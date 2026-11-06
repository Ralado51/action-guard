"""Persistent, append-only reservation ledger for runs that write to Salesforce.

A Case is reserved BEFORE anything is sent. Any later attempt for the same Case is refused, whatever the outcome
(finished, uncertain, crashed): re-sending could duplicate Tasks. To try a Case again, a human reconciles it in
Salesforce and uses a new Case. The ledger sits next to authorized.json and is shared by every executor.
"""
from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .ids import key15


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Ledger:
    def __init__(self, directory: str | os.PathLike):
        self.dir = Path(directory)
        self.path = self.dir / "ledger.jsonl"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        os.chmod(self.path, 0o600)

    def _append(self, fh, entry: dict) -> None:
        fh.write(json.dumps(entry) + "\n")
        fh.flush()
        os.fsync(fh.fileno())

    def _seen(self, fh) -> dict[str, dict]:
        fh.seek(0)
        out: dict[str, dict] = {}
        for line in fh:
            line = line.strip()
            if line:
                e = json.loads(line)
                out.setdefault(e["case"], e)
        return out

    def import_existing(self) -> int:
        """Cases already handled by earlier runs (evidence files <run-dir>/<case15>.json) count as reserved."""
        n = 0
        with open(self.path, "a+", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            seen = self._seen(fh)
            for f in sorted(self.dir.glob("*-run-*/*.json")):
                k = f.stem
                if len(k) == 15 and k not in seen:
                    self._append(fh, {"case": k, "executor": f.parent.name.split("-run-")[0], "state": "imported",
                                      "at": _now()})
                    seen[k] = {}
                    n += 1
        return n

    def reserve(self, case_id: str, executor: str) -> bool:
        k = key15(case_id)
        with open(self.path, "a+", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            if k in self._seen(fh):
                return False
            self._append(fh, {"case": k, "executor": executor, "state": "reserved", "at": _now()})
            return True

    def record(self, case_id: str, executor: str, state: str) -> None:
        with open(self.path, "a", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            self._append(fh, {"case": key15(case_id), "executor": executor, "state": state, "at": _now(), "update": True})
