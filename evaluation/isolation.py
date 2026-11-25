"""Process-local Harbor 0.23 backport of upstream PR #1961.

Call install() before constructing trials in an explicitly selected worker.
Only MultiStepTrial methods are replaced in this Python process. Neither the
installed package nor task/test payloads are modified. Original 0.23 method ASTs
must match exactly; an unknown lifecycle aborts installation before mutation.

This implements the upstream directory lifecycle fix, not arbitrary cleanup of
task-specific verifier side effects elsewhere (for example temporary /tmp data).
"""
from __future__ import annotations

import ast
import copy
from datetime import datetime, timezone
import functools
import hashlib
import importlib.metadata
import inspect
import json
import linecache
import os
from pathlib import Path
import textwrap


PATCH_VERSION = 'harbor-1961-run-scoped-v1'
UPSTREAM = 'https://github.com/harbor-framework/harbor/pull/1961'
FLAG = '_shared_verifier_dirs_need_reset'
MARKER = '_adapt_shared_verifier_isolation_installation'

PREPARE_023 = '''\
async def _prepare_step(
    self,
    step: StepConfig,
    step_result: StepResult,
    *,
    resume: bool,
) -> None:
    self._are_agent_logs_downloaded = False
    await self._reset_agent_logs_for_step(resume=resume)

    with self.agent_environment.with_default_user(self._step_agent_user(step)):
        workdir = await self._upload_step_workdir(step)
        await self._run_step_setup(step, step_result, workdir)
        await self._run_step_healthcheck(step, step_result)
'''

VERIFIER_023 = '''\
async def _run_step_verifier(
    self,
    step: StepConfig,
    step_result: StepResult,
    *,
    artifacts_dir: Path,
    mode: VerifierEnvironmentMode,
) -> None:
    if self.config.verifier.disable:
        return

    step_result.verifier = TimingInfo(started_at=self._now())
    user = self._step_verifier_user(step)

    try:
        await self._emit(TrialEvent.VERIFICATION_START)

        if mode == VerifierEnvironmentMode.SEPARATE:
            step_result.verifier_result = await self._run_separate_verifier(
                key=step.name,
                timeout_sec=self._step_verifier_timeout_sec(step),
                artifacts_dir=artifacts_dir,
                artifacts=step.artifacts,
                step_cfg=step,
                user=user,
                env=step.verifier.env or None,
            )
        else:
            await self._reset_shared_step_verifier_dirs()
            step_result.verifier_result = await self._run_shared_verifier(
                timeout_sec=self._step_verifier_timeout_sec(step),
                user=user,
                env=step.verifier.env or None,
                step_name=step.name,
                step_cfg=step,
            )
    except Exception as exc:
        if step_result.exception_info is None:
            step_result.exception_info = ExceptionInfo.from_exception(exc)
    finally:
        step_result.verifier.finished_at = self._now()
'''


class UnsupportedHarborLifecycle(RuntimeError):
    pass


def _tree(source):
    module = ast.parse(textwrap.dedent(source))
    if len(module.body) != 1 or not isinstance(module.body[0], (ast.FunctionDef, ast.AsyncFunctionDef)):
        raise UnsupportedHarborLifecycle('Expected exactly one lifecycle function')
    return module


def _shape(tree):
    return ast.dump(tree, annotate_fields=True, include_attributes=False)


def _digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _source(method):
    try:
        return textwrap.dedent(inspect.getsource(method))
    except (OSError, TypeError) as error:
        raise UnsupportedHarborLifecycle('Cannot inspect native lifecycle source') from error


def _event(event, **values):
    directory = os.environ.get('HARBOR_SHARED_VERIFIER_ISOLATION_EVENTS')
    if not directory:
        return
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    payload = {'at': datetime.now(timezone.utc).isoformat(), 'pid': os.getpid(),
               'patch_version': PATCH_VERSION, 'event': event, **values}
    descriptor = os.open(root / f'{os.getpid()}.jsonl', os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(descriptor, (json.dumps(payload, ensure_ascii=False) + '\n').encode())
    finally:
        os.close(descriptor)


def _modified_trees(*, events):
    prepare = _tree(PREPARE_023)
    verifier = _tree(VERIFIER_023)
    cleanup = f'''\
if self.{FLAG}:
    await self._reset_shared_step_verifier_dirs()
    self.{FLAG} = False
'''
    if events:
        cleanup += "    _shared_isolation_event('cleaned_before_step_setup', step=step.name)\n"
    prepare.body[0].body.insert(2, ast.parse(cleanup).body[0])
    # Preserve native disable checks, exception recording, per-step scoring and
    # all verifier arguments. The only inserted statement marks a SHARED run.
    shared_branch = verifier.body[0].body[3].body[1].orelse
    assert isinstance(verifier.body[0].body[3], ast.Try)
    assert isinstance(verifier.body[0].body[3].body[1], ast.If)
    shared_branch.insert(1, ast.parse(f'self.{FLAG} = True').body[0])
    if events:
        shared_branch.insert(2, ast.parse("_shared_isolation_event('shared_verifier_entered', step=step.name)").body[0])
    ast.fix_missing_locations(prepare)
    ast.fix_missing_locations(verifier)
    return prepare, verifier


def _compile_method(original, tree, label):
    source = ast.unparse(tree) + '\n'
    filename = f'<{PATCH_VERSION}:{label}>'
    linecache.cache[filename] = (len(source), None, source.splitlines(keepends=True), filename)
    namespace = dict(original.__globals__)
    namespace['_shared_isolation_event'] = _event
    exec(compile(tree, filename, 'exec'), namespace)
    method = namespace[tree.body[0].name]
    method.__module__ = original.__module__
    method.__qualname__ = original.__qualname__
    method._shared_isolation_original = original
    return method, source


def _init_shape_ok(method):
    signature = inspect.signature(method)
    params = list(signature.parameters.values())
    return ([p.name for p in params] == ['self', 'config', '_task', '_task_download_result']
            and params[2].kind is inspect.Parameter.KEYWORD_ONLY
            and params[3].kind is inspect.Parameter.KEYWORD_ONLY
            and params[2].default is None
            and params[3].default is inspect.Parameter.empty)


def _native_init_has_flag(source):
    node = _tree(source)
    return any(isinstance(statement, ast.Assign)
               and isinstance(statement.value, ast.Constant) and statement.value.value is False
               and any(isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                       and target.value.id == 'self' and target.attr == FLAG for target in statement.targets)
               for statement in ast.walk(node))


def install(target_class=None):
    """Install once on the process's MultiStepTrial, returning an audit receipt.

    target_class exists for isolated tests; production callers omit it. Unknown
    source/signatures or a later modification of installed methods fail closed.
    """
    if target_class is None:
        from harbor.trial.multi_step import MultiStepTrial
        target_class = MultiStepTrial
    cls = target_class
    existing = cls.__dict__.get(MARKER)
    if existing is not None:
        if existing.get('version') != PATCH_VERSION:
            raise UnsupportedHarborLifecycle('Conflicting isolation installation marker')
        for name, method in existing['methods'].items():
            if getattr(cls, name) is not method:
                raise UnsupportedHarborLifecycle('Lifecycle changed after isolation installation: ' + name)
        return dict(existing['receipt'], already_installed=True)

    originals = {name: getattr(cls, name) for name in ('__init__', '_prepare_step', '_run_step_verifier')}
    if not _init_shape_ok(originals['__init__']):
        raise UnsupportedHarborLifecycle('Unknown MultiStepTrial constructor signature')
    sources = {name: _source(method) for name, method in originals.items()}
    prepare = _tree(sources['_prepare_step'])
    verifier = _tree(sources['_run_step_verifier'])
    fixed_prepare, fixed_verifier = _modified_trees(events=False)
    native_fixed = (_shape(prepare) == _shape(fixed_prepare)
                    and _shape(verifier) == _shape(fixed_verifier)
                    and _native_init_has_flag(sources['__init__']))
    native_original = (_shape(prepare) == _shape(_tree(PREPARE_023))
                       and _shape(verifier) == _shape(_tree(VERIFIER_023)))
    if not native_fixed and not native_original:
        raise UnsupportedHarborLifecycle('Unknown native step lifecycle; refusing heuristic patch')
    try:
        harbor_version = importlib.metadata.version('harbor')
    except importlib.metadata.PackageNotFoundError:
        harbor_version = 'test_fixture'
    receipt = {'patch_version': PATCH_VERSION, 'upstream': UPSTREAM,
               'harbor_version': harbor_version, 'pid': os.getpid(),
               'at': datetime.now(timezone.utc).isoformat(),
               'class': cls.__module__ + '.' + cls.__qualname__,
               'native_source_sha256': {name: _digest(src) for name, src in sources.items()},
               'module_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'mode': 'native_fix_already_present' if native_fixed else 'run_scoped_backport',
               'site_packages_modified': False, 'task_payload_modified': False}
    if native_fixed:
        _event('native_fix_verified', receipt=receipt)
        return dict(receipt, already_installed=False)

    trees = _modified_trees(events=True)
    new_prepare, prepare_source = _compile_method(originals['_prepare_step'], trees[0], '_prepare_step')
    new_verifier, verifier_source = _compile_method(originals['_run_step_verifier'], trees[1], '_run_step_verifier')
    native_init = originals['__init__']

    @functools.wraps(native_init)
    def initialized(self, *args, **kwargs):
        setattr(self, FLAG, False)
        native_init(self, *args, **kwargs)
        _event('trial_initialized_clean')

    receipt['compiled_patch_sha256'] = {'_prepare_step': _digest(prepare_source),
                                        '_run_step_verifier': _digest(verifier_source)}
    installed = {'__init__': initialized, '_prepare_step': new_prepare, '_run_step_verifier': new_verifier}
    # All inspection and compilation has succeeded; no mutation occurs earlier.
    _event('installing', receipt=receipt)
    for name, method in installed.items():
        setattr(cls, name, method)
    setattr(cls, MARKER, {'version': PATCH_VERSION, 'receipt': receipt, 'methods': installed})
    return dict(receipt, already_installed=False)
