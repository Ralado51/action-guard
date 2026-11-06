"""Execucao da auditoria: plano aprovado + selecao de registros -> audit_report."""
from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable

from connector.ids import key15, to_sfid18
from connector.rest import QueryError, SalesforceRest
from contracts.plan_hash import approval_is_valid
from planner import coverage as cov

from . import collect
from .policy import policy_view
from .present import check_view
from .evaluate import CORRECT, FAILED, INCONCLUSIVE, INCORRECT, case_status, classify_checks, evaluate_case, needed_fields

MAX_LISTED = 200


class AuditBlocked(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_audit(plan: dict[str, Any], rest: SalesforceRest, *, case_ids: list[str] | None = None,
              since: str | None = None, modified_by: str | None = None, limit: int = 200,
              audit_id: str | None = None, now: Callable[[], str] = _now,
              agent_runs: dict[str, dict[str, Any]] | None = None, list_all: bool = False) -> dict[str, Any]:
    if not approval_is_valid(plan):
        raise AuditBlocked("The plan must be approved (current hash) to be used in an audit.")
    if bool(case_ids) == bool(since):
        raise AuditBlocked("Informe exatamente um entre case_ids e since.")
    auditable, skipped = classify_checks(plan)
    if not auditable:
        raise AuditBlocked("No check in the plan is auditable from the final state alone.")
    primary = next(c["object"] for c in auditable if c["kind"] != "record_created") if any(
        c["kind"] != "record_created" for c in auditable) else "Case"
    fields = needed_fields(auditable)
    errors: list[str] = []

    if case_ids:
        ordered = list(dict.fromkeys(to_sfid18(i) for i in case_ids))
        if len(ordered) > collect.MAX_CASES:
            raise AuditBlocked(f"At most {collect.MAX_CASES} records per audit.")
        try:
            found = collect.fetch_cases_by_ids(rest, primary, fields.get(primary, []), ordered)
        except QueryError as e:
            found, errors = {}, [f"Reading the main records failed: {e}"]
        rows = [(i, found.get(key15(i))) for i in ordered]
        mode = "case_ids"
    else:
        try:
            listed = collect.fetch_cases_window(rest, primary, fields.get(primary, []), since, limit, modified_by)
        except QueryError as e:
            listed, errors = [], [f"Reading the main records failed: {e}"]
        rows = [(r["Id"], r) for r in listed]
        mode = "closed_window"

    linked: dict[str, list[dict[str, Any]]] = {}
    linked_error: set[str] = set()
    ids_present = [cid for cid, row in rows if row is not None]
    for c in auditable:
        if c["kind"] == "record_created" and c["object"] not in linked and c["object"] not in linked_error:
            try:
                linked[c["object"]] = collect.fetch_linked(rest, c["object"], c["link_field"], fields[c["object"]], ids_present) if ids_present else []
            except QueryError as e:
                linked_error.add(c["object"])
                errors.append(f"Reading {c['object']} failed: {e}")

    per_case, by_check = [], {c["check_id"]: Counter() for c in auditable}
    for cid, row in rows:
        results = evaluate_case(auditable, primary, cid, row, linked, linked_error)
        for r in results:
            by_check[r["check_id"]][r["status"]] += 1
        per_case.append({"case_id": cid, "status": case_status(results), "results": results, "row": row})

    totals = Counter(c["status"] for c in per_case)
    evaluated = len(per_case)
    desc = {c["check_id"]: c.get("description", c["check_id"]) for c in plan["checks"]}
    by_id = {c["check_id"]: c for c in auditable}
    listed_cases = [{"case_id": c["case_id"], "status": c["status"],
                     "failed_checks": [r["check_id"] for r in c["results"] if r["status"] == FAILED],
                     "inconclusive_checks": [r["check_id"] for r in c["results"] if r["status"] == INCONCLUSIVE],
                     "evidence": {r["check_id"]: r["evidence"] for r in c["results"] if r["status"] == FAILED and r["evidence"]},
                     "checks": [check_view(by_id[r["check_id"]], r, c["row"]) for r in c["results"]]}
                    for c in per_case if list_all or c["status"] != CORRECT]
    runs15 = {key15(k): v for k, v in (agent_runs or {}).items()}
    for c in listed_cases:
        run = runs15.get(key15(c["case_id"]))
        if run:
            c["agent"] = {"source": str(run.get("source", ""))[:40], "outcome": str(run.get("outcome", ""))[:40], "final_message": run.get("final_message"),
                         "steps": [{"at": str(x.get("at", "")), "tool": str(x.get("tool", "")), "result": x.get("result")} for x in (run.get("steps") or [])][:20]}
    coverage = plan.get("rule_coverage")
    limitations = [
        "Read-only audit of the FINAL STATE: without the previous state, it does not verify that the owner was preserved or that no unexpected changes occurred.",
        "Rate = records with no failure among the auditable checks; inconclusive records do NOT count as correct.",
        ("Window selection audits only records that are already closed: a Case the agent claimed to close but did not will not appear here. Use the list of Cases reported by the agent to cover that case."
         if mode == "closed_window" else
         "List selection: only the given records were audited; nothing is claimed about the others."),
        "A matching Task counts even if it existed before the agent's action (the audit does not know when it was created).",
    ]
    if linked_error or errors:
        limitations.append("A read failure occurred: the affected records are inconclusive.")
    if skipped:
        limitations.append("Plan checks NOT auditable here: " + ", ".join(s["check_id"] for s in skipped) + ".")
    report: dict[str, Any] = {
        "schema_version": "1.0", "audit_id": audit_id or "audit-" + uuid.uuid4().hex, "generated_at": now(),
        "plan_id": plan["plan_id"], "plan_version": plan["plan_version"], "plan_hash": plan["plan_hash"],
        "selection": {"mode": mode, "limit": limit if mode == "closed_window" else None,
                      "since": since, "filtered_by_user": bool(modified_by)},
        "totals": {"evaluated": evaluated, "correct": totals[CORRECT], "incorrect": totals[INCORRECT],
                   "inconclusive": totals[INCONCLUSIVE]},
        "outcome_rate": round(totals[CORRECT] / evaluated, 4) if evaluated else None,
        "by_check": [{"check_id": cid, "description": desc[cid], "passed": n["passed"], "failed": n["failed"],
                      "inconclusive": n["inconclusive"]} for cid, n in by_check.items()],
        "not_auditable": skipped,
        "cases": listed_cases[:MAX_LISTED], "cases_truncated": len(listed_cases) > MAX_LISTED, "all_cases_listed": list_all,
        "collection_errors": errors, "limitations": limitations,
        "policy": policy_view(plan, auditable, skipped),
    }
    if coverage:
        report["rule_coverage"] = coverage
        report["coverage_status"] = cov.coverage_status(coverage)
    else:
        report["coverage_status"] = "not_assessed"
    report["summary"] = {"text": deterministic_summary(report), "basis": "server"}
    return report


def deterministic_summary(r: dict[str, Any]) -> str:
    t = r["totals"]
    if not t["evaluated"]:
        return "No records evaluated."
    pct = f"{r['outcome_rate'] * 100:.1f}".rstrip("0").rstrip(".")
    parts = [f"{t['correct']} of {t['evaluated']} records ({pct}%) met every auditable check"]
    if t["incorrect"]:
        worst = max(r["by_check"], key=lambda c: c["failed"])
        parts.append(f"{t['incorrect']} failed (most frequent: {worst['description']} — {worst['failed']})")
    if t["inconclusive"]:
        parts.append(f"{t['inconclusive']} were inconclusive")
    if r["not_auditable"]:
        parts.append(f"{len(r['not_auditable'])} plan check(s) could not be audited")
    return "; ".join(parts) + "."
