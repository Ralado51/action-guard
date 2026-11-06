"""Guarded Salesforce tools. Two separate writes (close, create task); one read.

Safety rules enforced HERE, not in the prompt:
- only Case Ids in the authorized allowlist can be touched (15/18-char safe);
- the Case must carry the synthetic marker in its Subject, or nothing is written;
- a write whose outcome is uncertain (timeout) is never repeated: the run stops;
- a hard cap on writes per run.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from connector.ids import key15
from connector.rest import QueryError, SalesforceRest

MARKER = "[SYNTHETIC]"
ID_RE = re.compile(r"[A-Za-z0-9]{15}([A-Za-z0-9]{3})?")
REASONS = ("Resolved - Customer confirmed", "Resolved - Guidance provided", "Duplicate", "Cancelled")


class ToolRefused(Exception):
    """The guard blocked the call before anything was sent."""


class UncertainWrite(Exception):
    """A write may or may not have happened. The run must stop; a human reconciles."""


def _uncertain(e: Exception) -> bool:
    m = str(e)
    return "timeout" in m or "network" in m or "(HTTP 5" in m


@dataclass
class Guard:
    authorized: frozenset[str]            # key15 of the Case Ids this run may touch
    max_writes: int = 4
    writes: int = 0

    def check_case(self, case_id: Any) -> str:
        if not isinstance(case_id, str) or not ID_RE.fullmatch(case_id):
            raise ToolRefused("case_id must be a 15- or 18-character Salesforce Id.")
        if key15(case_id) not in self.authorized:
            raise ToolRefused("This Case is not in the list authorized for this run.")
        return case_id

    def take_write(self) -> None:
        if self.writes >= self.max_writes:
            raise ToolRefused("Write limit for this run reached.")
        self.writes += 1


@dataclass
class SalesforceTools:
    rest: SalesforceRest
    guard: Guard
    closed_fields: dict[str, Any] = field(default_factory=dict)

    def read_case(self, case_id: str) -> dict[str, Any]:
        cid = self.guard.check_case(case_id)
        rows = self.rest.query(f"SELECT Status, Closure_Reason__c, Subject FROM Case WHERE Id = '{cid}'")
        if not rows:
            return {"found": False}
        r = rows[0]
        tasks = self.rest.query(f"SELECT Subject FROM Task WHERE WhatId = '{cid}'")
        return {"found": True, "status": r.get("Status"), "closure_reason": r.get("Closure_Reason__c"),
                "linked_task_subjects": [t.get("Subject") for t in tasks]}

    def _assert_synthetic(self, cid: str) -> None:
        rows = self.rest.query(f"SELECT Subject, IsClosed FROM Case WHERE Id = '{cid}'")
        if not rows:
            raise ToolRefused("Case not found.")
        if not str(rows[0].get("Subject") or "").startswith(MARKER):
            raise ToolRefused("Refused: the Case is not marked as synthetic.")

    def close_case(self, case_id: str, closure_reason: str) -> dict[str, Any]:
        cid = self.guard.check_case(case_id)
        if closure_reason not in REASONS:
            raise ToolRefused("closure_reason must be one of: " + "; ".join(REASONS))
        self._assert_synthetic(cid)
        self.guard.take_write()
        try:
            self.rest.update("Case", cid, {"Status": "Closed", "Closure_Reason__c": closure_reason})
        except QueryError as e:
            if _uncertain(e):
                raise UncertainWrite(f"close_case outcome unknown: {e}") from None
            return {"ok": False, "error": str(e)}
        return {"ok": True}

    def create_followup_task(self, case_id: str, subject: str) -> dict[str, Any]:
        cid = self.guard.check_case(case_id)
        if not isinstance(subject, str) or not subject.strip() or len(subject) > 120:
            raise ToolRefused("subject must be a non-empty string up to 120 characters.")
        self._assert_synthetic(cid)
        self.guard.take_write()
        try:
            task_id = self.rest.create("Task", {"Subject": subject.strip(), "WhatId": cid})
        except QueryError as e:
            if _uncertain(e):
                raise UncertainWrite(f"create_followup_task outcome unknown: {e}") from None
            return {"ok": False, "error": str(e)}
        return {"ok": True, "task_id": task_id}
