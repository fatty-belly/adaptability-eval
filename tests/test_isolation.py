"""No-model regression tests for the process-local Harbor #1961 backport."""
import asyncio
from contextlib import contextmanager
import importlib.util
import inspect
import json
import linecache
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / 'evaluation/isolation.py'
spec = importlib.util.spec_from_file_location('shared_verifier_isolation24', MODULE)
iso = importlib.util.module_from_spec(spec)
spec.loader.exec_module(iso)


class ExceptionInfo:
    @classmethod
    def from_exception(cls, exc):
        return types.SimpleNamespace(exception_type=type(exc).__name__, message=str(exc))


class FakeEnvironment:
    def __init__(self, mounted):
        self.capabilities = types.SimpleNamespace(mounted=mounted)
        self.files = {'/tests/image-provided.txt': 'public', '/app/implementation.py': 'keep me'}

    @contextmanager
    def with_default_user(self, user):
        yield


class FixtureBase:
    def __init__(self, config, *, _task=None, _task_download_result):
        self.config = config
        self.events = []
        self.agent_environment = FakeEnvironment(config.mounted)
        self.fail_shared = False
        self.fail_cleanup = False

    def _now(self):
        return len(self.events)

    async def _reset_agent_logs_for_step(self, *, resume):
        self.events.append(('agent_logs', resume))

    def _step_agent_user(self, step):
        return 'agent'

    def _step_verifier_user(self, step):
        return 'verifier'

    def _step_verifier_timeout_sec(self, step):
        return 123

    async def _upload_step_workdir(self, step):
        self.events.append(('workdir', step.name))
        return '/app'

    async def _run_step_setup(self, step, result, workdir):
        self.events.append(('setup', step.name))
        if step.name == 'b' and getattr(self, iso.FLAG, False):
            raise AssertionError('Setup observed dirty verifier state')

    async def _run_step_healthcheck(self, step, result):
        self.events.append(('healthcheck', step.name))

    async def _emit(self, event):
        self.events.append(('emit', event))

    async def _reset_shared_step_verifier_dirs(self):
        self.events.append(('cleanup', None))
        if self.fail_cleanup:
            raise RuntimeError('simulated cleanup failure')
        for path in list(self.agent_environment.files):
            if path == '/tests' or path.startswith('/tests/') or path == '/logs/verifier' or path.startswith('/logs/verifier/'):
                del self.agent_environment.files[path]

    async def _run_shared_verifier(self, **kwargs):
        self.events.append(('shared', kwargs['step_name']))
        self.agent_environment.files['/tests/private-test.py'] = 'hidden assertion'
        self.agent_environment.files['/logs/verifier/reward.txt'] = '1'
        if self.fail_shared:
            raise ValueError('verifier failed after upload')
        return types.SimpleNamespace(rewards={'reward': 1})

    async def _run_separate_verifier(self, **kwargs):
        self.events.append(('separate', kwargs['key']))
        return types.SimpleNamespace(rewards={'reward': 1})


def compile_fixture(source, name):
    filename = f'<isolation-test-fixture:{name}>'
    linecache.cache[filename] = (len(source), None, source.splitlines(keepends=True), filename)
    namespace = {'StepConfig': types.SimpleNamespace, 'StepResult': types.SimpleNamespace,
                 'Path': Path, 'VerifierEnvironmentMode': types.SimpleNamespace(SEPARATE='separate'),
                 'TimingInfo': types.SimpleNamespace,
                 'TrialEvent': types.SimpleNamespace(VERIFICATION_START='verification_start'),
                 'ExceptionInfo': ExceptionInfo}
    exec(compile(source, filename, 'exec'), namespace)
    return namespace


def fixture_class(native_fixed=False):
    prepare = iso.PREPARE_023
    verifier = iso.VERIFIER_023
    if native_fixed:
        import ast
        p, v = iso._modified_trees(events=False)
        prepare, verifier = ast.unparse(p), ast.unparse(v)
    methods = compile_fixture(prepare + '\n\n' + verifier, 'fixed' if native_fixed else '023')

    class Fixture(FixtureBase):
        def __init__(self, config, *, _task=None, _task_download_result):
            super().__init__(config, _task=_task, _task_download_result=_task_download_result)
            if native_fixed:
                self._shared_verifier_dirs_need_reset = False

    Fixture._prepare_step = methods['_prepare_step']
    Fixture._run_step_verifier = methods['_run_step_verifier']
    return Fixture


def step(name):
    return types.SimpleNamespace(name=name, artifacts=[], verifier=types.SimpleNamespace(env={}))


def result():
    return types.SimpleNamespace(exception_info=None, verifier=None, verifier_result=None)


class IsolationTests(unittest.IsolatedAsyncioTestCase):
    def trial(self, mounted=False, disabled=False):
        cls = fixture_class()
        receipt = iso.install(cls)
        self.assertEqual(receipt['mode'], 'run_scoped_backport')
        config = types.SimpleNamespace(mounted=mounted, verifier=types.SimpleNamespace(disable=disabled))
        return cls(config, _task_download_result=None)

    async def test_first_step_preserves_image_tests_mounted_matrix(self):
        for mounted in (False, True):
            with self.subTest(mounted=mounted):
                trial = self.trial(mounted)
                self.assertFalse(getattr(trial, iso.FLAG))
                await trial._prepare_step(step('a'), result(), resume=False)
                self.assertIn('/tests/image-provided.txt', trial.agent_environment.files)
                self.assertFalse(any(e[0] == 'cleanup' for e in trial.events))

    async def test_shared_cleanup_before_workdir_setup_healthcheck_mounted_matrix(self):
        for mounted in (False, True):
            with self.subTest(mounted=mounted):
                trial = self.trial(mounted)
                await trial._prepare_step(step('a'), result(), resume=False)
                await trial._run_step_verifier(step('a'), result(), artifacts_dir=Path('/unused'), mode='shared')
                self.assertTrue(getattr(trial, iso.FLAG))
                start = len(trial.events)
                await trial._prepare_step(step('b'), result(), resume=True)
                self.assertEqual([e[0] for e in trial.events[start:]], ['agent_logs', 'cleanup', 'workdir', 'setup', 'healthcheck'])
                self.assertFalse(getattr(trial, iso.FLAG))
                self.assertNotIn('/tests/private-test.py', trial.agent_environment.files)
                self.assertNotIn('/logs/verifier/reward.txt', trial.agent_environment.files)
                self.assertEqual(trial.agent_environment.files['/app/implementation.py'], 'keep me')

    async def test_separate_preserves_agent_owned_tests(self):
        trial = self.trial()
        await trial._run_step_verifier(step('a'), result(), artifacts_dir=Path('/unused'), mode='separate')
        await trial._prepare_step(step('b'), result(), resume=False)
        self.assertFalse(getattr(trial, iso.FLAG))
        self.assertIn('/tests/image-provided.txt', trial.agent_environment.files)
        self.assertFalse(any(e[0] == 'cleanup' for e in trial.events))

    async def test_disabled_verification_does_not_mark_or_clean(self):
        trial = self.trial(disabled=True)
        await trial._run_step_verifier(step('a'), result(), artifacts_dir=Path('/unused'), mode='shared')
        await trial._prepare_step(step('b'), result(), resume=False)
        self.assertIn('/tests/image-provided.txt', trial.agent_environment.files)
        self.assertFalse(getattr(trial, iso.FLAG))
        self.assertFalse(any(e[0] in ('shared', 'cleanup') for e in trial.events))

    async def test_shared_to_separate_to_shared_mixed_modes(self):
        trial = self.trial()
        await trial._run_step_verifier(step('a'), result(), artifacts_dir=Path('/unused'), mode='shared')
        await trial._prepare_step(step('b'), result(), resume=True)
        self.assertNotIn('/tests/private-test.py', trial.agent_environment.files)
        trial.agent_environment.files['/tests/agent-owned.txt'] = 'preserve after separate'
        await trial._run_step_verifier(step('b'), result(), artifacts_dir=Path('/unused'), mode='separate')
        await trial._prepare_step(step('c'), result(), resume=True)
        self.assertIn('/tests/agent-owned.txt', trial.agent_environment.files)
        await trial._run_step_verifier(step('c'), result(), artifacts_dir=Path('/unused'), mode='shared')
        await trial._prepare_step(step('d'), result(), resume=True)
        self.assertNotIn('/tests/private-test.py', trial.agent_environment.files)

    async def test_failed_shared_still_requires_cleanup_and_keeps_native_exception(self):
        trial = self.trial()
        trial.fail_shared = True
        r = result()
        await trial._run_step_verifier(step('a'), r, artifacts_dir=Path('/unused'), mode='shared')
        self.assertEqual(r.exception_info.exception_type, 'ValueError')
        self.assertIsNotNone(r.verifier.finished_at)
        self.assertTrue(getattr(trial, iso.FLAG))
        await trial._prepare_step(step('b'), result(), resume=True)
        self.assertFalse(getattr(trial, iso.FLAG))
        self.assertNotIn('/tests/private-test.py', trial.agent_environment.files)

    async def test_cleanup_failure_aborts_before_any_setup_and_retains_dirty_flag(self):
        trial = self.trial()
        await trial._run_step_verifier(step('a'), result(), artifacts_dir=Path('/unused'), mode='shared')
        trial.fail_cleanup = True
        start = len(trial.events)
        with self.assertRaisesRegex(RuntimeError, 'cleanup failure'):
            await trial._prepare_step(step('b'), result(), resume=True)
        self.assertEqual([e[0] for e in trial.events[start:]], ['agent_logs', 'cleanup'])
        self.assertTrue(getattr(trial, iso.FLAG))

    async def test_global_disable_after_prior_shared_still_cleans_before_next_agent(self):
        trial = self.trial()
        await trial._run_step_verifier(step('a'), result(), artifacts_dir=Path('/unused'), mode='shared')
        trial.config.verifier.disable = True
        await trial._prepare_step(step('b'), result(), resume=True)
        self.assertFalse(getattr(trial, iso.FLAG))
        self.assertNotIn('/tests/private-test.py', trial.agent_environment.files)

    def test_idempotent_and_detects_post_install_tampering(self):
        cls = fixture_class()
        first = iso.install(cls)
        original = cls._prepare_step
        second = iso.install(cls)
        self.assertEqual(first['compiled_patch_sha256'], second['compiled_patch_sha256'])
        self.assertIs(cls._prepare_step, original)
        self.assertTrue(second['already_installed'])
        cls._prepare_step = lambda *a: None
        with self.assertRaisesRegex(iso.UnsupportedHarborLifecycle, 'changed after'):
            iso.install(cls)

    def test_native_fixed_recognized_without_replacement(self):
        cls = fixture_class(native_fixed=True)
        original = cls._prepare_step
        receipt = iso.install(cls)
        self.assertEqual(receipt['mode'], 'native_fix_already_present')
        self.assertIs(cls._prepare_step, original)

    def test_unknown_method_body_aborts_before_any_class_mutation(self):
        cls = fixture_class()
        wrong = compile_fixture(iso.PREPARE_023.replace('self._are_agent_logs_downloaded = False', 'self._are_agent_logs_downloaded = True'), 'unknown')['_prepare_step']
        cls._prepare_step = wrong
        before = cls.__init__, cls._run_step_verifier
        with self.assertRaisesRegex(iso.UnsupportedHarborLifecycle, 'Unknown native'):
            iso.install(cls)
        self.assertIs(cls.__init__, before[0])
        self.assertIs(cls._run_step_verifier, before[1])

    def test_unknown_constructor_signature_aborts(self):
        cls = fixture_class()
        cls.__init__ = lambda self, config: None
        with self.assertRaisesRegex(iso.UnsupportedHarborLifecycle, 'constructor signature'):
            iso.install(cls)

    async def test_provenance_event_file_and_native_scoring_retained(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {'HARBOR_SHARED_VERIFIER_ISOLATION_EVENTS': directory}):
            trial = self.trial()
            r = result()
            await trial._run_step_verifier(step('a'), r, artifacts_dir=Path('/unused'), mode='shared')
            self.assertEqual(r.verifier_result.rewards, {'reward': 1})
            await trial._prepare_step(step('b'), result(), resume=True)
            events = [json.loads(line)['event'] for path in Path(directory).glob('*.jsonl') for line in path.read_text().splitlines()]
            self.assertEqual(events, ['installing', 'trial_initialized_clean', 'shared_verifier_entered', 'cleaned_before_step_setup'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
