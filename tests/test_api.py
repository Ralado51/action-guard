"""API lifecycle using real validation and engine, simulated upstream services."""
import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from connector.transport import UrllibTransport
from planner.__main__ import fixture_metadata
from tests import sim
from tests.conftest import EXAMPLES, load
from web.app.main import app, workflow
from web.app.service import Workflow, WorkflowError

TOKEN = 'test-app-token'
HASH = 'sha256:' + 'a' * 64
HEADERS = {'Authorization': 'Bearer ' + TOKEN}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('ACTION_GUARD_API_TOKEN', TOKEN)
    for k,v in {'SF_LOGIN_URL':'https://example.my.salesforce.com','SF_API_VERSION':'68.0',
                'SF_AGENT_ID':'0XxSYN','SF_CLIENT_ID':'cid','SF_CLIENT_SECRET':sim.CLIENT_SECRET}.items():
        monkeypatch.setenv(k,v)
    meta = fixture_metadata()
    meta['source'] = 'salesforce_describe'
    meta['collected_at'] = '2026-11-05T12:00:00Z'
    path = tmp_path / 'metadata.json'
    path.write_text(json.dumps(meta))
    monkeypatch.setenv('SF_METADATA_PATH', str(path))
    calls = []
    def generate(rule, metadata, action):
        calls.append(rule)
        plan = load(EXAMPLES / 'test_plan_draft.json')
        plan['rule_id'] = rule['rule_id']
        return plan, {'metadata_source': 'salesforce_describe', 'model':'test-model','calls':1}
    svc = Workflow(tmp_path / 'data', generate=generate)
    fake = sim.FakeSalesforce()
    monkeypatch.setattr('web.app.service.UrllibTransport', lambda: fake)
    app.dependency_overrides[workflow] = lambda: svc
    with TestClient(app, headers=HEADERS) as client:
        yield client, svc, fake, calls
    app.dependency_overrides.clear()


def create(client):
    r = client.post('/api/plans', json={'rule_text_pt':'Encerrar Case e verificar os efeitos.',
                                       'closure_reason':sim.REASON})
    assert r.status_code == 201, r.text
    return r.json()


def bind(client, plan):
    r=client.post('/api/plans/'+plan['plan_id']+'/case', json={'case_id':sim.CASE,'expected_plan_hash':plan['plan_hash']})
    assert r.status_code == 200, r.text
    return r.json()


def approve(client, plan):
    return client.post('/api/plans/'+plan['plan_id']+'/approve', json={
        'approved_by':'operator','approved_plan_hash':plan['plan_hash']})


def test_health_and_ui_are_public(setup):
    client, *_ = setup
    assert client.get('/health').json() == {'status':'ok','service':'action-guard'}
    assert 'Action Guard' in client.get('/').text
    assert client.get('/static/app.js').status_code == 200


def test_api_requires_token_and_configured_auth(setup, monkeypatch):
    client, svc, fake, calls = setup
    assert client.get('/api/plans/x', headers={'Authorization':''}).status_code == 401
    monkeypatch.delenv('ACTION_GUARD_API_TOKEN')
    assert client.get('/api/plans/x').status_code == 503
    assert fake.log == [] and calls == []


def test_full_api_lifecycle_with_real_engine(setup):
    client, svc, fake, calls = setup
    p = create(client)
    assert p['approval'] is None and fake.action_calls == 0
    assert approve(client, p).status_code == 409
    oldhash = p['plan_hash']
    p = bind(client, p)
    assert p['plan_version'] == 2 and p['plan_hash'] != oldhash
    assert approve(client,p).status_code == 200
    r = client.post('/api/runs',json={'approved_plan_id':p['plan_id'],'expected_plan_hash':p['plan_hash']})
    assert r.status_code == 202, r.text
    rid = r.json()['run_id']
    assert client.get('/api/plans/'+p['plan_id']+'/runs').json()[0]['run_id'] == rid
    report = client.get('/api/runs/'+rid+'/report').json()
    assert report['status'] == 'passed' and fake.action_calls == 1
    assert len(calls) == 1
    assert client.post('/api/runs',json={'approved_plan_id':p['plan_id'],'expected_plan_hash':p['plan_hash']}).status_code == 409
    assert fake.action_calls == 1
    # Reloading service retains approval, run and replay reservation.
    loaded = Workflow(svc.root)
    assert loaded.run(rid)['report']['status'] == 'passed'
    assert loaded.get(p['plan_id'])['approval']['approved_by'] == 'operator'


def test_edit_invalidates_approval_and_stale_hashes(setup):
    client, svc, fake, calls = setup
    p=bind(client,create(client))
    assert approve(client,p).status_code == 200
    edited=copy.deepcopy(p)
    edited['checks'][0]['description']='Descricao revisada'
    r=client.put('/api/plans/'+p['plan_id'],json={'plan':edited,'expected_plan_hash':p['plan_hash']})
    assert r.status_code == 200, r.text
    assert r.json()['approval'] is None
    assert approve(client,p).status_code == 409
    assert client.post('/api/runs',json={'approved_plan_id':p['plan_id'],'expected_plan_hash':p['plan_hash']}).status_code == 409
    assert client.put('/api/plans/'+p['plan_id'],json={'plan':edited,'expected_plan_hash':p['plan_hash']}).status_code == 409
    assert fake.action_calls == 0


@pytest.mark.parametrize('change',['owner','preconditions','count','action'])
def test_mandatory_conditions_cannot_be_weakened(setup,change):
    client,*_=setup
    p=bind(client,create(client)); edited=copy.deepcopy(p)
    if change=='owner':
        edited['checks']=[c for c in edited['checks'] if c['check_id']!='chk_owner_unchanged']
    elif change=='preconditions':
        edited['preconditions']=[]
    elif change=='count':
        next(c for c in edited['checks'] if c['kind']=='record_created')['expected_count']=2
    else:
        edited['action']['input']['closure_reason']='Duplicate'
    assert client.put('/api/plans/'+p['plan_id'],json={'plan':edited,'expected_plan_hash':p['plan_hash']}).status_code == 422


def test_concurrent_reservation_is_single_and_worker_does_not_replay(setup):
    client,svc,fake,_=setup
    p=bind(client,create(client));assert approve(client,p).status_code==200
    def reserve():
        try:return svc.reserve(p['plan_id'],p['plan_hash'])
        except WorkflowError as e:return e.code
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(lambda _:reserve(),range(2)))
    assert results.count(409)==1
    rid=next(r for r in results if isinstance(r,str))
    svc.work(rid);svc.work(rid)
    assert fake.action_calls==1


def test_background_failure_keeps_reservation_and_hides_error(setup):
    client,svc,fake,_=setup
    p=bind(client,create(client));approve(client,p)
    def fail(*args):raise RuntimeError(sim.CLIENT_SECRET)
    svc.execute=fail
    response=client.post('/api/runs',json={'approved_plan_id':p['plan_id'],'expected_plan_hash':p['plan_hash']})
    rid=response.json()['run_id']
    state=client.get('/api/runs/'+rid).json()
    assert state['state']=='error' and sim.CLIENT_SECRET not in json.dumps(state)
    assert client.get('/api/runs/'+rid+'/report').status_code==409
    assert client.post('/api/runs',json={'approved_plan_id':p['plan_id'],'expected_plan_hash':p['plan_hash']}).status_code==409


def test_plan_without_approval_cannot_run(setup):
    client,*_=setup;p=bind(client,create(client))
    assert client.post('/api/runs',json={'approved_plan_id':p['plan_id'],'expected_plan_hash':p['plan_hash']}).status_code==409


@pytest.mark.parametrize('url,body',[
    ('/api/plans',{'rule_text_pt':'','closure_reason':sim.REASON}),
    ('/api/plans',{'rule_text_pt':'x','closure_reason':'invented'}),
    ('/api/plans/p/approve',{'approved_by':'operator','approved_plan_hash':'abc'}),
    ('/api/runs',{}),
    ('/api/plans/p/case',{'case_id':'bad','expected_plan_hash':HASH}),
])
def test_invalid_bodies(setup,url,body):
    client,*_=setup
    assert client.post(url,json=body).status_code==422


def test_registered_operator_name_is_set_by_the_server(setup, tmp_path):
    client, svc, fake, calls = setup
    from web.app import main as m
    from web.app.operators import OperatorRegistry
    reg = OperatorRegistry(tmp_path / 'ops')
    m.app.dependency_overrides[m.operator_registry] = lambda: reg
    try:
        _, key = reg.create('Maria Silva', 'operator')
        p = bind(client, create(client))
        r = client.post('/api/plans/'+p['plan_id']+'/approve', headers={'Authorization': 'Bearer ' + key},
                        json={'approved_by': 'Someone Else', 'approved_plan_hash': p['plan_hash']})
        assert r.status_code == 200
        assert svc.get(p['plan_id'])['approval']['approved_by'] == 'Maria Silva'
    finally:
        m.app.dependency_overrides.pop(m.operator_registry, None)
