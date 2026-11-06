"""Acceptance policy view: which conditions the plan checks, how severe a miss is, and what is NOT observed.

Severity is a plain rule table, not a score. There is deliberately no single "trust percentage": a critical
condition that was not observed must stay visible next to the checks that passed.
"""
from __future__ import annotations

from typing import Any

CRITICAL, OPERATIONAL = "critical", "operational"


def severity(check: dict[str, Any]) -> str:
    kind = check["kind"]
    if kind in ("field_equals", "field_not_empty", "field_unchanged"):
        return CRITICAL            # status, mandatory reason, owner: a miss changes the business record
    return OPERATIONAL             # linked records and side effects: a miss is repaired in operations


def policy_view(plan: dict[str, Any], auditable: list[dict[str, Any]], skipped: list[dict[str, str]]) -> dict[str, Any]:
    ok = {c["check_id"] for c in auditable}
    why = {s["check_id"]: s["reason"] for s in skipped}
    conditions = [{"check_id": c["check_id"], "description": c.get("description", c["check_id"]), "severity": severity(c),
                   "observed": c["check_id"] in ok, "why_not_observed": why.get(c["check_id"])} for c in plan["checks"]]
    crit = [c for c in conditions if c["severity"] == CRITICAL]
    return {"policy_version": f"{plan['plan_id']}@v{plan['plan_version']}", "conditions": conditions,
            "critical_total": len(crit), "critical_observed": sum(c["observed"] for c in crit),
            "all_total": len(conditions), "all_observed": sum(c["observed"] for c in conditions)}


def finding_severity(failed_check_ids: list[str], policy: dict[str, Any]) -> str:
    sev = {c["check_id"]: c["severity"] for c in policy["conditions"]}
    return CRITICAL if any(sev.get(i) == CRITICAL for i in failed_check_ids) else OPERATIONAL
