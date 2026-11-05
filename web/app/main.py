"""Single-operator API and UI. Live services only; credentials remain server-side."""
import hmac
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from connector.config import ConfigError
from planner.errors import PlannerError
from .service import Workflow, WorkflowError

app = FastAPI(title='Action Guard', version='0.2.0')
STATIC = Path(__file__).resolve().parents[1] / 'static'
app.mount('/static', StaticFiles(directory=STATIC), name='static')


@lru_cache
def workflow():
    return Workflow()


def authorize(authorization: str = Header(default='')):
    token = os.environ.get('ACTION_GUARD_API_TOKEN', '')
    if not token:
        raise HTTPException(503, 'Configure ACTION_GUARD_API_TOKEN no servidor.')
    if not hmac.compare_digest(authorization, 'Bearer ' + token):
        raise HTTPException(401, 'Token de acesso invalido.')


def invoke(fn, *args):
    try:
        return fn(*args)
    except WorkflowError as e:
        raise HTTPException(e.code, e.message)
    except PlannerError as e:
        raise HTTPException(502, e.to_public())
    except ConfigError:
        raise HTTPException(503, 'Configuracao Salesforce incompleta no servidor.')
    except (OSError, ValueError, TypeError, KeyError):
        raise HTTPException(503, 'Configuracao ou dados invalidos no servidor.')


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


class ExecuteRunRequest(HashRequest):
    approved_plan_id: str = Field(min_length=1)


@app.get('/health')
def health():
    return {'status': 'ok', 'service': 'action-guard'}


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
def approve(plan_id: str, body: ApprovePlanRequest, svc=Depends(workflow)):
    return invoke(svc.approve, plan_id, body.approved_plan_hash, body.approved_by)


@app.post('/api/runs', status_code=202, dependencies=[Depends(authorize)])
def execute(body: ExecuteRunRequest, background: BackgroundTasks, svc=Depends(workflow)):
    run_id = invoke(svc.reserve, body.approved_plan_id, body.expected_plan_hash)
    background.add_task(svc.work, run_id)
    return {'run_id': run_id}


@app.get('/api/runs/{run_id}', dependencies=[Depends(authorize)])
def get_run(run_id: str, svc=Depends(workflow)):
    return invoke(svc.run, run_id)


@app.get('/api/runs/{run_id}/report', dependencies=[Depends(authorize)])
def get_report(run_id: str, svc=Depends(workflow)):
    result = invoke(svc.run, run_id)
    if result['state'] != 'completed':
        raise HTTPException(409, 'Relatorio ainda indisponivel; confira o estado da execucao.')
    return result['report']
