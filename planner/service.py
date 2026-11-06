"""create_plan / bind_case: ponto de entrada interno do planner (nao e contrato publico)."""
from __future__ import annotations

import copy
import json
import re
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from connector.transport import Transport
from contracts.plan_hash import with_hash
from contracts.semantics import validate_plan_semantics

from . import coverage as cov
from . import policy
from .client import Budget, ChatResult, VultrChatClient
from .config import PlannerConfig
from connector.ids import InvalidSalesforceId, to_sfid18
from .context import KNOWN_REASONS, ActionContext, check_sufficiency, parse_action, parse_metadata
from .errors import PlannerError
from .prompt import correction_prompt, system_prompt, user_prompt

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"
MAX_RULE_CHARS = 4000
_FENCE = re.compile(r"^```(?:json)?\s*\n(.*)\n```$", re.DOTALL)


@lru_cache(maxsize=1)
def _validators() -> dict[str, Draft202012Validator]:
    schemas = {p.name.replace(".schema.json", ""): json.loads(p.read_text(encoding="utf-8"))
               for p in CONTRACTS.glob("*.schema.json")}
    reg = Registry().with_resources([(s["$id"], Resource.from_contents(s)) for s in schemas.values()])
    return {n: Draft202012Validator(s, registry=reg) for n, s in schemas.items()}


@dataclass
class PlanResult:
    plan: dict[str, Any]                 # rascunho: approval nulo, hash calculado aqui
    metadata_source: str                 # "salesforce_describe" | "fixture"
    metadata_collected_at: str
    model: str
    served_model: str | None = None      # modelo informado na resposta, se houver
    usage: dict[str, int] = field(default_factory=dict)
    calls: int = 0
    warnings: list[str] = field(default_factory=list)


def _extract_json(content: str) -> dict[str, Any]:
    text = content.strip()
    m = _FENCE.match(text)
    if m:
        text = m.group(1).strip()
    try:
        data = json.loads(text)
    except ValueError:
        raise ValueError("the response is not valid JSON") from None
    if not isinstance(data, dict):
        raise ValueError("the JSON response is not an object")
    return data


def create_plan(rule: dict[str, Any], metadata_context: Any, action_context: Any, transport: Transport, *,
                config: PlannerConfig | None = None, sleep: Callable[[float], None] | None = None,
                id_factory: Callable[[], str] = lambda: f"plan-{uuid.uuid4().hex[:12]}") -> PlanResult:
    cfg = config or PlannerConfig.from_env()
    v = _validators()
    errs = [e.message[:120] for e in v["rule"].iter_errors(rule)]
    if errs:
        raise PlannerError("insufficient_context", ["invalid rule: " + e for e in errs[:3]])
    if len(rule["text_pt"]) > MAX_RULE_CHARS:
        raise PlannerError("insufficient_context", [f"text_pt above {MAX_RULE_CHARS} characters"])
    meta = parse_metadata(metadata_context)
    action = parse_action(action_context)
    mentioned = {r for r in KNOWN_REASONS if r.lower() in rule["text_pt"].lower()}
    if mentioned - {action.closure_reason}:
        raise PlannerError("insufficient_context", [
            "the rule mentions a reason different from the requested one; fix one of them: "
            + "; ".join(sorted(mentioned | {action.closure_reason}))])
    check_sufficiency(meta, action)       # antes de gastar qualquer chamada

    import time
    clauses = cov.segment(rule["text_pt"])
    client = VultrChatClient(cfg, transport, sleep or time.sleep)
    budget = Budget(cfg.max_calls)
    messages = [{"role": "system", "content": system_prompt()},
                {"role": "user", "content": user_prompt(rule["text_pt"], meta, action, clauses)}]
    plan_id = id_factory()
    usage: dict[str, int] = {}
    served: str | None = None
    last: PlannerError | None = None
    while True:
        res: ChatResult = client.chat(messages, budget)   # PlannerError (auth/timeout/...) sobe sem nova tentativa
        served = res.model or served
        for k, n in res.usage.items():
            usage[k] = usage.get(k, 0) + n
        problems: list[str] = []
        category = "invalid_response"
        plan: dict[str, Any] = {}
        warnings: list[str] = []
        try:
            proposal = _extract_json(res.content)
        except ValueError as e:
            problems = [str(e)]
        else:
            plan, struct, warnings = policy.assemble(proposal, rule, action, plan_id=plan_id)
            if plan:
                items, cov_warnings = cov.finalize(clauses, proposal.get("coverage"), plan["checks"])
                warnings = warnings + cov_warnings
                plan = with_hash({**plan, "rule_coverage": items})
            schema_p, sem_p = policy.validate(plan, meta, action, v["test_plan"]) if plan else ([], [])
            problems = schema_p + struct + sem_p
            category = "schema" if schema_p else "semantics"
        if not problems:
            if meta.source == "fixture":
                warnings.append("metadata came from a fixture, not from the org; do not present it as real metadata")
            return PlanResult(plan=plan, metadata_source=meta.source, metadata_collected_at=meta.collected_at,
                              model=cfg.model, served_model=served, usage=usage, calls=budget.used, warnings=warnings)
        last = PlannerError(category, problems)
        if budget.left <= 0:
            raise last
        messages = messages + [{"role": "assistant", "content": res.content[:6000]},
                               {"role": "user", "content": correction_prompt(problems)}]


def bind_case(plan: dict[str, Any], case_id: str) -> dict[str, Any]:
    """Vincula o Case ao plano: nova versao, novo hash, SEM aprovacao (revisao humana obrigatoria)."""
    try:
        case_id = to_sfid18(case_id)      # sempre a forma de 18 caracteres, a mesma que a REST devolve
    except InvalidSalesforceId:
        raise PlannerError("insufficient_context", ["invalid case_id"]) from None
    out = copy.deepcopy(plan)
    out.setdefault("action", {}).setdefault("input", {})["case_id"] = case_id
    out["plan_version"] = int(out["plan_version"]) + 1
    out["approval"] = None
    out = with_hash(out)
    v = _validators()["test_plan"]
    problems = [e.message[:120] for e in v.iter_errors(out)] + validate_plan_semantics(out)
    if problems:
        raise PlannerError("schema", problems)
    return out


def ready_for_approval(plan: dict[str, Any]) -> list[str]:
    """Pendencias antes de oferecer o plano para aprovacao (lista vazia = pode revisar e aprovar)."""
    out = []
    inp = (plan.get("action") or {}).get("input") or {}
    if not inp.get("case_id"):
        out.append("falta action.input.case_id (provisione o Case sintetico e use bind_case)")
    if not inp.get("closure_reason"):
        out.append("falta action.input.closure_reason")
    schema = [e.message[:120] for e in _validators()["test_plan"].iter_errors(plan)]
    out += schema
    if not schema:
        out += validate_plan_semantics(plan)
    return out
