"""Two-turn ablation. Only B calls the model; Harbor grades both stages."""
import json
import os
import shlex
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

from harbor.agents.oracle import OracleAgent
from harbor.models.trial.paths import EnvironmentPaths
from harbor.trial.multi_step import MultiStepTrial
from evaluation.terminus import FinalTerminus2

PREFIX = 'Continue from the existing implementation in the workspace.\n\n'


class AblationTerminus2(FinalTerminus2):
    async def run(self, instruction, environment, context):
        trial, step = self.ablation_phase
        row = json.loads(Path(os.environ['ABLATION_INPUT']).read_text())
        if step.name == 'a':
            if row['arm'] == 'reset':
                await restore(environment, row, self.logs_dir)
            else:
                await self.run_a_oracle(trial, instruction, environment, context)
            context.metadata = {'new_model_calls': 0, 'state_source': row['arm']}
            return

        assert step.name == 'b' and len(trial.result.step_results) == 2
        previous = trial.result.step_results[0]
        expected_a = row['a_reward'] if row['arm'] == 'reset' else 1
        if previous.exception_info or not previous.verifier_result or previous.verifier_result.rewards.get('reward') != expected_a:
            raise RuntimeError('A checkpoint did not reproduce its expected native verifier reward')
        if getattr(self, '_chat', None) is not None:
            raise RuntimeError('B must start a new model conversation')
        try:
            await super().run(PREFIX + instruction, environment, context)
        finally:
            if context.metadata is None:
                context.metadata = {}
            context.metadata['ablation'] = {'fresh_chat': True, 'arm': row['arm'], 'a_reward': expected_a}

    async def run_a_oracle(self, trial, instruction, environment, context):
        oracle = OracleAgent(logs_dir=self.logs_dir, task_dir=Path(os.environ['ABLATION_TASK']),
                            trial_paths=trial.paths, agent_timeout_sec=trial._step_agent_timeout_sec(self.ablation_phase[1]))
        await oracle.run(instruction, environment, context)
        if (trial.paths.agent_dir / 'exit-code.txt').exists():
            raise RuntimeError('A oracle exited unsuccessfully')
        path = EnvironmentPaths.for_os(environment.os).solution_dir
        result = await environment.exec(command=f'rm -rf -- {shlex.quote(str(path))}', user='root', cwd='/')
        if result.return_code:
            raise RuntimeError('Could not remove private A oracle files before B')



async def restore(environment, row, logs_dir):
    source = Path(row['a_artifacts'])
    for mapping in row['mappings']:
        target = PurePosixPath(mapping['source'])
        if (not target.is_absolute() or '..' in target.parts or
                not any(target.is_relative_to(PurePosixPath(root)) for root in ('/app','/workspace'))):
            raise ValueError(f'Unsupported checkpoint path {target}')
        node = source / mapping['local']
        if not node.is_symlink() and not node.resolve().is_relative_to(source.resolve()):
            raise ValueError('Checkpoint input escaped its artifact directory')
        with tempfile.TemporaryDirectory(dir=logs_dir) as folder:
            archive = Path(folder) / 'checkpoint.tar'
            with tarfile.open(archive, 'w', dereference=False) as out:
                out.add(node, arcname=target.name)
            remote = '/tmp/ablation-a-checkpoint.tar'
            await environment.upload_file(archive, remote)
            command = '''set -eu
stage=$(mktemp -d /tmp/ablation-stage.XXXXXX)
trap 'rm -rf -- "$stage"; rm -f -- "$archive"' EXIT
tar --numeric-owner -xpf "$archive" -C "$stage"
if [ -d "$stage/$name" ] && [ ! -L "$stage/$name" ] && [ -d "$target" ] && [ ! -L "$target" ]; then
  find "$target" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
  cp -a -- "$stage/$name/." "$target/"
else
  rm -rf -- "$target"
  mkdir -p -- "$parent"
  cp -a -- "$stage/$name" "$target"
fi
tar --compare --numeric-owner -f "$archive" -C "$parent"
'''
            variables = {'archive':remote, 'target':str(target), 'parent':str(target.parent), 'name':target.name}
            script = '\n'.join(f'{k}={shlex.quote(v)}' for k,v in variables.items()) + '\n' + command
            result = await environment.exec(command='bash -c ' + shlex.quote(script), user='root', cwd='/')
            if result.return_code:
                raise RuntimeError('A snapshot restore or byte comparison failed: ' + str(result.stderr)[-600:])


def install_ablation():
    native_run = MultiStepTrial._run_step_agent

    async def run_step(trial, step, result, **kwargs):
        if isinstance(trial.agent, AblationTerminus2):
            if kwargs.get('resume') or kwargs.get('load'):
                raise ValueError('Ablation cannot load or resume any conversation')
            trial.agent.ablation_phase = (trial, step)
        await native_run(trial, step, result, **kwargs)

    MultiStepTrial._run_step_agent = run_step
