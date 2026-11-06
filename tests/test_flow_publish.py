"""Publishing the recorded acceptance flow and serving it."""
import json

import pytest
from fastapi.testclient import TestClient

from acceptance.__main__ import main as acc
from acceptance.dossier import build_bundle
from tests.test_acceptance import fix_noreason, make_report, world  # noqa: F401


def flow_for(world, tmp_path):
    fake, store, rep, ids = world
    store.open_from_report(rep, "Lead")
    fid = next(s["finding_id"] for s in store.list() if s["case_id"] == ids["noreason"])
    store.assign(fid, "Lead", "Analyst"); store.record_fix(fid, "Analyst", "Closure reason set by hand in the org")
    fix_noreason(fake, ids)
    new = make_report(fake, [ids["noreason"]], "2026-11-06T11:00:00Z")
    store.revalidate(fid, "Analyst", new); store.close(fid, "Lead")
    b = build_bundle(store, fid, [rep, new], mask=True)
    bp = tmp_path / "b.json"; bp.write_text(json.dumps(b))
    cal = {"audit_id": "a", "audited_at": "2026-11-06T09:00:00Z", "plan_hash": "x", "injected": 1, "detected": 1, "missed": 0,
           "controls": 1, "false_alarms": 0, "cases": []}
    cp = tmp_path / "c.json"; cp.write_text(json.dumps(cal))
    return bp, cp, b


def test_publish_only_verified_masked_bundles(world, tmp_path):
    bp, cp, b = flow_for(world, tmp_path)
    out = tmp_path / "flow.json"
    assert acc(["publish", "--calibration", str(cp), "--bundle", str(bp), "--out", str(out)]) == 0
    flow = json.loads(out.read_text())
    assert len(flow["bundles"]) == 1 and flow["calibration"]["injected"] == 1
    t = json.loads(bp.read_text()); t["files"]["finding"]["state"] = "open"
    tp = tmp_path / "t.json"; tp.write_text(json.dumps(t))
    assert acc(["publish", "--calibration", str(cp), "--bundle", str(tp), "--out", str(tmp_path / "x.json")]) == 1
    unmasked = tmp_path / "u.json"
    u = json.loads(bp.read_text()); u["manifest"]["masked"] = False; unmasked.write_text(json.dumps(u))
    assert acc(["publish", "--calibration", str(cp), "--bundle", str(unmasked), "--out", str(tmp_path / "y.json")]) == 1


def test_recorded_flow_endpoint(tmp_path, monkeypatch):
    from web.app import main as m
    monkeypatch.setattr(m, "FLOW_PATH", tmp_path / "none.json", raising=False)
    c = TestClient(m.app)
    assert c.get("/api/recorded-flow").status_code == 404
    p = tmp_path / "f.json"; p.write_text('{"calibration":null,"bundles":[]}')
    monkeypatch.setattr(m, "FLOW_PATH", p, raising=False)
    assert c.get("/api/recorded-flow").json() == {"calibration": None, "bundles": []}


def test_committed_recorded_flow_verifies_and_has_no_salesforce_ids():
    import re
    from pathlib import Path
    from acceptance.dossier import verify_bundle
    p = Path(__file__).resolve().parents[1] / "web" / "data" / "recorded_flow.json"
    raw = p.read_text(encoding="utf-8")
    assert not re.search(r"\b500[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?\b", raw)
    d = json.loads(raw)
    assert d["calibration"]["detected"] == d["calibration"]["injected"] and d["bundles"]
    assert all(verify_bundle(b) == [] and b["manifest"]["masked"] for b in d["bundles"])
