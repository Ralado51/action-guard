"""Evidence dossier for one finding: a single JSON bundle with a manifest of SHA-256 hashes.

What the hashes give: anyone can recompute them and see that the files are the ones listed in the manifest.
What they do NOT give: proof of who produced the bundle, or protection if the whole bundle (manifest included) is
replaced. A signature would be needed for that; this prototype does not claim one.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from audit.mask import mask_report, mask_text

from .findings import FindingStore, report_hash, sha, canonical
import json

NOTE = ("Integrity check only: the hashes show the files match this manifest. They do not prove who produced the bundle "
        "or stop someone replacing the whole bundle.")


def _masked(obj: Any) -> Any:
    return json.loads(mask_text(json.dumps(obj, ensure_ascii=False)))


def build_bundle(store: FindingStore, finding_id: str, reports: list[dict[str, Any]], *, mask: bool = False) -> dict[str, Any]:
    state = store.state(finding_id)
    needed = {state["opened_audit_id"]} | {e["data"]["audit_id"] for e in state["events"] if e["type"] == "revalidated"}
    by_id = {r["audit_id"]: r for r in reports}
    missing = needed - set(by_id)
    if missing:
        raise ValueError("Missing audit report(s): " + ", ".join(sorted(missing)))
    recorded = {}
    for e in state["events"]:
        if e["type"] in ("opened", "revalidated"):
            recorded[e["data"]["audit_id"]] = e["data"].get("report_hash")
    for aid in sorted(needed):
        if report_hash(by_id[aid]) != recorded.get(aid):
            raise ValueError(f"Report {aid} does not match the hash recorded in the finding's event; refusing to export.")
    files: dict[str, Any] = {}
    masking: dict[str, dict[str, str]] = {}
    for aid in sorted(needed):
        rep = by_id[aid]
        if mask:
            masked = mask_report(rep)
            masking[aid] = {"original_sha256": report_hash(rep), "masked_sha256": sha(masked)}
            rep = masked
        files["report:" + aid] = rep
    files["finding"] = _masked(state) if mask else state
    manifest = {"algorithm": "sha256 of canonical JSON (sorted keys, no spaces, integral floats as integers)",
                "files": {k: sha(v) for k, v in sorted(files.items())},
                "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "masked": mask, "note": NOTE}
    if mask:
        manifest["masking"] = masking
    manifest["manifest_sha256"] = sha({"files": manifest["files"], "masked": mask})
    return {"kind": "action-guard-dossier", "version": 1, "files": files, "manifest": manifest}


def verify_bundle(bundle: dict[str, Any]) -> list[str]:
    """Returns a list of problems; empty means the bundle matches its manifest and is internally consistent."""
    problems: list[str] = []
    m, files = bundle.get("manifest", {}), bundle.get("files", {})
    if set(m.get("files", {})) != set(files):
        problems.append("The manifest and the files list different entries.")
    for k, v in files.items():
        if m.get("files", {}).get(k) != sha(v):
            problems.append(f"Hash mismatch: {k}")
    if m.get("manifest_sha256") != sha({"files": m.get("files", {}), "masked": m.get("masked", False)}):
        problems.append("Manifest hash mismatch.")
    finding = files.get("finding")
    if finding:
        events = finding.get("events", [])
        opened = events[0]["data"] if events else {}
        if "report:" + str(opened.get("audit_id")) not in files:
            problems.append("The report that opened the finding is missing.")
        for e in events:
            if e["type"] == "revalidated" and "report:" + e["data"]["audit_id"] not in files:
                problems.append("A revalidation report is missing.")
        if m.get("masked"):
            for e in events:
                aid = e["data"].get("audit_id") if e["type"] in ("opened", "revalidated") else None
                info = m.get("masking", {}).get(aid) if aid else None
                if aid and "report:" + aid in files:
                    if not info or info.get("original_sha256") != e["data"].get("report_hash"):
                        problems.append(f"Event {e['seq']}: the original report hash in the masking record does not match the event.")
                    elif info.get("masked_sha256") != sha(files["report:" + aid]):
                        problems.append(f"Masked report {aid} does not match its masking record.")
        else:
            for e in events:
                aid = e["data"].get("audit_id") if e["type"] in ("opened", "revalidated") else None
                if aid and "report:" + aid in files and e["data"].get("report_hash") != sha(files["report:" + aid]):
                    problems.append(f"Event {e['seq']} refers to a different version of its report.")
    return problems
