"""Esqueleto da API do Action Guard.

Somente /health esta implementado. As demais rotas definem o contrato de API
(ver docs/API.md) e respondem 501 ate que o motor, o planner e o conector
existam. Nao ha integracao real com Salesforce, Agentforce ou Vultr aqui.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Action Guard", version="0.1.0")


class CreatePlanRequest(BaseModel):
    rule_text_pt: str = Field(min_length=1, description="Regra funcional em portugues.")
    process: Literal["close_case"] = "close_case"


class UpdatePlanRequest(BaseModel):
    plan: dict[str, Any] = Field(description="Plano editado, conforme contracts/test_plan.schema.json.")


class ApprovePlanRequest(BaseModel):
    approved_by: str = Field(min_length=1)
    approved_plan_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ExecuteRunRequest(BaseModel):
    approved_plan_id: str = Field(min_length=1)


def _not_implemented() -> JSONResponse:
    return JSONResponse(status_code=501, content={"detail": "not implemented"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "action-guard"}


@app.post("/api/plans", status_code=201)
def create_plan(body: CreatePlanRequest):
    """create_plan(rule): gera um plano validado, revisavel e ainda nao aprovado."""
    return _not_implemented()


@app.get("/api/plans/{plan_id}")
def get_plan(plan_id: str):
    return _not_implemented()


@app.put("/api/plans/{plan_id}")
def update_plan(plan_id: str, body: UpdatePlanRequest):
    """Editar gera nova plan_version e novo plan_hash e invalida a aprovacao anterior."""
    return _not_implemented()


@app.post("/api/plans/{plan_id}/approve")
def approve_plan(plan_id: str, body: ApprovePlanRequest):
    """Aprova somente se approved_plan_hash for o hash atual; senao 409."""
    return _not_implemented()


@app.post("/api/runs", status_code=202)
def execute_plan(body: ExecuteRunRequest):
    """execute_plan(approved_plan_id): executa exatamente a versao aprovada; 409 se nao aprovada."""
    return _not_implemented()


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    return _not_implemented()


@app.get("/api/runs/{run_id}/report")
def get_report(run_id: str):
    return _not_implemented()
