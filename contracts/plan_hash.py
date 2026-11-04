"""Hash canonico do plano de teste e validacao da aprovacao.

A aprovacao vale somente para o hash aprovado. Qualquer edicao do plano muda o
hash e, portanto, invalida a aprovacao anterior.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

EXCLUDED_KEYS = ("plan_hash", "approval")


def canonical_json(plan: dict[str, Any]) -> str:
    body = {k: v for k, v in plan.items() if k not in EXCLUDED_KEYS}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_plan_hash(plan: dict[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json(plan).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def with_hash(plan: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(plan)
    out["plan_hash"] = compute_plan_hash(out)
    return out


def approval_is_valid(plan: dict[str, Any]) -> bool:
    """True somente se o plano tem aprovacao e o hash aprovado e o hash atual."""
    approval = plan.get("approval")
    if not approval:
        return False
    current = compute_plan_hash(plan)
    return plan.get("plan_hash") == current and approval.get("approved_plan_hash") == current
