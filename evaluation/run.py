"""Run the released Harbor evaluation conditions with one shared sample ledger."""
from argparse import ArgumentParser
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import time

from harbor.models.task.task import Task
from evaluation.retries import retryable_exception, retry_delay
from evaluation.prepare_data import ARTIFACT_FAMILIES

REPO = Path(__file__).resolve().parents[1]
ARMS = ('baseline', 'full', 'reset', 'oracle')
BASE_AGENTS = {'baseline': 'evaluation.terminus:FinalTerminus2',
               'full': 'evaluation.continuous:ContinuousTerminus2'}


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.new')
    temporary.write_text(json.dumps(data, indent=2) + '\n', encoding='utf8')
    temporary.replace(path)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def discover(data_dir, include):
    families = {}
    for marker in sorted(data_dir.rglob('task.toml')):
        parts = marker.relative_to(data_dir).parts
        if len(parts) < 6 or parts[-4] != 'families' or parts[-5] not in ('two-turn', 'multiround'):
            continue
        ident, variant, track = parts[-3], parts[-2], parts[-5]
        direct = 'direct-b' if track == 'two-turn' else 'direct-final'
        if variant not in ('adapt', direct) or (include and ident not in include):
            continue
        family = families.setdefault(ident, {'id': ident, 'track': track, 'variants': {}})
        if family['track'] != track or variant in family['variants']:
            raise ValueError(f'Duplicate or conflicting task identity: {ident}/{variant}')
        task = Task(marker.parent)
        steps = [s.name for s in (task.config.steps or [])]
        if variant == 'adapt':
            if ident in ARTIFACT_FAMILIES and not any(getattr(a, 'source', a)=='/app' for a in task.config.artifacts):
                raise ValueError(f'Missing /app artifact declaration for {ident}. Run python -m evaluation.prepare_data first.')
            if len(steps) < 2 or (track == 'two-turn' and steps != ['a', 'b']):
                raise ValueError(f'Unexpected stage sequence: {ident} {steps}')
            if any(step.min_reward is not None for step in task.config.steps):
                raise ValueError(f'Stage success gating is incompatible with full evaluation: {ident}')
        elif steps:
            raise ValueError(f'Direct task must be single-step: {ident}')
        family['variants'][variant] = {'path': str(marker.parent), 'checksum': task.checksum, 'steps': steps}
    if not families or (include and set(families) != include):
        raise ValueError('The requested families were not found in the extracted Harbor archive')
    for family in families.values():
        if len(family['variants']) != 2:
            raise ValueError(f"Expected one adapt and one direct package for {family['id']}")
    return list(families.values())


def slot_path(root, arm, ident, slot):
    return root / 'arms' / arm / ident / f's{slot:02d}'


def checkpoint(root, ident, slot):
    state = read(slot_path(root, 'full', ident, slot) / 'result.json')
    if state['status'] != 'completed' or len(state['rewards']) != 2:
        raise ValueError(f'Full result is missing or invalid: {ident} slot {slot}')
    source = Path(state['native_result'])
    if digest(source) != state['native_result_sha256']:
        raise ValueError(f'Full result changed: {ident} slot {slot}')
    artifacts = source.parent / 'steps/a/artifacts'
    mappings = []
    for record in read(artifacts/'manifest.json'):
        if record['source'].startswith('/logs/'):
            continue
        dest = PurePosixPath(record['destination'])
        if not dest.is_relative_to('artifacts') or '..' in dest.parts or record['status'] != 'ok':
            raise ValueError(f'Invalid checkpoint receipt: {ident} slot {slot}')
        local = dest.relative_to('artifacts')
        if not (artifacts/local).exists():
            raise ValueError(f'Checkpoint path is missing: {ident} slot {slot}')
        mappings.append({'source': record['source'], 'local': str(local)})
    if not mappings:
        raise ValueError(f'No saved A workspace for {ident} slot {slot}. Run evaluation.prepare_data and collect a fresh full result.')
    return {'a_artifacts': str(artifacts), 'mappings': mappings, 'a_reward': state['rewards'][0],
            'full_b_reward': state['rewards'][1], 'source_result': str(source),
            'source_sha256': state['native_result_sha256']}


def collect(execution, arm, variant, row):
    paths = list((execution/'native').glob('*/result.json'))
    if len(paths) != 1:
        raise RuntimeError(f'Expected one native result under {execution}; inspect its Harbor log')
    path = paths[0]
    raw = read(path)
    if not raw.get('finished_at'):
        raise RuntimeError(f'Native result is still active or unfinished: {path}')
    if raw['task_checksum'] != variant['checksum']:
        raise ValueError(f'Native result task identity mismatch: {path}')
    steps = [raw] if arm=='baseline' else raw.get('step_results') or []
    names = [step.get('step_name') for step in steps] if arm!='baseline' else []
    errors = [item for item in [raw.get('exception_info'), *(s.get('exception_info') for s in steps)] if item]
    rewards = [((s.get('verifier_result') or {}).get('rewards') or {}).get('reward') for s in steps]
    calls = [(((s.get('agent_result') or {}).get('metadata') or {}).get('resources') or {}).get('llm_calls')
             for s in steps]
    complete = (bool(steps) and names==variant['steps'] and
                all(type(r) in (float,int) and r in (0,1) for r in rewards) and
                all((s.get('verifier') or {}).get('finished_at') for s in steps) and
                all(e['exception_type']=='AgentTimeoutError' for e in errors))
    if arm in BASE_AGENTS:
        complete = complete and all(type(c) is int and c>0 for c in calls)
    else:
        meta = ((steps[-1].get('agent_result') or {}).get('metadata') or {}) if steps else {}
        expected_a = row['a_reward'] if arm=='reset' else 1
        complete = (complete and len(rewards)==2 and rewards[0]==expected_a and
                    type(calls[-1]) is int and calls[-1]>0 and meta.get('ablation',{}).get('fresh_chat') is True)
    if arm=='baseline' and len(errors)>0 and all(e['exception_type']=='AgentTimeoutError' for e in errors):
        # A saved submission can have a native score even if the agent timed out.
        complete = (all(type(r) in (float,int) and r in (0,1) for r in rewards) and
                    all((s.get('verifier') or {}).get('finished_at') for s in steps))
    retryable = any(retryable_exception(e['exception_type'], e.get('exception_message','')) or
                    e['exception_type'].rsplit('.',1)[-1] in ('BadGatewayError','GatewayTimeoutError') for e in errors)
    return {'status':'completed' if complete else 'error', 'rewards':rewards, 'llm_calls':calls,
            'error_types':sorted({e['exception_type'] for e in errors}), 'retryable':retryable,
            'native_result':str(path), 'native_result_sha256':digest(path), 'at':now()}


def execute(root, cfg, arm, family, slot, input_row):
    folder = slot_path(root, arm, family['id'], slot)
    folder.mkdir(parents=True, exist_ok=True)
    status = folder/'result.json'
    if status.exists():
        previous = read(status)
        if digest(Path(previous['native_result'])) != previous['native_result_sha256']:
            raise ValueError(f'Accepted native result changed: {status}')
        return previous
    variant = family['variants']['adapt'] if arm!='baseline' else next(
        value for name,value in family['variants'].items() if name.startswith('direct-'))
    task = Task(Path(variant['path']))
    if task.checksum != variant['checksum']:
        raise ValueError(f"Task changed after preparation: {variant['path']}")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', LITELLM_LOCAL_MODEL_COST_MAP='True',
               DISABLE_AIOHTTP_TRANSPORT='True', TMPDIR=str(root/'runtime/tmp'),
               TEMP=str(root/'runtime/tmp'), TMP=str(root/'runtime/tmp'),
               ADAPTABILITY_DOCKER_TOOLING=str(root/'runtime/docker-tooling'))
    env.pop('ADAPTABILITY_DOCKER_BUILD_NETWORK', None)
    if cfg.get('docker_build_network'):
        env['ADAPTABILITY_DOCKER_BUILD_NETWORK'] = cfg['docker_build_network']
    if cfg.get('api_base'):
        env.update(OPENAI_BASE_URL=cfg['api_base'], OPENAI_API_BASE=cfg['api_base'])
    if input_row is not None:
        request=folder/'input.json'
        if request.exists() and read(request)!=input_row:
            raise ValueError(f'Paired checkpoint changed: {request}')
        write(request,input_row)
        env.update(ABLATION_INPUT=str(request), ABLATION_TASK=variant['path'])
    for index in range(cfg['max_retries']+1):
        execution = folder/f'execution-{index:02d}'
        if not execution.exists():
            while shutil.disk_usage(root).free < cfg['min_free_gib'] * 2**30 or shutil.disk_usage('/').free < 2**30:
                print(f'Waiting for storage before {arm}/{family["id"]}/s{slot:02d}',flush=True)
                time.sleep(30)
            execution.mkdir()
            command=[sys.executable,'-B','-m','evaluation.harbor_entry','run','--env',cfg['environment'],
                     '--agent-import-path',BASE_AGENTS.get(arm,'evaluation.agents:AblationTerminus2'),
                     '--model',cfg['model'],'--path',variant['path'],'--jobs-dir',str(execution),
                     '--job-name','native','--n-attempts','1','--n-concurrent','1','--max-retries','0','--yes',
                     '--cpus','ignore','--memory','ignore','--agent-kwarg',f"reasoning_effort={cfg['reasoning_effort']}",
                     '--agent-kwarg','store_all_messages=true',
                     '--agent-kwarg','trajectory_config={"raw_content":true,"linear_history":true}',
                     '--agent-kwarg','record_terminal_session=false']
            if arm=='full':
                command.append('--resume-trajectory')
            write(execution/'invocation.json',{'at':now(),'task_checksum':variant['checksum'],'command':command})
            with (execution/'harbor.log').open('x',encoding='utf8') as log:
                subprocess.run(command,cwd=REPO,env=env,stdout=log,stderr=subprocess.STDOUT,check=False)
        result=collect(execution,arm,variant,input_row)
        if result['status']=='completed' or not result['retryable'] or index==cfg['max_retries']:
            write(status,result)
            return result
        time.sleep(retry_delay({'delay_seconds':5,'max_delay_seconds':60},index+1))


def report(root, families, attempts):
    by_arm=defaultdict(Counter)
    by_track=defaultdict(lambda: defaultdict(Counter))
    for family in families:
        for arm in ARMS if family['track']=='two-turn' else ARMS[:2]:
            for slot in range(1,attempts+1):
                counts=by_arm[arm]
                group=by_track[family['track']][arm]
                for c in (counts,group):c['planned']+=1
                path=slot_path(root,arm,family['id'],slot)/'result.json'
                if not path.exists():continue
                result=read(path)
                for c in (counts,group):
                    c[result['status']]+=1
                    if result['status']=='completed':c['passed']+=int(result['rewards'][-1]==1)
    summary={'at':now(),'conditions':by_arm,'tracks':by_track}
    write(root/'summary.json',summary)
    print(json.dumps(summary,indent=2),flush=True)


def main():
    parser=ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,required=True,help='Directory containing the extracted task archive')
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--config',type=Path,default=Path(__file__).with_name('example.json'))
    parser.add_argument('--model',help='Override the model in the JSON configuration')
    parser.add_argument('--arms',default='all',help='all or a comma-separated subset of baseline,full,reset,oracle')
    parser.add_argument('--include',nargs='+',default=[],help='Optional family IDs for a small run')
    parser.add_argument('--dry-run',action='store_true',help='Validate data and show sample counts without launching a model')
    args=parser.parse_args()
    cfg=read(args.config)
    if args.model:cfg['model']=args.model
    for name in ('attempts','concurrency','min_free_gib'):
        if type(cfg[name]) is not int or cfg[name]<1:raise ValueError(f'{name} must be a positive integer')
    if type(cfg['max_retries']) is not int or cfg['max_retries']<0:raise ValueError('max_retries must be a nonnegative integer')
    if cfg.get('docker_build_network') not in (None, 'host', 'default', 'none'):
        raise ValueError('docker_build_network must be null, host, default or none')
    arms=set(ARMS) if args.arms=='all' else set(args.arms.split(','))
    if not arms or not arms <= set(ARMS):raise ValueError('Invalid evaluation conditions')
    families=discover(args.data.resolve(),set(args.include))
    count=sum(f['track']=='two-turn' for f in families)
    print(json.dumps({'families':len(families),'two_turn':count,'model':cfg['model'],
                      'planned':{a:cfg['attempts']*(len(families) if a in BASE_AGENTS else count) for a in ARMS if a in arms}}),flush=True)
    if args.dry_run:return
    root=args.run_dir.resolve()
    root.mkdir(parents=True,exist_ok=True)
    (root/'runtime/tmp').mkdir(parents=True,exist_ok=True)
    with (root/'run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest=root/'run-plan.json'
        plan={'configuration':cfg,'families':families}
        if manifest.exists() and read(manifest)!=plan:raise ValueError('Run configuration or task identities changed; use a new run directory')
        write(manifest,plan)
        failed=False
        for stage in (ARMS[:2], ARMS[2:]):
            work=[]
            for slot in range(1,cfg['attempts']+1):
                for family in families:
                    for arm in stage:
                        if arm not in arms or (arm not in BASE_AGENTS and family['track']!='two-turn'):continue
                        row=None if arm in BASE_AGENTS else dict(checkpoint(root,family['id'],slot),arm=arm)
                        work.append((root,cfg,arm,family,slot,row))
            with ThreadPoolExecutor(max_workers=cfg['concurrency']) as pool:
                for result in pool.map(lambda item:execute(*item),work):
                    failed |= result['status']!='completed'
        report(root,families,cfg['attempts'])
        if failed:raise SystemExit(1)


if __name__=='__main__':
    main()
