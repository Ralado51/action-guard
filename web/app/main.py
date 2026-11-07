"""Single-operator API and UI. Live services only; credentials remain server-side."""
import hmac
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from connector.config import ConfigError
from planner.errors import PlannerError
from .service import Workflow, WorkflowError
from .mode import demo_mode
from audit.demo import build_demo
from .live import LiveDemo, LiveError
from .operators import OperatorError, OperatorRegistry

app = FastAPI(title='Action Guard', version='0.2.0')


@app.exception_handler(Exception)
async def unexpected(request, exc):
    # Sem detalhe ao cliente; o traceback fica no log do servidor.
    import logging
    logging.getLogger('action_guard').exception('unexpected error in %s', request.url.path)
    return JSONResponse(status_code=500, content={'detail': 'Internal server error.'})
STATIC = Path(__file__).resolve().parents[1] / 'static'
app.mount('/static', StaticFiles(directory=STATIC), name='static')


@lru_cache
def workflow():
    return Workflow()


@lru_cache
def operator_registry():
    return OperatorRegistry(os.environ.get('ACTION_GUARD_DATA_DIR', 'runs/web') + '/operators')


def authorize(authorization: str = Header(default=''), reg=Depends(operator_registry)):
    """Returns the caller: {'role': 'admin'} for the shared token, or the registered operator record for a personal key."""
    token = os.environ.get('ACTION_GUARD_API_TOKEN', '')
    if not token:
        raise HTTPException(503, 'Configure ACTION_GUARD_API_TOKEN no servidor.')
    if hmac.compare_digest(authorization.encode('utf-8', 'replace'), ('Bearer ' + token).encode('utf-8')):
        return {'role': 'admin', 'name': None}
    if authorization.startswith('Bearer '):
        op = reg.lookup(authorization[7:].strip())
        if op:
            return op
    raise HTTPException(401, 'Invalid access token.')


def require_admin(who=Depends(authorize)):
    if who.get('role') != 'admin':
        raise HTTPException(403, 'Only the administrator token can manage operators.')
    return who


def invoke(fn, *args):
    try:
        return fn(*args)
    except WorkflowError as e:
        raise HTTPException(e.code, e.message)
    except PlannerError as e:
        raise HTTPException(502, e.to_public())
    except ConfigError:
        raise HTTPException(503, 'Configuracao Salesforce incompleta no servidor.')
    # Outras excecoes (KeyError, TypeError, ...) sao bugs: NAO viram "503 configuracao". Sobem como 500 generico.


class Body(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class CreatePlanRequest(Body):
    rule_text_pt: str = Field(min_length=1, max_length=4000)
    process: Literal['close_case'] = 'close_case'
    closure_reason: Literal['Resolved - Customer confirmed', 'Resolved - Guidance provided', 'Duplicate', 'Cancelled']


class HashRequest(Body):
    expected_plan_hash: str = Field(pattern=r'^sha256:[0-9a-f]{64}$')


class UpdatePlanRequest(HashRequest):
    plan: dict[str, Any]


class BindCaseRequest(HashRequest):
    case_id: str = Field(pattern=r'^[A-Za-z0-9]{15}([A-Za-z0-9]{3})?$')


class ApprovePlanRequest(Body):
    approved_by: str = Field(min_length=1, max_length=80)
    approved_plan_hash: str = Field(pattern=r'^sha256:[0-9a-f]{64}$')
    acknowledged_clauses: list[str] = Field(default_factory=list, max_length=12)


class AuditRequest(Body):
    approved_plan_id: str = Field(min_length=1)
    case_ids: list[str] | None = Field(default=None, max_length=500)
    since: str | None = Field(default=None, pattern=r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
    modified_by: str | None = Field(default=None, pattern=r'^[A-Za-z0-9]{15}([A-Za-z0-9]{3})?$')
    limit: int = Field(default=200, ge=1, le=500)
    explain: bool = False


class ExecuteRunRequest(HashRequest):
    approved_plan_id: str = Field(min_length=1)


@lru_cache
def live_demo():
    return LiveDemo(os.environ.get('ACTION_GUARD_DATA_DIR', 'runs/web') + '/live')


class LiveCreate(Body):
    code: str = Field(min_length=1, max_length=200)
    scenario: str = Field(min_length=1, max_length=40)
    mode: Literal['agent', 'verifier_test']


def live_call(fn, *args):
    try:
        return fn(*args)
    except LiveError as e:
        raise HTTPException(e.code, e.message)


@app.get('/api/live/status')
def live_status(demo=Depends(live_demo)):
    return demo.status()


@app.get('/api/live/activity')
def live_activity(demo=Depends(live_demo)):
    return demo.activity()


@app.post('/api/live/sessions', status_code=201)
def live_create(body: LiveCreate, demo=Depends(live_demo)):
    return live_call(demo.create, body.code, body.scenario, body.mode)


@app.post('/api/live/sessions/{sid}/run', status_code=202)
def live_run(sid: str, background: BackgroundTasks, demo=Depends(live_demo)):
    if live_call(demo.begin_run, sid):
        background.add_task(demo.work, sid)
    return live_call(demo.view, sid)


@app.get('/api/live/sessions/{sid}')
def live_get(sid: str, demo=Depends(live_demo)):
    return live_call(demo.view, sid)


@app.post('/api/live/sessions/{sid}/check')
def live_check(sid: str, demo=Depends(live_demo)):
    return live_call(demo.check, sid)


@app.post('/api/live/sessions/{sid}/fix')
def live_fix(sid: str, demo=Depends(live_demo)):
    return live_call(demo.fix, sid)


@app.get('/health')
def health():
    return {'status': 'ok', 'service': 'action-guard'}


@app.get('/favicon.ico', include_in_schema=False)
def favicon():
    return FileResponse(STATIC / 'favicon-32.png', media_type='image/png')


@app.get('/')
def index():
    return FileResponse(STATIC / 'index.html')


@app.post('/api/plans', status_code=201, dependencies=[Depends(authorize)])
def create_plan(body: CreatePlanRequest, svc=Depends(workflow)):
    return invoke(svc.create, body.rule_text_pt, body.closure_reason)


@app.get('/api/plans/{plan_id}', dependencies=[Depends(authorize)])
def get_plan(plan_id: str, svc=Depends(workflow)):
    return invoke(svc.get, plan_id)


@app.get('/api/plans/{plan_id}/context', dependencies=[Depends(authorize)])
def get_context(plan_id: str, svc=Depends(workflow)):
    return invoke(svc.info, plan_id)


@app.get('/api/plans/{plan_id}/runs', dependencies=[Depends(authorize)])
def get_history(plan_id: str, svc=Depends(workflow)):
    return invoke(svc.history, plan_id)


@app.put('/api/plans/{plan_id}', dependencies=[Depends(authorize)])
def update_plan(plan_id: str, body: UpdatePlanRequest, svc=Depends(workflow)):
    return invoke(svc.edit, plan_id, body.expected_plan_hash, body.plan)


@app.post('/api/plans/{plan_id}/case', dependencies=[Depends(authorize)])
def bind(plan_id: str, body: BindCaseRequest, svc=Depends(workflow)):
    return invoke(svc.edit, plan_id, body.expected_plan_hash, None, body.case_id)


@app.post('/api/plans/{plan_id}/approve', dependencies=[Depends(authorize)])
def approve(plan_id: str, body: ApprovePlanRequest, svc=Depends(workflow), who=Depends(authorize)):
    # A registered operator's name comes from the server, not from the request body.
    actor = who['name'] if who.get('name') else body.approved_by
    return invoke(svc.approve, plan_id, body.approved_plan_hash, actor, body.acknowledged_clauses)


class OperatorCreate(Body):
    name: str = Field(min_length=2, max_length=60)
    role: Literal['operator', 'reviewer'] = 'operator'


def op_call(fn, *args):
    try:
        return fn(*args)
    except OperatorError as e:
        raise HTTPException(e.code, e.message)


@app.get('/api/operators')
def operators_list(reg=Depends(operator_registry)):
    # Public on purpose: names, roles and dates only. Never keys or hashes.
    return {'operators': reg.list_public(), 'max': 25}


@app.get('/api/operators/me')
def operators_me(who=Depends(authorize)):
    return {'role': who.get('role'), 'name': who.get('name'), 'id': who.get('id')}


@app.post('/api/operators', status_code=201, dependencies=[Depends(require_admin)])
def operators_create(body: OperatorCreate, reg=Depends(operator_registry)):
    op, key = op_call(reg.create, body.name, body.role)
    return {'operator': op, 'key': key, 'note': 'Shown once. Only its hash is stored.'}


@app.delete('/api/operators/{oid}', dependencies=[Depends(require_admin)])
def operators_revoke(oid: str, reg=Depends(operator_registry)):
    op_call(reg.revoke, oid)
    return {'revoked': oid}


def require_execution():
    if demo_mode():
        raise HTTPException(403, 'Demo mode: real execution is disabled. Generation, review and audit remain available.')


@app.get('/api/capabilities')
def capabilities():
    return {'demo_mode': demo_mode(), 'execution_enabled': not demo_mode()}


@app.get('/api/demo/audit')
def demo_audit():
    # Public on purpose: built in memory from invented data; no Salesforce, no token, no model call.
    return build_demo()


@app.get('/api/recorded-run')
def recorded_run():
    # A real audit report recorded earlier (Ids masked). Static file shipped with the image; no live access.
    path = Path(__file__).resolve().parents[1] / 'data' / 'recorded_run.json'
    if not path.is_file():
        raise HTTPException(404, 'No recorded run published.')
    import json
    return json.loads(path.read_text(encoding='utf-8'))


FLOW_PATH = Path(__file__).resolve().parents[1] / 'data' / 'recorded_flow.json'


@app.get('/api/recorded-flow')
def recorded_flow():
    path = FLOW_PATH
    if not path.is_file():
        raise HTTPException(404, 'No recorded acceptance flow published.')
    import json
    return json.loads(path.read_text(encoding='utf-8'))


@app.post('/api/runs', status_code=202, dependencies=[Depends(authorize), Depends(require_execution)])
def execute(body: ExecuteRunRequest, background: BackgroundTasks, svc=Depends(workflow)):
    run_id = invoke(svc.reserve, body.approved_plan_id, body.expected_plan_hash)
    background.add_task(svc.work, run_id)
    return {'run_id': run_id}


@app.post('/api/audits', dependencies=[Depends(authorize)])
def audit(body: AuditRequest, svc=Depends(workflow)):
    if bool(body.case_ids) == bool(body.since):
        raise HTTPException(422, 'Informe exatamente um entre case_ids e since.')
    ids = body.case_ids
    if ids is not None and any(not re.fullmatch(r'[A-Za-z0-9]{15}([A-Za-z0-9]{3})?', i) for i in ids):
        raise HTTPException(422, 'All Ids must have 15 or 18 alphanumeric characters.')
    return invoke(svc.audit, body.approved_plan_id, ids, body.since, body.modified_by, body.limit, body.explain)


@app.get('/api/runs/{run_id}', dependencies=[Depends(authorize)])
def get_run(run_id: str, svc=Depends(workflow)):
    return invoke(svc.run, run_id)


@app.get('/api/runs/{run_id}/report', dependencies=[Depends(authorize)])
def get_report(run_id: str, svc=Depends(workflow)):
    result = invoke(svc.run, run_id)
    if result['state'] != 'completed':
        raise HTTPException(409, 'Report not available yet; check the run status.')
    return result['report']
