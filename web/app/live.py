"""Controlled live demo: a visitor opens a synthetic Case, an agent handles it, Action Guard checks the result.

Everything that matters is decided on the SERVER: the browser only sends a session id, a scenario key and a mode.
It never chooses Case Ids, tool arguments or the plan. Off by default; separate from the demo-mode switch.
Limits count sessions STARTED (failed ones included) and survive restarts (sqlite).
"""
from __future__ import annotations

import dataclasses
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from acceptance.findings import FindingError, FindingStore
from audit.mask import mask_report, mask_text
from audit.policy import finding_severity
from audit.run import AuditBlocked, run_audit
from calibration.__main__ import FIX_REASON, FOLLOWUP, MARKER
from connector.auth import get_token
from connector.config import SalesforceConfig
from connector.ids import key15
from connector.ledger import Ledger
from connector.rest import QueryError, SalesforceRest
from connector.transport import UrllibTransport
from contracts.plan_hash import approval_is_valid
from planner.client import VultrChatClient
from planner.config import PlannerConfig
from vultr_agent.agent import run_agent
from vultr_agent.tools import Guard, SalesforceTools

SCENARIOS = {
    "wrong_item": ("Wrong item: exchange arranged by phone", "The team already arranged the exchange with the customer by phone. Record the closure and schedule a follow-up.", "Resolved - Guidance provided"),
    "late_shipment": ("Late shipment: customer was informed", "The team already told the customer the new delivery date. Record the closure and schedule a follow-up.", "Resolved - Customer confirmed"),
    "duplicate_charge": ("Duplicate charge: refund handled elsewhere", "The duplicate charge was already handled in the billing system. Record the closure and schedule a follow-up.", "Duplicate"),
    "cancel_order": ("Order cancelled by the team", "The team already cancelled the order at the customer's request. Record the closure and schedule a follow-up.", "Cancelled"),
}
MODES = ("agent", "verifier_test")
SESSION_TTL = 6 * 3600
MAX_RUNNING = 2
MAX_CHECKS = 6
SID = re.compile(r"^[0-9a-f]{32}$")


class LiveError(Exception):
    def __init__(self, code: int, message: str):
        self.code, self.message = code, message


@dataclass(frozen=True)
class LiveConfig:
    enabled: bool
    reason: str | None
    code: str = ""
    daily: int = 0
    hourly: int = 4
    plan_file: str = ""

    @classmethod
    def from_env(cls, env=None) -> "LiveConfig":
        e = env if env is not None else os.environ
        if str(e.get("ACTION_GUARD_LIVE_DEMO", "off")).strip().lower() not in {"on", "true", "1"}:
            return cls(False, "off")
        code = e.get("ACTION_GUARD_LIVE_CODE", "")
        try:
            daily, hourly = int(e.get("ACTION_GUARD_LIVE_DAILY_LIMIT", "0")), int(e.get("ACTION_GUARD_LIVE_HOURLY_LIMIT", "4"))
        except ValueError:
            return cls(False, "misconfigured")
        plan_file = e.get("ACTION_GUARD_LIVE_PLAN_FILE", "")
        if len(code) < 8 or daily <= 0 or hourly <= 0 or not plan_file or not Path(plan_file).is_file():
            return cls(False, "misconfigured")
        return cls(True, None, code, daily, hourly, plan_file)


def _load_plan(path: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    plan = data["plan"] if isinstance(data, dict) and "plan" in data else data
    if not approval_is_valid(plan):
        raise LiveError(503, "The live demo plan is not a valid approved plan.")
    return plan


def default_rest() -> SalesforceRest:
    http = UrllibTransport()
    cfg = SalesforceConfig.from_env(dict(os.environ))
    return SalesforceRest(cfg, get_token(cfg, http), http)


def default_agent(rest: SalesforceRest, case_id: str, reason: str) -> dict[str, Any]:
    cfg = dataclasses.replace(PlannerConfig.from_env(), max_calls=6)
    client = VultrChatClient(cfg, UrllibTransport())
    tools = SalesforceTools(rest, Guard(frozenset({key15(case_id)}), max_writes=3))
    return run_agent(client, tools, case_id, reason, model=cfg.model, max_steps=6)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _mask(obj: Any) -> Any:
    return json.loads(mask_text(json.dumps(obj, ensure_ascii=False)))


def _claim(ev: dict[str, Any]) -> dict[str, Any]:
    return {"source": ev.get("source", "vultr-agent"), "outcome": ev["outcome"], "final_message": ev.get("final_message"),
            "steps": [{"at": s["at"], "tool": (s.get("request") or {}).get("tool") or ("final" if s.get("final") else s.get("error", "none")),
                       "result": json.dumps(s["result"])[:300] if "result" in s else None} for s in ev["steps"]]}


class LiveDemo:
    def __init__(self, root, config: LiveConfig | None = None, *, rest_factory: Callable[[], SalesforceRest] = default_rest,
                 agent_runner: Callable[..., dict[str, Any]] = default_agent, clock: Callable[[], float] = time.time,
                 now_iso: Callable[[], str] = _now_iso):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.cfg = config or LiveConfig.from_env()
        self.rest_factory, self.agent_runner, self.clock, self.now_iso = rest_factory, agent_runner, clock, now_iso
        self.db = self.root / "live.sqlite3"
        with self._c() as db:
            db.executescript("""CREATE TABLE IF NOT EXISTS usage (ts REAL NOT NULL, kind TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, created REAL NOT NULL, state TEXT NOT NULL, body TEXT NOT NULL);""")
        os.chmod(self.db, 0o600)

    def _c(self):
        db = sqlite3.connect(self.db, timeout=10); db.execute("PRAGMA busy_timeout=10000"); return db

    # ---- limits ----
    def _count(self, db, kind: str, window: float) -> int:
        return db.execute("SELECT COUNT(*) FROM usage WHERE kind=? AND ts>?", (kind, self.clock() - window)).fetchone()[0]

    def status(self) -> dict[str, Any]:
        return {"enabled": self.cfg.enabled, "reason": self.cfg.reason,
                "scenarios": [{"key": k, "title": v[0], "text": v[1]} for k, v in SCENARIOS.items()],
                "modes": list(MODES)}

    # ---- sessions ----
    def _load(self, sid: str) -> dict[str, Any]:
        if not SID.fullmatch(sid or ""):
            raise LiveError(404, "Unknown session.")
        with self._c() as db:
            row = db.execute("SELECT body FROM sessions WHERE id=?", (sid,)).fetchone()
        if not row:
            raise LiveError(404, "Unknown session.")
        s = json.loads(row[0])
        if self.clock() - s["created"] > SESSION_TTL:
            raise LiveError(410, "This session has expired. Start a new one.")
        return s

    def _save(self, s: dict[str, Any]) -> None:
        with self._c() as db:
            db.execute("UPDATE sessions SET state=?, body=? WHERE id=?", (s["state"], json.dumps(s), s["id"]))

    def _transition(self, sid: str, frm: str, to: str) -> bool:
        with self._c() as db:
            cur = db.execute("UPDATE sessions SET state=? WHERE id=? AND state=?", (to, sid, frm))
            if cur.rowcount != 1:
                return False
            row = db.execute("SELECT body FROM sessions WHERE id=?", (sid,)).fetchone()
            body = json.loads(row[0]); body["state"] = to
            db.execute("UPDATE sessions SET body=? WHERE id=?", (json.dumps(body), sid))
            return True

    def create(self, code: str, scenario: str, mode: str) -> dict[str, Any]:
        if not self.cfg.enabled:
            raise LiveError(503, "The live demo is switched off.")
        if scenario not in SCENARIOS or mode not in MODES:
            raise LiveError(422, "Unknown scenario or mode.")
        with self._c() as db:
            if self._count(db, "badcode", 3600) >= 20:
                raise LiveError(429, "Too many wrong codes. Try again later.")
            if not hmac.compare_digest(str(code).encode(), self.cfg.code.encode()):
                db.execute("INSERT INTO usage VALUES (?,?)", (self.clock(), "badcode"))
                db.commit()                                  # a raise below would otherwise roll the attempt back
                raise LiveError(403, "Invalid access code.")
            if self._count(db, "session", 3600) >= self.cfg.hourly or self._count(db, "session", 86400) >= self.cfg.daily:
                raise LiveError(429, "The live demo reached its usage limit for now. The recorded walkthrough is always available.")
            if db.execute("SELECT COUNT(*) FROM sessions WHERE state='running'").fetchone()[0] >= MAX_RUNNING:
                raise LiveError(429, "The live demo is busy. Try again in a minute.")
            db.execute("INSERT INTO usage VALUES (?,?)", (self.clock(), "session"))     # counted BEFORE any write
        title, text, reason = SCENARIOS[scenario]
        sid = secrets.token_hex(16)
        s: dict[str, Any] = {"id": sid, "created": self.clock(), "state": "created", "mode": mode, "scenario": scenario,
                             "reason": reason, "case_id": None, "claims": None, "reports": [], "finding": None, "checks": 0, "error": None}
        try:
            rest = self.rest_factory()
            cid = rest.create("Case", {"Subject": f"{MARKER} Live demo · {title}", "Description": text, "Status": "New", "Origin": "Web"})
            s["case_id"] = cid
            with self._c() as db:
                db.execute("INSERT INTO sessions VALUES (?,?,?,?)", (sid, s["created"], s["state"], json.dumps(s)))
            if mode == "verifier_test":
                rest.update("Case", cid, {"Status": "Closed"})                       # fault: closed with NO closure reason
                rest.create("Task", {"Subject": FOLLOWUP, "WhatId": cid})
                s["claims"] = {"source": "controlled-fault", "outcome": "injected", "final_message": None, "steps": []}
                s["state"] = "agent_done"
                self._save(s)
        except (QueryError, OSError, KeyError, ValueError):
            s["state"], s["error"] = "failed", "Salesforce could not be reached; nothing more will be attempted for this session."
            with self._c() as db:
                db.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,?,?)", (sid, s["created"], s["state"], json.dumps(s)))
        return self.view(sid)

    def begin_run(self, sid: str) -> bool:
        s = self._load(sid)
        if s["mode"] != "agent":
            raise LiveError(409, "This session has no agent run.")
        return self._transition(sid, "created", "running")

    def work(self, sid: str) -> None:
        s = self._load(sid)
        try:
            led = Ledger(self.root / "ledger")
            if not led.reserve(s["case_id"], "live-vultr"):
                raise RuntimeError("already reserved")
            ev = self.agent_runner(self.rest_factory(), s["case_id"], s["reason"])
            s = self._load(sid)
            s["claims"] = _claim(ev)
            s["state"] = "uncertain" if ev["outcome"] == "uncertain_write" else "agent_done"
            led.record(s["case_id"], "live-vultr", ev["outcome"])
        except Exception:
            s = self._load(sid)
            s["state"], s["error"] = "failed", "The agent run did not complete; the Case may be partly handled. It is not retried."
        self._save(s)

    # ---- check / fix ----
    def _audit(self, s: dict[str, Any]) -> dict[str, Any]:
        plan = _load_plan(self.cfg.plan_file)
        claims = {s["case_id"]: s["claims"]} if s.get("claims") else None
        return run_audit(plan, self.rest_factory(), case_ids=[s["case_id"]], list_all=True, agent_runs=claims, now=self.now_iso)

    def check(self, sid: str) -> dict[str, Any]:
        s = self._load(sid)
        if s["state"] not in ("agent_done", "uncertain", "fixed", "revalidation_failed"):
            raise LiveError(409, "There is nothing to check yet.")
        if s["checks"] >= MAX_CHECKS:
            raise LiveError(429, "Check limit reached for this session.")
        try:
            rep = self._audit(s)
        except (AuditBlocked, QueryError) as e:
            raise LiveError(502, "The check could not be completed: " + str(e)[:160])
        s["reports"].append(rep); s["checks"] += 1
        self._save(s)
        return self.view(sid)

    def fix(self, sid: str) -> dict[str, Any]:
        s = self._load(sid)
        if s["mode"] != "verifier_test" or s["state"] != "agent_done" or not s["reports"]:
            raise LiveError(409, "Fix is available once, after a check that found the controlled fault.")
        first = s["reports"][-1]
        row = first["cases"][0]
        if row["status"] == "correct":
            raise LiveError(409, "Nothing to fix: the check passed.")
        if not self._transition(sid, "agent_done", "fixing"):
            raise LiveError(409, "A fix is already in progress.")
        s = self._load(sid)
        store = FindingStore(self.root / "findings" / sid)
        try:
            fid = store.open_from_report(first, "Action Guard audit")[0]
            store.assign(fid, "Demo visitor", "Demo visitor")
            rest = self.rest_factory()
            rows = rest.query(f"SELECT Subject, Closure_Reason__c FROM Case WHERE Id = '{s['case_id']}'")
            if not rows or not str(rows[0].get("Subject") or "").startswith(MARKER):
                raise LiveError(409, "Refused: the Case is not marked as synthetic.")
            if not rows[0].get("Closure_Reason__c"):
                rest.update("Case", s["case_id"], {"Closure_Reason__c": FIX_REASON})
            store.record_fix(fid, "Demo visitor", "Closure reason set by the demo server at the visitor's request")
            second = self._audit(s)
            s["reports"].append(second); s["checks"] += 1
            store.revalidate(fid, "Demo visitor", second)
            if store.state(fid)["state"] == "revalidated":
                store.close(fid, "Demo visitor")
            s["finding"] = store.state(fid)
            if s["finding"]["state"] == "closed":
                s["state"] = "fixed"
            else:
                s["state"], s["error"] = "revalidation_failed", "The new audit did not pass, so the finding stays open. It is not counted as fixed."
        except (FindingError, AuditBlocked, QueryError, LiveError) as e:
            s["state"], s["error"] = "agent_done", "The fix could not be completed: " + (e.message if isinstance(e, LiveError) else str(e))[:160]
        self._save(s)
        return self.view(sid)

    def activity(self) -> dict[str, Any]:
        """Public, aggregate-only summary of past sessions: no codes, no Case Ids, no agent text."""
        with self._c() as db:
            rows = db.execute("SELECT body FROM sessions ORDER BY created DESC").fetchall()
        items, agg = [], {"sessions": 0, "checked": 0, "agent_passed": 0, "agent_failed": 0, "agent_inconclusive": 0, "faults_injected": 0, "faults_detected": 0, "faults_inconclusive": 0, "fixed": 0, "errors": 0}
        for (raw,) in rows:
            s = json.loads(raw); agg["sessions"] += 1
            sts = [r["cases"][0]["status"] for r in s.get("reports", []) if r.get("cases")]
            first = sts[0] if sts else None
            if sts: agg["checked"] += 1
            if s["state"] == "failed": agg["errors"] += 1
            if s["mode"] == "agent" and first:
                agg["agent_passed" if first == "correct" else "agent_failed" if first == "incorrect" else "agent_inconclusive"] += 1
            if s["mode"] == "verifier_test" and first:
                agg["faults_injected"] += 1
                if first == "incorrect": agg["faults_detected"] += 1
                elif first != "correct": agg["faults_inconclusive"] += 1
            if s["state"] == "fixed": agg["fixed"] += 1
            if len(items) < 8:
                items.append({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(s["created"])), "mode": s["mode"],
                              "scenario": SCENARIOS[s["scenario"]][0], "first": first, "last": sts[-1] if sts else None,
                              "state": s["state"]})
        return {**agg, "recent": items}

    # ---- public view ----
    def view(self, sid: str) -> dict[str, Any]:
        s = self._load(sid)
        title, text, _ = SCENARIOS[s["scenario"]]
        out: dict[str, Any] = {"session_id": s["id"], "mode": s["mode"], "state": s["state"], "error": s["error"],
                               "scenario": {"key": s["scenario"], "title": title, "text": text},
                               "case_label": _mask(s["case_id"]) if s["case_id"] else None,
                               "claims": _mask(s["claims"]) if s["claims"] else None, "checks": s["checks"],
                               "reports": [], "finding": None}
        for rep in s["reports"]:
            r = mask_report(rep); row = r["cases"][0]
            sev = finding_severity(row["failed_checks"], rep["policy"]) if row["failed_checks"] else None
            out["reports"].append({"report": r, "decision": {"accepted": row["status"] == "correct", "status": row["status"], "severity": sev}})
        if s["finding"]:
            f = s["finding"]
            out["finding"] = {"finding_id": f["finding_id"], "state": f["state"], "severity": f["severity"],
                              "events": [{"type": e["type"], "actor": e["actor"], "at": e["at"], "note": e["note"]} for e in f["events"]]}
        return out
