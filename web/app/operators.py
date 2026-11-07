"""Operator registry: named operators with personal keys, so plan approvals carry a server-verified name.

The shared ACTION_GUARD_API_TOKEN stays the admin credential: it is the only way to register or revoke an operator.
Keys are random, shown once, stored only as a sha256 hash. The public list never contains keys or hashes.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any

ROLES = ("operator", "reviewer")
MAX_OPERATORS = 25
NAME = re.compile(r"^[\w][\w .'\-]{1,59}$", re.UNICODE)
PREFIX = "agk_"


class OperatorError(Exception):
    def __init__(self, code: int, message: str):
        self.code, self.message = code, message


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8", "replace")).hexdigest()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class OperatorRegistry:
    def __init__(self, root):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "operators.sqlite3"
        with self._c() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS operators (id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
                key_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, last_seen TEXT, active INTEGER NOT NULL DEFAULT 1)""")
        try:
            self.db.chmod(0o600)
        except OSError:
            pass

    def _c(self):
        db = sqlite3.connect(self.db, timeout=10); db.row_factory = sqlite3.Row; return db

    def create(self, name: str, role: str) -> tuple[dict[str, Any], str]:
        name = (name or "").strip()
        if not NAME.fullmatch(name):
            raise OperatorError(422, "Use a name of 2 to 60 characters: letters, numbers, spaces, dots, hyphens.")
        if role not in ROLES:
            raise OperatorError(422, "Role must be operator or reviewer.")
        with self._c() as db:
            if db.execute("SELECT COUNT(*) FROM operators WHERE active=1").fetchone()[0] >= MAX_OPERATORS:
                raise OperatorError(409, "The registry is full. Revoke an operator first.")
            if db.execute("SELECT 1 FROM operators WHERE active=1 AND lower(name)=lower(?)", (name,)).fetchone():
                raise OperatorError(409, "An active operator already has this name.")
            key = PREFIX + secrets.token_urlsafe(24)
            oid = "op_" + secrets.token_hex(4)
            db.execute("INSERT INTO operators (id,name,role,key_hash,created_at) VALUES (?,?,?,?,?)", (oid, name, role, _hash(key), _now()))
        return self._public(oid), key

    def lookup(self, key: str) -> dict[str, Any] | None:
        if not key.startswith(PREFIX) or len(key) > 200:
            return None
        h = _hash(key)
        with self._c() as db:
            row = db.execute("SELECT id,key_hash FROM operators WHERE key_hash=? AND active=1", (h,)).fetchone()
            if not row or not hmac.compare_digest(row["key_hash"], h):
                return None
            db.execute("UPDATE operators SET last_seen=? WHERE id=?", (_now(), row["id"]))
        return self._public(row["id"])

    def revoke(self, oid: str) -> None:
        with self._c() as db:
            if db.execute("UPDATE operators SET active=0 WHERE id=? AND active=1", (oid,)).rowcount != 1:
                raise OperatorError(404, "No such active operator.")

    def _public(self, oid: str) -> dict[str, Any]:
        with self._c() as db:
            r = db.execute("SELECT id,name,role,created_at,last_seen FROM operators WHERE id=?", (oid,)).fetchone()
        return {"id": r["id"], "name": r["name"], "role": r["role"], "created_at": r["created_at"], "last_seen": r["last_seen"]}

    def list_public(self) -> list[dict[str, Any]]:
        with self._c() as db:
            ids = [r["id"] for r in db.execute("SELECT id FROM operators WHERE active=1 ORDER BY created_at")]
        return [self._public(i) for i in ids]
