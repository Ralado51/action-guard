"""Append-only findings log. A divergence becomes a finding; it is closed only by a passing revalidation or an
explicit, justified risk acceptance. History is never rewritten: every change is a new event.

Actors are DECLARED names (shared token), not authenticated identities. This is a prototype of the accountability
model, not enterprise governance.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audit.evaluate import CORRECT
from audit.policy import finding_severity
from connector.ids import key15

TERMINAL = {"closed", "risk_accepted"}
MIN_JUSTIFICATION = 20


class FindingError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm(o: Any) -> Any:
    """Integral floats become ints so the same text is produced by Python and by a browser's JSON.stringify."""
    if isinstance(o, float) and o.is_integer():
        return int(o)
    if isinstance(o, dict):
        return {k: _norm(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_norm(v) for v in o]
    return o


def canonical(obj: Any) -> str:
    return json.dumps(_norm(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(obj: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def report_hash(report: dict[str, Any]) -> str:
    return sha(report)


def check_row_consistency(row: dict[str, Any]) -> None:
    """A Case row may only be trusted if its status follows from its own checks."""
    checks = row.get("checks")
    if not checks:
        raise FindingError("The report row has no per-check results, so its status cannot be verified.")
    failed = sorted(c["check_id"] for c in checks if c.get("status") == "failed")
    inconc = sorted(c["check_id"] for c in checks if c.get("status") == "inconclusive")
    if sorted(row.get("failed_checks") or []) != failed or sorted(row.get("inconclusive_checks") or []) != inconc:
        raise FindingError("The report is inconsistent: the listed failures do not match the per-check results.")
    all_passed = not failed and not inconc and all(c.get("status") == "passed" for c in checks)
    if (row.get("status") == CORRECT) != all_passed:
        raise FindingError("The report is inconsistent: the Case status does not follow from its per-check results.")

class FindingStore:
    def __init__(self, directory: str | os.PathLike, clock=_now):
        self.dir, self.clock = Path(directory), clock
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "events.jsonl"
        self.path.touch(exist_ok=True)
        os.chmod(self.path, 0o600)

    # -- storage --
    def events(self, finding_id: str | None = None) -> list[dict[str, Any]]:
        out = []
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    e = json.loads(line)
                    if finding_id is None or e["finding_id"] == finding_id:
                        out.append(e)
        return out

    def _append(self, event: dict[str, Any]) -> dict[str, Any]:
        with open(self.path, "a+", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.seek(0)
            event["seq"] = sum(1 for ln in fh if ln.strip()) + 1
            event["at"] = self.clock()
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
            fh.flush(); os.fsync(fh.fileno())
        return event

    # -- state --
    def state(self, finding_id: str) -> dict[str, Any]:
        ev = self.events(finding_id)
        if not ev:
            raise FindingError("Unknown finding.")
        opened = ev[0]["data"]
        st, assignee, reval, fix_at = "open", None, None, None
        for e in ev[1:]:
            t = e["type"]
            if t == "assigned":
                st, assignee = "assigned", e["data"]["assignee"]
            elif t == "fix_recorded":
                st, fix_at, reval = "fix_recorded", e["at"], None
            elif t == "revalidated":
                reval = e["data"]
                st = "revalidated" if reval["passed"] else "revalidation_failed"
            elif t == "closed":
                st = "closed"
            elif t == "risk_accepted":
                st = "risk_accepted"
        return {"finding_id": finding_id, "state": st, "case_id": opened["case_id"], "severity": opened["severity"],
                "failed_checks": opened["failed_checks"], "plan_hash": opened["plan_hash"], "opened_audit_id": opened["audit_id"],
                "assignee": assignee, "last_revalidation": reval, "fix_recorded_at": fix_at, "events": ev}

    def list(self) -> list[dict[str, Any]]:
        ids = list(dict.fromkeys(e["finding_id"] for e in self.events()))
        return [self.state(i) for i in ids]

    # -- commands --
    def open_from_report(self, report: dict[str, Any], actor: str) -> list[str]:
        policy = report.get("policy")
        if not policy:
            raise FindingError("The report has no policy block; run the audit again.")
        for c in report["cases"]:
            check_row_consistency(c)        # a row marked correct that hides a failed check must not slip through
        existing = {s["case_id"] for s in self.list() if s["state"] not in TERMINAL}
        opened = []
        for c in report["cases"]:
            if c["status"] == CORRECT or key15(c["case_id"]) in {key15(x) for x in existing}:
                continue
            fid = "F-" + hashlib.sha256((key15(c["case_id"]) + report["audit_id"]).encode()).hexdigest()[:8]
            sev = finding_severity(c["failed_checks"], policy) if c["failed_checks"] else "inconclusive"
            self._append({"finding_id": fid, "type": "opened", "actor": actor, "note": None, "data": {
                "case_id": c["case_id"], "severity": sev, "failed_checks": c["failed_checks"],
                "inconclusive_checks": c["inconclusive_checks"], "audit_id": report["audit_id"],
                "plan_hash": report["plan_hash"], "report_hash": report_hash(report),
                "found": {k["check_id"]: k["found"] for k in c.get("checks", []) if k["status"] != "passed"}}})
            opened.append(fid)
        return opened

    def _live(self, fid: str, actor: str) -> dict[str, Any]:
        if not actor or not actor.strip():
            raise FindingError("An actor name is required.")
        s = self.state(fid)
        if s["state"] in TERMINAL:
            raise FindingError(f"The finding is already {s['state']}; history is not reopened.")
        return s

    def assign(self, fid: str, actor: str, assignee: str) -> None:
        self._live(fid, actor)
        if not assignee.strip():
            raise FindingError("An assignee is required.")
        self._append({"finding_id": fid, "type": "assigned", "actor": actor, "note": None, "data": {"assignee": assignee.strip()}})

    def record_fix(self, fid: str, actor: str, note: str) -> None:
        self._live(fid, actor)
        if len(note.strip()) < 10:
            raise FindingError("Describe the correction (at least 10 characters).")
        self._append({"finding_id": fid, "type": "fix_recorded", "actor": actor, "note": note.strip(), "data": {}})

    def revalidate(self, fid: str, actor: str, report: dict[str, Any]) -> bool:
        s = self._live(fid, actor)
        if not s["fix_recorded_at"]:
            raise FindingError("Record the correction before revalidating.")
        if report["plan_hash"] != s["plan_hash"]:
            raise FindingError("The new audit used a different plan; revalidation must use the same approved plan.")
        if report["audit_id"] == s["opened_audit_id"]:
            raise FindingError("Revalidation needs a new audit, not the one that found the problem.")
        if report["generated_at"] < s["fix_recorded_at"]:
            raise FindingError("The audit predates the recorded correction; run a new audit after the fix.")
        row = next((c for c in report["cases"] if key15(c["case_id"]) == key15(s["case_id"])), None)
        if row is None:
            raise FindingError("The new audit does not include this Case (use --list-all or its Id).")
        check_row_consistency(row)
        passed = row["status"] == CORRECT
        self._append({"finding_id": fid, "type": "revalidated", "actor": actor, "note": None, "data": {
            "passed": passed, "audit_id": report["audit_id"], "report_hash": report_hash(report), "case_status": row["status"]}})
        return passed

    def close(self, fid: str, actor: str) -> None:
        s = self._live(fid, actor)
        if s["state"] != "revalidated":
            raise FindingError("Only a passing revalidation closes a finding. Otherwise accept the risk explicitly, with a justification.")
        self._append({"finding_id": fid, "type": "closed", "actor": actor, "note": None,
                      "data": {"revalidation_audit_id": s["last_revalidation"]["audit_id"]}})

    def accept_risk(self, fid: str, actor: str, justification: str) -> None:
        s = self._live(fid, actor)
        if len(justification.strip()) < MIN_JUSTIFICATION:
            raise FindingError(f"A justification of at least {MIN_JUSTIFICATION} characters is required to accept a risk.")
        self._append({"finding_id": fid, "type": "risk_accepted", "actor": actor, "note": justification.strip(),
                      "data": {"severity": s["severity"], "unresolved": True}})
