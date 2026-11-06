import json
import subprocess

import pytest

from engine import evaluate
from sandbox.runner import MAX_BYTES,SandboxError,command,run
from sandbox.worker import process
from tests.conftest import EXAMPLES,SCENARIOS,load


@pytest.mark.parametrize('scenario',SCENARIOS)
def test_worker_matches_engine(scenario):
    plan=load(EXAMPLES/'test_plan.json')
    before=load(EXAMPLES/scenario/'before.json');after=load(EXAMPLES/scenario/'after.json')
    r=process(dict(plan=plan,before=before,after=after))
    results,changes=evaluate(plan,before,after)
    assert r=={'results':results,'unexpected_changes':changes}


def test_worker_rejects_extra_input_and_bad_schema():
    with pytest.raises(ValueError):process({'script':'anything'})
    with pytest.raises(Exception):process({'plan':{},'before':{},'after':{}})


def test_sandbox_command_has_restrictions_and_no_mounts():
    args=command('image','name')
    for flag,value in [('--network','none'),('--user','65532:65532'),('--cap-drop','ALL'),
                       ('--memory','128m'),('--pids-limit','32'),('--cpus','0.5')]:
        assert args[args.index(flag)+1]==value
    assert '--read-only' in args
    assert '--mount' not in args and '-v' not in args
    assert not any('SF_' in a or 'VULTR_' in a for a in args)
    assert 'HTTP_PROXY=' in args and 'https_proxy=' in args


def response(code=0,data=None,stderr=b''):
    return subprocess.CompletedProcess([],code,json.dumps(data or {'results':[],'unexpected_changes':[]}).encode(),stderr)


def test_runner_cleanup_success_and_no_fallback():
    calls=[]
    def invoke(args,**kw):
        calls.append((args,kw))
        return response()
    output,events=run({'plan':{}},invoke=invoke)
    assert output['results']==[]
    assert calls[0][0][:2]==['docker','run'] and calls[1][0][:3]==['docker','rm','-f']
    assert calls[0][1]['timeout']==15
    assert events[-1]['type']=='cleanup' and events[-1]['blocked'] is True


def test_timeout_always_cleans_up():
    calls=[]
    def invoke(args,**kw):
        calls.append(args)
        if args[1]=='run':raise subprocess.TimeoutExpired(args,15)
        return response()
    with pytest.raises(SandboxError) as e:run({},invoke=invoke)
    assert [e['type'] for e in e.value.events]==['timeout','cleanup']
    assert len(calls)==2


def test_auto_removed_container_is_confirmed_absent():
    def invoke(args,**kw):
        return response(1,stderr=b'Error: No such container: name') if args[1]=='rm' else response()
    assert run({},invoke=invoke)[1][-1]['blocked'] is True


def test_cleanup_failure_rejects_even_successful_evaluation():
    def invoke(args,**kw):
        return response(1,stderr=b'cannot connect') if args[1]=='rm' else response()
    with pytest.raises(SandboxError,match='cleanup'):run({},invoke=invoke)


def test_missing_docker_is_error_not_host_execution():
    def invoke(*a,**kw):raise FileNotFoundError()
    with pytest.raises(SandboxError):run({},invoke=invoke)


def test_input_limit_before_docker():
    def invoke(*a,**kw):pytest.fail('Docker should not start')
    with pytest.raises(SandboxError):run({'data':'x'*MAX_BYTES},invoke=invoke)


@pytest.mark.parametrize('body',[{},[],{'results':'bad','unexpected_changes':[]}])
def test_bad_output_never_passes(body):
    def invoke(args,**kw):
        return subprocess.CompletedProcess(args,0,json.dumps(body).encode(),b'')
    with pytest.raises(SandboxError):run({},invoke=invoke)


def test_image_preserves_worker_contract_path_layout(tmp_path, monkeypatch):
    from pathlib import Path
    from sandbox import worker
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / 'sandbox' / 'Dockerfile').read_text()
    assert 'COPY sandbox/worker.py /app/sandbox/worker.py' in dockerfile
    assert '"/app/sandbox/worker.py"' in dockerfile
    app = tmp_path / 'app'
    (app / 'sandbox').mkdir(parents=True)
    import shutil
    shutil.copytree(root / 'contracts', app / 'contracts')
    monkeypatch.setattr(worker, '__file__', str(app / 'sandbox' / 'worker.py'))
    payload = {'plan':load(EXAMPLES/'test_plan.json'),
               'before':load(EXAMPLES/'success'/'before.json'),
               'after':load(EXAMPLES/'success'/'after.json')}
    assert {r['status'] for r in worker.process(payload)['results']} == {'passed'}
