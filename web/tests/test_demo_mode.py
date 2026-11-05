"""Demo policy: API, service and queued work cannot reach an action."""
import pytest
from tests.test_api import setup, create, bind, approve
from tests import sim
from web.app.mode import demo_mode
from web.app.service import WorkflowError
from orchestrator.run import RunBlocked


@pytest.mark.parametrize('value,expected', [('true', True), ('1', True), ('typo', True), ('', True), ('false', False), ('0', False)])
def test_mode_fail_closed(monkeypatch, value, expected):
    monkeypatch.setenv('ACTION_GUARD_DEMO_MODE', value)
    assert demo_mode() is expected


def test_demo_blocks_api_before_reservation(setup, monkeypatch):
    client, svc, fake, _ = setup
    monkeypatch.setenv('ACTION_GUARD_DEMO_MODE', 'true')
    plan = bind(client, create(client))
    assert approve(client, plan).status_code == 200
    assert client.get('/api/capabilities').json() == {'demo_mode': True, 'execution_enabled': False}
    response = client.post('/api/runs', json={'approved_plan_id': plan['plan_id'], 'expected_plan_hash': plan['plan_hash']})
    assert response.status_code == 403
    assert svc.history(plan['plan_id']) == []
    assert fake.log == [] and fake.action_calls == 0
    with pytest.raises(WorkflowError) as exc:
        svc.reserve(plan['plan_id'], plan['plan_hash'])
    assert exc.value.code == 403
    with pytest.raises(RunBlocked):
        svc._execute(plan, 'never-sent')
    assert fake.log == []


def test_queued_work_blocked_after_mode_change(setup, monkeypatch):
    client, svc, fake, _ = setup
    monkeypatch.setenv('ACTION_GUARD_DEMO_MODE', 'false')
    plan = bind(client, create(client))
    assert approve(client, plan).status_code == 200
    rid = svc.reserve(plan['plan_id'], plan['plan_hash'])
    def forbidden(*args):
        pytest.fail('executor reached in demo mode')
    svc.execute = forbidden
    monkeypatch.setenv('ACTION_GUARD_DEMO_MODE', 'true')
    svc.work(rid)
    assert svc.run(rid)['state'] == 'blocked'
    assert svc.run(rid)['sent'] is False
    assert fake.log == []
    # Release is durable; operator can reserve later when execution is enabled.
    monkeypatch.setenv('ACTION_GUARD_DEMO_MODE', 'false')
    assert svc.reserve(plan['plan_id'], plan['plan_hash']) != rid


def test_audit_still_available_in_demo(setup, monkeypatch):
    client, svc, fake, _ = setup
    monkeypatch.setenv('ACTION_GUARD_DEMO_MODE', 'true')
    plan = bind(client, create(client))
    assert approve(client, plan).status_code == 200
    response = client.post('/api/audits', json={'approved_plan_id': plan['plan_id'], 'case_ids': [sim.CASE]})
    assert response.status_code == 200, response.text
    assert fake.action_calls == 0
    assert {m for m, url in fake.log if 'oauth2' not in url} <= {'GET'}


def test_execution_enabled_still_works(setup, monkeypatch):
    client, svc, fake, _ = setup
    monkeypatch.setenv('ACTION_GUARD_DEMO_MODE', 'false')
    plan = bind(client, create(client))
    assert approve(client, plan).status_code == 200
    response = client.post('/api/runs', json={'approved_plan_id': plan['plan_id'], 'expected_plan_hash': plan['plan_hash']})
    assert response.status_code == 202
    assert svc.run(response.json()['run_id'])['state'] == 'completed'
    assert fake.action_calls == 1
