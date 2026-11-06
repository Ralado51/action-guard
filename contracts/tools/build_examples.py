"""Generates contracts/examples/ from synthetic data.

Usage: python contracts/tools/build_examples.py

All ids, names and values are synthetic. The closure reason field
(Closure_Reason__c) is illustrative: replace it with the org's real API name after
confirming it (see docs/DECISIONS.md).
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from contracts.plan_hash import compute_plan_hash, with_hash  # noqa: E402

EX = ROOT / "contracts" / "examples"
V = "1.0"

CASE_ID = "500SYN000000001AAA"
OWNER_1 = "005SYN000000001AAA"
OWNER_2 = "005SYN000000002AAA"
OLD_TASK = "00TSYN000000000AAA"
NEW_TASK = "00TSYN000000001AAA"
DUP_TASK = "00TSYN000000002AAA"
TASK_SUBJECT = "Action Guard - Case closure follow-up"
CLOSURE_REASON = "Resolved - Customer confirmed"
REASON = "Closure_Reason__c"

T_BEFORE = "2026-11-03T18:00:00Z"
T_START = "2026-11-03T18:00:05Z"
T_END = "2026-11-03T18:00:20Z"
T_AFTER = "2026-11-03T18:00:40Z"
T_REPORT = "2026-11-03T18:00:45Z"

CASE_FIELDS = ["Status", "OwnerId", REASON, "ClosedDate", "IsClosed", "Priority", "Subject"]
TASK_FIELDS = ["Subject", "WhatId", "OwnerId", "Status", "CreatedDate"]

rule = {
    "schema_version": V,
    "rule_id": "rule-close-case-001",
    "process": "close_case",
    "text_pt": (
        "When closing a Case: the closure reason must be filled, "
        "the owner must stay the same and a follow-up Task "
        "must be created and linked to the Case."
    ),
    "created_at": "2026-11-03T17:00:00Z",
}

plan_draft = {
    "schema_version": V,
    "plan_id": "plan-close-case-001",
    "plan_version": 1,
    "plan_hash": "sha256:" + "0" * 64,
    "rule_id": rule["rule_id"],
    "approval": None,
    "preconditions": [
        {"id": "pre_open", "description": "The synthetic Case is open before the action.",
         "object": "Case", "field": "IsClosed", "expected": False},
        {"id": "pre_reason_empty", "description": "The closure reason is empty before the action.",
         "object": "Case", "field": REASON, "expected": None},
    ],
    "action": {
        "executed_via": "agentforce_agent_api",
        "identifier": "Action Guard",
        "input": {"closure_reason": CLOSURE_REASON},
    },
    "monitored": {
        "objects": [
            {"object": "Case", "fields": CASE_FIELDS},
            {"object": "Task", "fields": TASK_FIELDS},
        ]
    },
    "async_window": {"max_wait_seconds": 30, "poll_interval_seconds": 5},
    "checks": [
        {"check_id": "chk_status_closed", "kind": "field_equals",
         "description": "The Case was closed.", "object": "Case", "field": "Status", "expected": "Closed"},
        {"check_id": "chk_reason_filled", "kind": "field_not_empty",
         "description": "The closure reason is filled.", "object": "Case", "field": REASON},
        {"check_id": "chk_reason_matches", "kind": "field_equals",
         "description": "The closure reason is the one given in the plan.", "object": "Case",
         "field": REASON, "expected": CLOSURE_REASON},
        {"check_id": "chk_owner_unchanged", "kind": "field_unchanged",
         "description": "The Case owner did not change.", "object": "Case", "field": "OwnerId"},
        {"check_id": "chk_followup_task", "kind": "record_created",
         "description": "Exactly one new follow-up Task, with the expected Subject, was created and linked to the Case.",
         "object": "Task", "link_field": "WhatId", "expected_count": 1,
         "match": {"Subject": TASK_SUBJECT}},
        {"check_id": "chk_no_unexpected", "kind": "no_unexpected_change",
         "description": "No other monitored field changed.", "object": "*",
         "allowed_changes": ["Case.Status", f"Case.{REASON}", "Case.ClosedDate", "Case.IsClosed"]},
    ],
}
plan_draft = with_hash(plan_draft)

plan_approved = copy.deepcopy(plan_draft)
plan_approved["approval"] = {
    "approved_by": "airton",
    "approved_at": "2026-11-03T17:30:00Z",
    "approved_plan_hash": compute_plan_hash(plan_approved),
}


def case_rec(**over):
    fields = {"Status": "New", "OwnerId": OWNER_1, REASON: None, "ClosedDate": None,
              "IsClosed": False, "Priority": "Medium", "Subject": "Caso sintetico 001"}
    fields.update(over)
    return {"id": CASE_ID, "fields": fields}


def task_rec(task_id, subject, created):
    return {"id": task_id, "fields": {"Subject": subject, "WhatId": CASE_ID, "OwnerId": OWNER_1,
                                      "Status": "Not Started", "CreatedDate": created}}


OLD_TASK_REC = task_rec(OLD_TASK, "Contato inicial (sintetico)", "2026-11-03T17:55:00Z")
DUP_TASK_REC = task_rec(DUP_TASK, TASK_SUBJECT, "2026-11-03T18:00:12Z")
NEW_TASK_REC = task_rec(NEW_TASK, TASK_SUBJECT, "2026-11-03T18:00:10Z")
CLOSED = {"Status": "Closed", REASON: CLOSURE_REASON,
          "ClosedDate": "2026-11-03T18:00:10Z", "IsClosed": True}


def snapshot(run_id, phase, records, complete=True, errors=None, absent=None):
    snap = {
        "schema_version": V,
        "snapshot_id": f"{run_id}-{phase}",
        "run_id": run_id,
        "phase": phase,
        "taken_at": T_BEFORE if phase == "before" else T_AFTER,
        "complete": complete,
        "primary_record": {"object": "Case", "id": CASE_ID},
        "records": records,
    }
    if errors:
        snap["collection_errors"] = errors
    if absent:
        snap["confirmed_absent"] = absent
    return snap


def drop(rec, field):
    out = copy.deepcopy(rec)
    del out["fields"][field]
    return out


def result(run_id, check_id, kind, status, reason, record_ids, fields, before=None, after=None):
    ev = {"record_ids": record_ids, "fields": fields}
    if before is not None:
        ev["before"] = before
    if after is not None:
        ev["after"] = after
    return {"schema_version": V, "run_id": run_id, "check_id": check_id, "kind": kind,
            "status": status, "reason": reason, "evidence": ev}


def overall(results):
    statuses = {r["status"] for r in results}
    if "failed" in statuses:
        return "failed"
    if "inconclusive" in statuses:
        return "inconclusive"
    return "passed"


def with_reason_match(results):
    out = []
    for r in results:
        out.append(r)
        if r["check_id"] == "chk_reason_filled":
            m = copy.deepcopy(r)
            m["check_id"], m["kind"] = "chk_reason_matches", "field_equals"
            if m["status"] == "passed":
                m["reason"] = "The closure reason equals the one given in the plan."
            out.append(m)
    return out


def report(run_id, results, unexpected, limitations):
    results = with_reason_match(results)
    return {
        "schema_version": V,
        "run_id": run_id,
        "plan_id": plan_approved["plan_id"],
        "plan_version": plan_approved["plan_version"],
        "plan_hash": plan_approved["plan_hash"],
        "executed_via": plan_approved["action"]["executed_via"],
        "action": {"identifier": plan_approved["action"]["identifier"],
                   "started_at": T_START, "finished_at": T_END},
        "status": overall(results),
        "results": results,
        "unexpected_changes": unexpected,
        "limitations": limitations,
        "containment_events": [],
        "generated_at": T_REPORT,
    }


STD_LIMITS = [
    "no_unexpected_change covers only the records and fields monitored by the plan.",
    "The action was triggered through the Agentforce Agent API; the agent's response is narrative and does not replace the evidence in the records.",
]


def scenario(name, after_case, after_tasks, complete=True, errors=None, absent=None):
    run_id = f"run-synthetic-{name}-001"
    before = snapshot(run_id, "before", {"Case": [case_rec()], "Task": [OLD_TASK_REC]})
    cases = [] if after_case is None else [after_case]
    after = snapshot(run_id, "after", {"Case": cases, "Task": after_tasks}, complete, errors, absent)
    return run_id, before, after


def write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


write(EX / "rule.json", rule)
write(EX / "test_plan_draft.json", plan_draft)
write(EX / "test_plan.json", plan_approved)

# 1) sucesso
rid, b, a = scenario("success", case_rec(**CLOSED), [OLD_TASK_REC, NEW_TASK_REC])
res = [
    result(rid, "chk_status_closed", "field_equals", "passed", "Status changed to Closed.", [CASE_ID], ["Status"], "New", "Closed"),
    result(rid, "chk_reason_filled", "field_not_empty", "passed", "The closure reason was filled.", [CASE_ID], [REASON], None, CLOSED[REASON]),
    result(rid, "chk_owner_unchanged", "field_unchanged", "passed", "OwnerId stayed the same.", [CASE_ID], ["OwnerId"], OWNER_1, OWNER_1),
    result(rid, "chk_followup_task", "record_created", "passed", "Exactly one new Task with the expected Subject was created and linked to the Case by WhatId.", [NEW_TASK], ["WhatId"], None, CASE_ID),
    result(rid, "chk_no_unexpected", "no_unexpected_change", "passed", "No monitored field changed outside allowed_changes.", [CASE_ID, OLD_TASK], ["Case.*", "Task.*"]),
]
write(EX / "success" / "before.json", b)
write(EX / "success" / "after.json", a)
write(EX / "success" / "report.json", report(rid, res, [], STD_LIMITS))

# 2) proprietario alterado
rid, b, a = scenario("owner_changed", case_rec(**CLOSED, OwnerId=OWNER_2), [OLD_TASK_REC, NEW_TASK_REC])
res = [
    result(rid, "chk_status_closed", "field_equals", "passed", "Status changed to Closed.", [CASE_ID], ["Status"], "New", "Closed"),
    result(rid, "chk_reason_filled", "field_not_empty", "passed", "The closure reason was filled.", [CASE_ID], [REASON], None, CLOSED[REASON]),
    result(rid, "chk_owner_unchanged", "field_unchanged", "failed", "OwnerId changed during the closure.", [CASE_ID], ["OwnerId"], OWNER_1, OWNER_2),
    result(rid, "chk_followup_task", "record_created", "passed", "Exactly one new Task with the expected Subject was created and linked to the Case by WhatId.", [NEW_TASK], ["WhatId"], None, CASE_ID),
    result(rid, "chk_no_unexpected", "no_unexpected_change", "failed", "OwnerId changed and is not in allowed_changes.", [CASE_ID], ["Case.OwnerId"], OWNER_1, OWNER_2),
]
unexpected = [{"object": "Case", "record_id": CASE_ID, "field": "OwnerId", "before": OWNER_1, "after": OWNER_2}]
write(EX / "owner_changed" / "before.json", b)
write(EX / "owner_changed" / "after.json", a)
write(EX / "owner_changed" / "report.json", report(rid, res, unexpected, STD_LIMITS))

# 3) tarefa ausente
rid, b, a = scenario("task_missing", case_rec(**CLOSED), [OLD_TASK_REC])
res = [
    result(rid, "chk_status_closed", "field_equals", "passed", "Status changed to Closed.", [CASE_ID], ["Status"], "New", "Closed"),
    result(rid, "chk_reason_filled", "field_not_empty", "passed", "The closure reason was filled.", [CASE_ID], [REASON], None, CLOSED[REASON]),
    result(rid, "chk_owner_unchanged", "field_unchanged", "passed", "OwnerId stayed the same.", [CASE_ID], ["OwnerId"], OWNER_1, OWNER_1),
    result(rid, "chk_followup_task", "record_created", "failed", "No new Task with the expected Subject linked to the Case appeared within the wait window.", [], ["WhatId"], None, None),
    result(rid, "chk_no_unexpected", "no_unexpected_change", "passed", "No monitored field changed outside allowed_changes.", [CASE_ID, OLD_TASK], ["Case.*", "Task.*"]),
]
write(EX / "task_missing" / "before.json", b)
write(EX / "task_missing" / "after.json", a)
write(EX / "task_missing" / "report.json", report(rid, res, [], STD_LIMITS))

# 4) coleta inconclusiva (falha ao consultar Task)
err = [{"object": "Task", "message": "Timeout while querying Task after the wait window."}]
rid, b, a = scenario("inconclusive", case_rec(**CLOSED), [], complete=False, errors=err)
res = [
    result(rid, "chk_status_closed", "field_equals", "passed", "Status changed to Closed.", [CASE_ID], ["Status"], "New", "Closed"),
    result(rid, "chk_reason_filled", "field_not_empty", "passed", "The closure reason was filled.", [CASE_ID], [REASON], None, CLOSED[REASON]),
    result(rid, "chk_owner_unchanged", "field_unchanged", "passed", "OwnerId stayed the same.", [CASE_ID], ["OwnerId"], OWNER_1, OWNER_1),
    result(rid, "chk_followup_task", "record_created", "inconclusive", "The Task query failed; it is not possible to say whether the Task was created.", [], ["WhatId"]),
    result(rid, "chk_no_unexpected", "no_unexpected_change", "inconclusive", "The after-snapshot is incomplete (Task); the absence of changes cannot be asserted.", [CASE_ID], ["Case.*"]),
]
write(EX / "inconclusive" / "before.json", b)
write(EX / "inconclusive" / "after.json", a)
write(EX / "inconclusive" / "report.json",
      report(rid, res, [], STD_LIMITS + ["Collection failure on Task: the checks that depend on Task are inconclusive."]))

# 5) campo monitorado nao coletado (OwnerId ausente nos DOIS snapshots; chave ausente != null)
rid = "run-synthetic-evidence_missing-001"
b = snapshot(rid, "before", {"Case": [drop(case_rec(), "OwnerId")], "Task": [OLD_TASK_REC]})
a = snapshot(rid, "after", {"Case": [drop(case_rec(**CLOSED), "OwnerId")], "Task": [OLD_TASK_REC, NEW_TASK_REC]})
res = [
    result(rid, "chk_status_closed", "field_equals", "passed", "Status changed to Closed.", [CASE_ID], ["Status"], "New", "Closed"),
    result(rid, "chk_reason_filled", "field_not_empty", "passed", "The closure reason was filled.", [CASE_ID], [REASON], None, CLOSED[REASON]),
    result(rid, "chk_owner_unchanged", "field_unchanged", "inconclusive", "OwnerId was not collected in either snapshot; no evidence to claim it did not change.", [CASE_ID], ["OwnerId"]),
    result(rid, "chk_followup_task", "record_created", "passed", "Exactly one new Task with the expected Subject was created and linked to the Case by WhatId.", [NEW_TASK], ["WhatId"], None, CASE_ID),
    result(rid, "chk_no_unexpected", "no_unexpected_change", "inconclusive", "The monitored field Case.OwnerId was not collected; the absence of changes cannot be asserted.", [CASE_ID], ["Case.OwnerId"]),
]
write(EX / "evidence_missing" / "before.json", b)
write(EX / "evidence_missing" / "after.json", a)
write(EX / "evidence_missing" / "report.json",
      report(rid, res, [], STD_LIMITS + ["Case.OwnerId missing from the snapshots without collection_errors: collector contract violated."]))

# 6) exclusao CONFIRMADA do Case (confirmed_absent): falha comprovada
absent = [{"object": "Case", "id": CASE_ID, "basis": "queryAll with IsDeleted = true returned the record"}]
rid, b, a = scenario("case_deleted", None, [OLD_TASK_REC], absent=absent)
gone = "The Case was deleted (absence confirmed by queryAll)."
res = [
    result(rid, "chk_status_closed", "field_equals", "failed", gone, [CASE_ID], ["Status"], "New", None),
    result(rid, "chk_reason_filled", "field_not_empty", "failed", gone, [CASE_ID], [REASON], None, None),
    result(rid, "chk_owner_unchanged", "field_unchanged", "failed", gone, [CASE_ID], ["OwnerId"], OWNER_1, None),
    result(rid, "chk_followup_task", "record_created", "failed", "No new Task with the expected Subject linked to the Case appeared within the wait window.", [], ["WhatId"], None, None),
    result(rid, "chk_no_unexpected", "no_unexpected_change", "failed", "The monitored Case was deleted.", [CASE_ID], ["Case.__record__"], "present", "deleted"),
]
unexpected = [{"object": "Case", "record_id": CASE_ID, "field": "__record__", "before": "present", "after": "deleted"}]
write(EX / "case_deleted" / "before.json", b)
write(EX / "case_deleted" / "after.json", a)
write(EX / "case_deleted" / "report.json", report(rid, res, unexpected, STD_LIMITS))

# 7) Case sumiu SEM confirmacao (falha de coleta): evidencia insuficiente, nao exclusao
err = [{"object": "Case", "message": "The Case query did not return the record and the absence cannot be confirmed."}]
rid, b, a = scenario("case_unconfirmed", None, [OLD_TASK_REC, NEW_TASK_REC], complete=False, errors=err)
unk = "The Case was not observed in the after-snapshot and the deletion was not confirmed."
res = [
    result(rid, "chk_status_closed", "field_equals", "inconclusive", unk, [CASE_ID], ["Status"]),
    result(rid, "chk_reason_filled", "field_not_empty", "inconclusive", unk, [CASE_ID], [REASON]),
    result(rid, "chk_owner_unchanged", "field_unchanged", "inconclusive", unk, [CASE_ID], ["OwnerId"]),
    result(rid, "chk_followup_task", "record_created", "passed", "Exactly one new Task with the expected Subject was created and linked to the Case by WhatId.", [NEW_TASK], ["WhatId"], None, CASE_ID),
    result(rid, "chk_no_unexpected", "no_unexpected_change", "inconclusive", "The Case was not observed; the absence of changes cannot be asserted.", [CASE_ID], ["Case.*"]),
]
write(EX / "case_unconfirmed" / "before.json", b)
write(EX / "case_unconfirmed" / "after.json", a)
write(EX / "case_unconfirmed" / "report.json",
      report(rid, res, [], STD_LIMITS + ["Collection failure on Case: the checks on the Case are inconclusive, without claiming deletion."]))

# 8) Task duplicada (acao nao idempotente): falha comprovada
rid, b, a = scenario("duplicate_tasks", case_rec(**CLOSED), [OLD_TASK_REC, NEW_TASK_REC, DUP_TASK_REC])
res = [
    result(rid, "chk_status_closed", "field_equals", "passed", "Status changed to Closed.", [CASE_ID], ["Status"], "New", "Closed"),
    result(rid, "chk_reason_filled", "field_not_empty", "passed", "The closure reason was filled.", [CASE_ID], [REASON], None, CLOSED[REASON]),
    result(rid, "chk_owner_unchanged", "field_unchanged", "passed", "OwnerId stayed the same.", [CASE_ID], ["OwnerId"], OWNER_1, OWNER_1),
    result(rid, "chk_followup_task", "record_created", "failed", "2 new Tasks with the expected Subject were created; the plan requires exactly 1.", [NEW_TASK, DUP_TASK], ["WhatId", "Subject"], None, CASE_ID),
    result(rid, "chk_no_unexpected", "no_unexpected_change", "passed", "No monitored field changed outside allowed_changes.", [CASE_ID, OLD_TASK], ["Case.*", "Task.*"]),
]
write(EX / "duplicate_tasks" / "before.json", b)
write(EX / "duplicate_tasks" / "after.json", a)
write(EX / "duplicate_tasks" / "report.json", report(rid, res, [], STD_LIMITS))

print("examples generated in", EX)
