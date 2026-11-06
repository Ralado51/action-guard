"""Synthetic demonstration population, evaluated by the REAL audit engine.

Nothing here touches Salesforce or any network. Twenty made-up Cases are built in memory and passed
through `audit.evaluate` exactly like rows read from an org; the payload is always labeled synthetic.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from connector.ids import to_sfid18

from .evaluate import CORRECT, FAILED, INCONCLUSIVE, INCORRECT, case_status, classify_checks, evaluate_case

SUBJECT = "Action Guard - Case closure follow-up"
REASONS = ["Resolved - Customer confirmed", "Resolved - Guidance provided", "Duplicate", "Cancelled"]

DEMO_PLAN: dict[str, Any] = {
    "action": {"input": {"closure_reason": REASONS[0]}},
    "checks": [
        {"check_id": "chk_status_closed", "kind": "field_equals", "description": "The Case is closed.",
         "object": "Case", "field": "Status", "expected": "Closed"},
        {"check_id": "chk_reason_filled", "kind": "field_not_empty", "description": "The mandatory closure reason is recorded.",
         "object": "Case", "field": "Closure_Reason__c"},
        {"check_id": "chk_reason_matches", "kind": "field_equals", "description": "The closure reason is the one in the test plan.",
         "object": "Case", "field": "Closure_Reason__c", "expected": REASONS[0]},
        {"check_id": "chk_owner_unchanged", "kind": "field_unchanged", "description": "The Case owner did not change.",
         "object": "Case", "field": "OwnerId"},
        {"check_id": "chk_followup_task", "kind": "record_created", "description": "Exactly one follow-up Task is linked to the Case.",
         "object": "Task", "link_field": "WhatId", "expected_count": 1, "match": {"Subject": SUBJECT}},
        {"check_id": "chk_no_unexpected", "kind": "no_unexpected_change", "description": "No other monitored field changed.",
         "object": "*", "allowed_changes": []},
    ],
}

SUBJECTS = [
    "Cannot reset password", "Invoice shows wrong amount", "Delivery date question", "Account locked after update",
    "Refund status request", "Change billing address", "App crashes on login", "Missing order confirmation",
    "Upgrade plan question", "Duplicate charge", "Cancel subscription", "Export my data",
    "Two-factor code not arriving", "Late shipment", "Wrong item received", "Update company name",
    "Promo code rejected", "Cannot download receipt", "Product manual request", "Warranty claim",
]

# (reason or None, tasks, readable)  -- the first 13 are right; the rest are the failure modes worth seeing.
_PLAN = ([("ok", 1)] * 13 + [("empty", 1)] * 3 + [("ok", 0)] * 2 + [("ok", 2)] + [("missing", 0)])


def _expected_found(check: dict[str, Any], result: dict[str, Any], row: dict[str, Any] | None) -> tuple[str, str]:
    kind, ev = check["kind"], result["evidence"]
    if result["status"] == INCONCLUSIVE:
        return _expect(check), "Could not be read"
    if kind == "record_created":
        n = ev.get("matching", 0)
        return _expect(check), f"{n} follow-up Task" + ("" if n == 1 else "s")
    if kind == "field_not_empty":
        v = (row or {}).get(check["field"])
        return _expect(check), "Empty" if v in (None, "") else str(v)
    observed = ev.get("observed", check["expected"]) if result["status"] == FAILED else check["expected"]
    return _expect(check), "Empty" if observed in (None, "") else str(observed)


def _expect(check: dict[str, Any]) -> str:
    if check["kind"] == "record_created":
        n = check.get("expected_count", 1)
        return f"{n} follow-up Task" + ("" if n == 1 else "s")
    if check["kind"] == "field_not_empty":
        return "A value is recorded"
    return str(check["expected"])


def _finding(status: str, results: list[dict[str, Any]]) -> str:
    failed = {r["check_id"]: r for r in results if r["status"] == FAILED}
    if status == CORRECT:
        return "Every auditable check passed."
    if status == INCONCLUSIVE:
        return "The Case could not be read, so the outcome cannot be confirmed."
    parts = []
    if "chk_reason_filled" in failed:
        parts.append("the mandatory closure reason was not recorded")
    t = failed.get("chk_followup_task")
    if t:
        n = t["evidence"].get("matching", 0)
        parts.append("no follow-up Task was created" if n == 0 else f"{n} follow-up Tasks were created instead of one")
    if "chk_status_closed" in failed:
        parts.append("the Case is not closed")
    return "The agent reported success, but " + " and ".join(parts) + "."


def build_demo() -> dict[str, Any]:
    auditable, skipped = classify_checks(DEMO_PLAN)
    by_check = {c["check_id"]: Counter() for c in auditable}
    cases, tasks_by_case = [], {}
    for i, (kind, n_tasks) in enumerate(_PLAN, start=1):
        cid = to_sfid18(f"500SYN{i:09d}")
        reason = None if kind == "empty" else REASONS[(i - 1) % len(REASONS)]
        row = None if kind == "missing" else {"Id": cid, "Status": "Closed", "Closure_Reason__c": reason}
        linked = {"Task": [{"WhatId": cid, "Subject": SUBJECT} for _ in range(n_tasks)]}
        results = evaluate_case(auditable, "Case", cid, row, linked, set())
        for r in results:
            by_check[r["check_id"]][r["status"]] += 1
        status = case_status(results)
        claim = "Case closed" + (f" with reason “{reason}”" if reason else "") + ". Follow-up task created."
        views = []
        by_id = {c["check_id"]: c for c in auditable}
        for r in results:
            exp, found = _expected_found(by_id[r["check_id"]], r, row)
            views.append({"check_id": r["check_id"], "description": by_id[r["check_id"]]["description"],
                          "status": r["status"], "expected": exp, "found": found})
        cases.append({"case_id": cid, "subject": SUBJECTS[i - 1], "status": status, "finding": _finding(status, results),
                      "agent_claim": claim, "checks": views})
        tasks_by_case[cid] = n_tasks
    totals = Counter(c["status"] for c in cases)
    n = len(cases)
    return {
        "synthetic": True,
        "label": "Synthetic demonstration: 20 invented Cases, no Salesforce connection, no real customer data.",
        "engine": "audit.evaluate, the same deterministic engine used on real Cases.",
        "agent_reported": n,
        "totals": {"evaluated": n, "correct": totals[CORRECT], "incorrect": totals[INCORRECT], "inconclusive": totals[INCONCLUSIVE]},
        "outcome_rate": round(totals[CORRECT] / n, 4),
        "by_check": [{"check_id": c["check_id"], "description": c["description"], "passed": by_check[c["check_id"]]["passed"],
                      "failed": by_check[c["check_id"]]["failed"], "inconclusive": by_check[c["check_id"]]["inconclusive"]}
                     for c in auditable],
        "not_auditable": skipped,
        "cases": cases,
        "limitations": [
            "The population is invented to show what the product reports; the rate says nothing about any real agent.",
            "Read-only audit of the FINAL STATE: checks that need the previous state are listed as not verified.",
            "Inconclusive Cases never count as correct.",
        ],
    }
