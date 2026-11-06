"""Evidencia duravel: um JSON por etapa, gravado de forma atomica assim que existe."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class EvidenceStore:
    def __init__(self, base_dir: str | Path, run_id: str):
        if "/" in run_id or ".." in run_id:
            raise ValueError("invalid run_id")
        self.dir = Path(base_dir) / run_id
        self.dir.mkdir(parents=True, exist_ok=True)

    def save(self, name: str, data: Any) -> Path:
        target = self.dir / f"{name}.json"
        tmp = self.dir / f".{name}.json.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
        return target
