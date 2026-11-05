"""Contextos fornecidos pelo backend: metadados autorizados e acao suportada.

O planner nao consulta o Salesforce. Se `source` for "fixture", o resultado do planner
carrega essa origem e nunca a apresenta como metadado real da org.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .errors import PlannerError

KNOWN_REASONS = ("Resolved - Customer confirmed", "Resolved - Guidance provided", "Duplicate", "Cancelled")
SOURCES = ("salesforce_describe", "fixture")
SFID = re.compile(r"^[A-Za-z0-9]{15,18}$")
IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")

# Campos que o MVP close_case precisa ler (invariantes). Os demais sao opcionais.
REQUIRED_MONITORED = {
    "Case": ["Status", "OwnerId", "Closure_Reason__c", "ClosedDate", "IsClosed"],
    "Task": ["Subject", "WhatId"],
}


@dataclass(frozen=True)
class FieldInfo:
    type: str
    readable: bool
    values: tuple[str, ...] = ()


@dataclass(frozen=True)
class MetadataContext:
    source: str
    collected_at: str
    objects: dict[str, dict[str, FieldInfo]] = field(default_factory=dict)  # somente objetos legiveis

    def field(self, obj: str, name: str) -> FieldInfo | None:
        return self.objects.get(obj, {}).get(name)


@dataclass(frozen=True)
class ActionContext:
    process: str
    closure_reason: str
    task_subject: str
    agent_name: str = "Action Guard"
    case_id: str | None = None


def _insufficient(*details: str) -> PlannerError:
    return PlannerError("insufficient_context", list(details))


def parse_metadata(raw: Any) -> MetadataContext:
    if not isinstance(raw, dict):
        raise _insufficient("metadata_context ausente ou nao e objeto")
    source, collected = raw.get("source"), raw.get("collected_at")
    if source not in SOURCES:
        raise _insufficient(f"metadata_context.source deve ser um de {list(SOURCES)}")
    if not isinstance(collected, str) or not collected:
        raise _insufficient("metadata_context.collected_at ausente")
    objs: dict[str, dict[str, FieldInfo]] = {}
    for oname, o in (raw.get("objects") or {}).items():
        if not isinstance(o, dict) or o.get("readable") is not True or not IDENT.match(str(oname)):
            continue
        fields: dict[str, FieldInfo] = {}
        for fname, f in (o.get("fields") or {}).items():
            if isinstance(f, dict) and IDENT.match(str(fname)) and isinstance(f.get("type"), str):
                vals = tuple(v for v in (f.get("values") or []) if isinstance(v, str))
                fields[fname] = FieldInfo(f["type"], f.get("readable") is True, vals)
        objs[oname] = fields
    return MetadataContext(source, collected, objs)


def parse_action(raw: Any) -> ActionContext:
    if not isinstance(raw, dict):
        raise _insufficient("action_context ausente ou nao e objeto")
    if raw.get("process") != "close_case":
        raise _insufficient("processo suportado neste MVP: close_case")
    reason = raw.get("closure_reason")
    if not isinstance(reason, str) or not reason.strip():
        raise _insufficient("closure_reason ausente; informe um dos valores: " + "; ".join(KNOWN_REASONS))
    if reason not in KNOWN_REASONS:
        raise _insufficient(f"closure_reason {reason[:60]!r} nao e um dos valores conhecidos: " + "; ".join(KNOWN_REASONS))
    subject = raw.get("task_subject")
    if not isinstance(subject, str) or not subject.strip() or len(subject) > 255 or subject != subject.strip():
        raise _insufficient("task_subject ausente, com espacos nas pontas ou maior que 255 caracteres")
    case_id = raw.get("case_id")
    if case_id is not None and (not isinstance(case_id, str) or not SFID.match(case_id)):
        raise _insufficient("case_id invalido; ele vem do backend/operador, nunca do modelo")
    agent = raw.get("agent_name", "Action Guard")
    if not isinstance(agent, str) or not agent.strip() or len(agent) > 80:
        raise _insufficient("agent_name invalido")
    return ActionContext("close_case", reason, subject, agent, case_id)


def check_sufficiency(meta: MetadataContext, action: ActionContext) -> None:
    problems = []
    for obj, names in REQUIRED_MONITORED.items():
        if obj not in meta.objects:
            problems.append(f"objeto {obj} ausente ou nao legivel no contexto")
            continue
        for n in names:
            info = meta.field(obj, n)
            if info is None:
                problems.append(f"campo {obj}.{n} ausente do contexto")
            elif not info.readable:
                problems.append(f"campo {obj}.{n} nao e legivel")
    status = meta.field("Case", "Status")
    if status and "Closed" not in status.values:
        problems.append("Case.Status sem o valor Closed no contexto")
    reason = meta.field("Case", "Closure_Reason__c")
    if reason and action.closure_reason not in reason.values:
        problems.append(f"Closure_Reason__c nao oferece {action.closure_reason!r} no contexto")
    if problems:
        raise _insufficient(*problems)
