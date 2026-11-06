"""CLI (writes to Salesforce only in `seed` and `remediate`; `score` reads a saved report).

  python -m calibration seed --out calibration_run --confirm-write      # 3 controls + 4 faulty synthetic Cases
  python -m audit run --plan approved_plan.json --case-ids calibration_run/ids.txt --list-all ...
  python -m calibration score --truth calibration_run/calibration.json --report audit_report.json
  python -m calibration remediate --truth calibration_run/calibration.json --label fault_no_reason --confirm-write
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path

from connector.auth import AuthError, get_token
from connector.config import ConfigError, SalesforceConfig
from connector.ids import key15
from connector.rest import QueryError, SalesforceRest
from connector.transport import UrllibTransport

MARKER = "[SYNTHETIC]"
FOLLOWUP = "Action Guard - Case closure follow-up"
FIX_REASON = "Resolved - Guidance provided"

# label, closure reason, tasks to create (subjects), fault description, auto-fixable
SPECS = [
    ("control_1", "Resolved - Customer confirmed", [FOLLOWUP], None, False),
    ("control_2", "Duplicate", [FOLLOWUP], None, False),
    ("control_3", "Cancelled", [FOLLOWUP], None, False),
    ("fault_no_reason", None, [FOLLOWUP], "Closed without the mandatory closure reason", True),
    ("fault_no_task", "Resolved - Customer confirmed", [], "Closed with no follow-up Task", True),
    ("fault_wrong_subject_task", "Duplicate", ["Follow up"], "Closed; the only Task has the wrong Subject", True),
    ("fault_duplicate_task", "Cancelled", [FOLLOWUP, FOLLOWUP], "Closed with two follow-up Tasks (fixing needs a deletion: left for a human)", False),
]


def _rest(transport, secret=None):
    env = dict(os.environ)
    for key in ("SF_CLIENT_ID", "SF_CLIENT_SECRET"):
        if not env.get(key):
            env[key] = (secret or getpass.getpass)(key + " (hidden): ")
    cfg = SalesforceConfig.from_env(env)
    return SalesforceRest(cfg, get_token(cfg, transport), transport)


def seed(rest: SalesforceRest, out: Path) -> dict:
    truth_path = out / "calibration.json"
    if truth_path.exists():
        raise ValueError("calibration.json already exists here; create a new folder (cases are never re-seeded).")
    out.mkdir(parents=True, exist_ok=True)
    truth: dict = {"marker": MARKER, "cases": {}}
    for label, reason, tasks, fault, fixable in SPECS:
        cid = rest.create("Case", {"Subject": f"{MARKER} Calibration {label}", "Status": "New", "Origin": "Web"})
        fields = {"Status": "Closed"}
        if reason:
            fields["Closure_Reason__c"] = reason
        rest.update("Case", cid, fields)
        for subj in tasks:
            rest.create("Task", {"Subject": subj, "WhatId": cid})
        truth["cases"][cid] = {"label": label, "injected": fault is not None, "fault": fault, "auto_fixable": fixable,
                               "expected": "incorrect" if fault else "correct"}
        truth_path.write_text(json.dumps(truth, indent=2))          # written after every Case: a crash leaves a record
    (out / "ids.txt").write_text("\n".join(truth["cases"]) + "\n")
    return truth


def score(truth: dict, report: dict) -> dict:
    rows = {key15(c["case_id"]): c for c in report["cases"]}
    out, injected, detected, controls, false_alarms = [], 0, 0, 0, 0
    for cid, t in truth["cases"].items():
        got = rows.get(key15(cid))
        status = got["status"] if got else "not_audited"
        ok = status == t["expected"]
        if t["injected"]:
            injected += 1; detected += ok
        else:
            controls += 1; false_alarms += (status != "correct")
        out.append({"case_id": cid, "label": t["label"], "fault": t["fault"], "expected": t["expected"], "detected_status": status,
                    "failed_checks": got["failed_checks"] if got else [], "ok": ok})
    return {"audit_id": report["audit_id"], "audited_at": report["generated_at"], "plan_hash": report["plan_hash"],
            "injected": injected, "detected": detected, "missed": injected - detected, "controls": controls,
            "false_alarms": false_alarms, "cases": out}


def remediate(rest: SalesforceRest, truth: dict, label: str) -> str:
    cid = next((c for c, t in truth["cases"].items() if t["label"] == label), None)
    if not cid:
        raise ValueError("Unknown label.")
    t = truth["cases"][cid]
    if not t["injected"] or not t["auto_fixable"]:
        raise ValueError("This Case is not auto-fixable (a control, or a fix that needs deleting a record). Handle it by hand or accept the risk.")
    rows = rest.query(f"SELECT Subject, Closure_Reason__c FROM Case WHERE Id = '{cid}'")
    if not rows or not str(rows[0].get("Subject") or "").startswith(MARKER):
        raise ValueError("Refused: the Case is not marked as synthetic.")
    done = []
    if t["label"] == "fault_no_reason" and not rows[0].get("Closure_Reason__c"):
        rest.update("Case", cid, {"Closure_Reason__c": FIX_REASON}); done.append("closure reason set")
    if t["label"] in ("fault_no_task", "fault_wrong_subject_task"):
        have = rest.query(f"SELECT Subject FROM Task WHERE WhatId = '{cid}'")
        if not any(x.get("Subject") == FOLLOWUP for x in have):
            rest.create("Task", {"Subject": FOLLOWUP, "WhatId": cid}); done.append("follow-up Task created")
    return ", ".join(done) or "nothing to do (already fixed)"


def main(argv=None, *, transport=None, secret=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m calibration")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed"); s.add_argument("--out", required=True); s.add_argument("--confirm-write", action="store_true")
    c = sub.add_parser("score"); c.add_argument("--truth", required=True); c.add_argument("--report", required=True); c.add_argument("--out")
    r = sub.add_parser("remediate"); r.add_argument("--truth", required=True); r.add_argument("--label", required=True); r.add_argument("--confirm-write", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "score":
            res = score(json.load(open(a.truth)), json.load(open(a.report)))
            print(f"Injected faults detected: {res['detected']} of {res['injected']} · controls flagged wrongly: {res['false_alarms']} of {res['controls']}")
            for x in res["cases"]:
                print(f"  {x['label']:<26} expected {x['expected']:<10} got {x['detected_status']:<10} {'OK' if x['ok'] else 'MISMATCH'}")
            if a.out:
                Path(a.out).write_text(json.dumps(res, indent=2))
            return 0 if not res["missed"] and not res["false_alarms"] else 2
        if not a.confirm_write:
            print("Refused: pass --confirm-write to acknowledge that this writes to synthetic Cases in Salesforce.")
            return 1
        rest = _rest(transport or UrllibTransport(), secret)
        if a.cmd == "seed":
            truth = seed(rest, Path(a.out))
            print(f"Created {len(truth['cases'])} synthetic Cases (3 controls, 4 injected faults). Ids in {a.out}/ids.txt")
        else:
            print(remediate(rest, json.load(open(a.truth)), a.label))
        return 0
    except (ValueError, QueryError, AuthError, ConfigError, OSError, KeyError) as e:
        print("Operation interrupted:", type(e).__name__, str(e)[:200])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
