"""Prepare a real audit report for public display: Salesforce Ids are masked, nothing else is altered."""
from __future__ import annotations

import json
import re
from typing import Any

SFID = re.compile(r"\b(500|00T|005)[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?\b")


def _mask_id(m: re.Match[str]) -> str:
    s = m.group(0)
    return s[:3] + "…" + s[-5:]


def mask_text(text: str) -> str:
    return SFID.sub(_mask_id, text)


def mask_report(report: dict[str, Any]) -> dict[str, Any]:
    out = json.loads(mask_text(json.dumps(report, ensure_ascii=False)))
    out["published"] = {"masked_ids": True,
                        "note": "Salesforce record Ids are masked; every other value is as recorded."}
    return out
