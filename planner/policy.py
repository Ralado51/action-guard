"""Montagem e validacao do plano. O modelo propoe; o servidor decide.

O modelo so contribui com: monitored, async_window e checks (kind/descricao/campos).
Tudo o mais (ids, rule_id, versao, acao, motivo, Subject, precondicoes, aprovacao, hash)
e atribuido aqui. Invariantes do MVP nao podem ser enfraquecidos: a proposta que os
omitir, contradisser ou ampliar e REJEITADA (nunca consertada em silencio).
"""
from __future__ import annotations

import copy
import re
from typing import Any, Callable

from jsonschema import Draft202012Validator

from contracts.plan_hash import with_hash
from contracts.semantics import validate_plan_semantics

from .context import REQUIRED_MONITORED, ActionContext, MetadataContext

MAX_CHECKS = 10
MAX_FIELDS_PER_OBJECT = 25
MAX_DESCRIPTION = 300
MAX_WAIT_SECONDS = 120
MAX_POLL_ATTEMPTS = 60
ALLOWED_OBJECTS = ("Case", "Task")
PROTECTED_CASE_FIELDS = ("Status", "Closure_Reason__c", "OwnerId", "ClosedDate", "IsClosed")
CANONICAL_ALLOWED_CHANGES = ["Case.Status", "Case.Closure_Reason__c", "Case.ClosedDate", "Case.IsClosed"]
ALLOWED_PROPOSAL_KEYS = ("monitored", "async_window", "checks", "coverage")
CHECK_KEYS = {"kind", "description", "object", "field", "expected", "link_field", "expected_count", "match",
              "allowed_changes", "check_id"}
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def canonical_specs(action: ActionContext) -> dict[str, dict[str, Any]]:
    return {
        "chk_status_closed": {"kind": "field_equals", "object": "Case", "field": "Status", "expected": "Closed"},
        "chk_reason_filled": {"kind": "field_not_empty", "object": "Case", "field": "Closure_Reason__c"},
        "chk_reason_matches": {"kind": "field_equals", "object": "Case", "field": "Closure_Reason__c",
                               "expected": action.closure_reason},
        "chk_owner_unchanged": {"kind": "field_unchanged", "object": "Case", "field": "OwnerId"},
        "chk_followup_task": {"kind": "record_created", "object": "Task", "link_field": "WhatId",
                              "expected_count": 1, "match": {"Subject": action.task_subject}},
        "chk_no_unexpected": {"kind": "no_unexpected_change", "object": "*",
                              "allowed_changes": list(CANONICAL_ALLOWED_CHANGES)},
    }


def preconditions() -> list[dict[str, Any]]:
    return [
        {"id": "pre_open", "description": "O Case sintetico esta aberto antes da acao.",
         "object": "Case", "field": "IsClosed", "expected": False},
        {"id": "pre_reason_empty", "description": "O motivo de encerramento esta vazio antes da acao.",
         "object": "Case", "field": "Closure_Reason__c", "expected": None},
    ]


def _clean(text: Any) -> str:
    return _CTRL.sub(" ", text).strip()[:MAX_DESCRIPTION] if isinstance(text, str) else ""


def _match_spec(check: dict[str, Any], spec: dict[str, Any]) -> bool:
    c = dict(check)
    if c.get("kind") == "record_created":
        c.setdefault("expected_count", 1)
    if "allowed_changes" in spec and isinstance(c.get("allowed_changes"), list):
        try:
            c["allowed_changes"] = sorted(c["allowed_changes"])     # a ordem nao importa
        except TypeError:
            return False
        spec = {**spec, "allowed_changes": sorted(spec["allowed_changes"])}
    return all(c.get(k) == v and type(c.get(k)) is type(v) for k, v in spec.items()) and \
        set(c) - {"kind", "description", "check_id"} <= set(spec)


def assemble(proposal: dict[str, Any], rule: dict[str, Any], action: ActionContext, *, plan_id: str
             ) -> tuple[dict[str, Any], list[str], list[str]]:
    """(plano, problemas estruturais, avisos). Problemas vazios nao significam plano valido: ver validate."""
    problems: list[str] = []
    warnings: list[str] = []
    dropped = sorted(k for k in proposal if k not in ALLOWED_PROPOSAL_KEYS)
    if dropped:
        warnings.append("campos do modelo ignorados: " + ", ".join(k[:30] for k in dropped))

    specs = canonical_specs(action)
    raw_checks = proposal.get("checks")
    if not isinstance(raw_checks, list) or not all(isinstance(c, dict) for c in raw_checks):
        return {}, ["checks deve ser uma lista de objetos"], warnings
    if len(raw_checks) > MAX_CHECKS:
        problems.append(f"checks excede o limite de {MAX_CHECKS}")
        raw_checks = raw_checks[:MAX_CHECKS]

    by_id: dict[str, dict[str, Any]] = {}
    extras: list[dict[str, Any]] = []
    for c in raw_checks:
        unknown = set(c) - CHECK_KEYS
        if unknown:
            problems.append("check com chaves desconhecidas: " + ", ".join(sorted(k[:30] for k in unknown)))
            continue
        clean = {k: v for k, v in c.items() if k not in ("check_id", "description")}
        clean["description"] = _clean(c.get("description")) or "Verificacao proposta pelo planner."
        cid = next((i for i, s in specs.items() if _match_spec(c, s)), None)
        if cid:
            if cid in by_id:
                problems.append(f"invariante duplicado: {cid}")
            else:
                by_id[cid] = {"check_id": cid, **{k: v for k, v in specs[cid].items()}, "description": clean["description"]}
            continue
        touches_protected = (c.get("object") == "Case" and c.get("field") in PROTECTED_CASE_FIELDS) \
            or c.get("kind") in ("no_unexpected_change", "record_created")
        if touches_protected:
            problems.append(f"check enfraquece ou contradiz um invariante do MVP: {str(c.get('kind'))[:30]} "
                            f"{str(c.get('object'))[:30]}.{str(c.get('field') or c.get('link_field'))[:40]}")
            continue
        extras.append(clean)
    for cid in specs:
        if cid not in by_id:
            problems.append(f"invariante ausente: {cid}")
    checks = [by_id[i] for i in specs if i in by_id]
    for n, e in enumerate(extras, 1):
        checks.append({"check_id": f"chk_extra_{n:02d}", **e})

    mon_raw = proposal.get("monitored")
    objects: list[dict[str, Any]] = []
    if not isinstance(mon_raw, dict) or not isinstance(mon_raw.get("objects"), list):
        problems.append("monitored.objects ausente")
    else:
        seen: dict[str, list[str]] = {}
        for m in mon_raw["objects"]:
            if not isinstance(m, dict) or not isinstance(m.get("object"), str) or not isinstance(m.get("fields"), list) \
                    or not all(isinstance(f, str) for f in m["fields"]):
                problems.append("monitored.objects com item malformado")
                continue
            if m["object"] not in ALLOWED_OBJECTS:
                problems.append(f"objeto fora do escopo do MVP: {m['object'][:40]!r}")
                continue
            if m["object"] in seen:
                problems.append(f"objeto monitorado duplicado: {m['object']}")
                continue
            if len(m["fields"]) > MAX_FIELDS_PER_OBJECT:
                problems.append(f"{m['object']}: mais de {MAX_FIELDS_PER_OBJECT} campos")
            seen[m["object"]] = list(dict.fromkeys(m["fields"]))[:MAX_FIELDS_PER_OBJECT]
        for obj, req in REQUIRED_MONITORED.items():
            have = seen.get(obj, [])
            missing = [f for f in req if f not in have]
            if missing:
                problems.append(f"monitored.{obj} sem campos obrigatorios: {', '.join(missing)}")
            ordered = [f for f in req if f in have] + [f for f in have if f not in req]
            objects.append({"object": obj, "fields": ordered})
    window = proposal.get("async_window")
    if not isinstance(window, dict):
        problems.append("async_window ausente")
        window = {}

    plan = {
        "schema_version": "1.0", "plan_id": plan_id, "plan_version": 1, "plan_hash": "sha256:" + "0" * 64,
        "rule_id": rule["rule_id"], "approval": None, "preconditions": preconditions(),
        "action": {"executed_via": "agentforce_agent_api", "identifier": action.agent_name,
                   "input": {"closure_reason": action.closure_reason}},
        "monitored": {"objects": objects}, "async_window": window, "checks": checks,
    }
    if action.case_id:
        plan["action"]["input"]["case_id"] = action.case_id
    return with_hash(plan), problems, warnings


def validate(plan: dict[str, Any], meta: MetadataContext, action: ActionContext,
             schema_validator: Draft202012Validator) -> tuple[list[str], list[str]]:
    """(problemas de schema, problemas de semantica/metadados/politica)."""
    schema = [f"{'/'.join(map(str, e.absolute_path)) or '<raiz>'}: {e.message[:120]}"
              for e in schema_validator.iter_errors(plan)]
    if schema:
        return schema, []
    sem = list(validate_plan_semantics(plan))
    w = plan["async_window"]
    if w["max_wait_seconds"] > MAX_WAIT_SECONDS:
        sem.append(f"async_window.max_wait_seconds acima de {MAX_WAIT_SECONDS}")
    elif w["max_wait_seconds"] // w["poll_interval_seconds"] + 1 > MAX_POLL_ATTEMPTS:
        sem.append(f"async_window gera mais de {MAX_POLL_ATTEMPTS} consultas")
    for m in plan["monitored"]["objects"]:
        if m["object"] not in meta.objects:
            sem.append(f"objeto {m['object']} fora do contexto de metadados")
            continue
        for f in m["fields"]:
            info = meta.field(m["object"], f)
            if info is None:
                sem.append(f"campo {m['object']}.{f} inexistente no contexto de metadados")
            elif not info.readable:
                sem.append(f"campo {m['object']}.{f} nao legivel")
    for c in plan["checks"]:
        if c["kind"] in ("field_equals", "field_not_empty", "field_unchanged") and c["object"] != "Case":
            sem.append(f"{c['check_id']}: verificacoes de campo devem mirar o Case")
        if c["kind"] == "field_equals":
            info = meta.field(c["object"], c["field"])
            if info and info.type == "picklist" and c["expected"] not in info.values:
                sem.append(f"{c['check_id']}: valor {str(c['expected'])[:40]!r} fora da picklist {c['field']}")
    return [], sem
