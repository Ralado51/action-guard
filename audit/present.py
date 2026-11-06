"""Plain-language expected/found rows for a checked record. Presentation only: never decides a verdict."""
from __future__ import annotations

from typing import Any

from .evaluate import FAILED, INCONCLUSIVE


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def expected_text(check: dict[str, Any]) -> str:
    if check["kind"] == "record_created":
        return _plural(check.get("expected_count", 1), f"matching {check['object']}")
    if check["kind"] == "field_not_empty":
        return "A value is recorded"
    return str(check["expected"])


def check_view(check: dict[str, Any], result: dict[str, Any], row: dict[str, Any] | None) -> dict[str, Any]:
    ev, status = result["evidence"], result["status"]
    if status == INCONCLUSIVE:
        found = "Could not be read"
    elif check["kind"] == "record_created":
        found = _plural(ev.get("matching", 0), f"matching {check['object']}")
    elif check["kind"] == "field_not_empty":
        v = ev.get("observed") if status == FAILED else (row or {}).get(check["field"])
        found = "Empty" if v in (None, "") else ("A value is recorded" if row is None else str(v))
    else:
        v = ev.get("observed") if status == FAILED else check["expected"]
        found = "Empty" if v in (None, "") else str(v)
    return {"check_id": check["check_id"], "description": check.get("description", check["check_id"]),
            "status": status, "expected": expected_text(check), "found": found}
