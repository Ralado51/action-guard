"""Findings lifecycle, policy severity and dossier integrity (simulated Salesforce, no network)."""
import json
import re

import pytest

from acceptance.dossier import build_bundle, verify_bundle
from acceptance.findings import FindingError, FindingStore, canonical
from audit.run import run_audit
from tests.test_audit import approved_plan, make_case, rest_for, sim


def make_report(fake, ids, at):
    return run_audit(approved_plan(), rest_for(fake), case_ids=ids, list_all=True, now=lambda: at)


class Clock:
    def __init__(self): self.n = 0
    def __call__(self):
        self.n += 1
        return f"2026-11-06T1{self.n // 10}:{self.n % 10}0:00Z"


@pytest.fixture
def world(tmp_path):
    fake = sim.FakeSalesforce(); fake.cases.clear()
    good = make_case(fake, 1)
    noreason = make_case(fake, 2, reason=None)
    notask = make_case(fake, 3, tasks=0)
    first = make_report(fake, [good, noreason, notask], "2026-11-06T09:00:00Z")
    store = FindingStore(tmp_path / "f", clock=lambda: "2026-11-06T10:00:00Z")
    return fake, store, first, {"good": good, "noreason": noreason, "notask": notask}


def fix_noreason(fake, ids):
    fake.cases[ids["noreason"]]["Closure_Reason__c"] = "Resolved - Guidance provided"


def test_report_carries_policy_with_severity_and_unobserved_conditions(world):
    _, _, rep, _ = world
    p = rep["policy"]
    sev = {c["check_id"]: (c["severity"], c["observed"]) for c in p["conditions"]}
    assert sev["chk_reason_filled"] == ("critical", True) and sev["chk_followup_task"] == ("operational", True)
    assert sev["chk_owner_unchanged"] == ("critical", False)          # critical and NOT observed stays visible
    assert p["critical_observed"] < p["critical_total"]


def test_findings_open_only_for_divergences_with_severity(world):
    _, store, rep, ids = world
    opened = store.open_from_report(rep, "Lead")
    states = {s["case_id"]: s for s in store.list()}
    assert len(opened) == 2 and states[ids["noreason"]]["severity"] == "critical" and states[ids["notask"]]["severity"] == "operational"
    assert store.open_from_report(rep, "Lead") == []                  # idempotent while open


def test_cannot_close_without_a_passing_revalidation(world):
    fake, store, rep, ids = world
    store.open_from_report(rep, "Lead")
    fid = next(s["finding_id"] for s in store.list() if s["case_id"] == ids["noreason"])
    with pytest.raises(FindingError, match="Only a passing revalidation"):
        store.close(fid, "Lead")
    with pytest.raises(FindingError, match="Record the correction"):
        store.revalidate(fid, "Analyst", rep)


def test_full_cycle_detect_assign_fix_revalidate_close_keeps_history(world):
    fake, store, rep, ids = world
    store.open_from_report(rep, "Lead")
    fid = next(s["finding_id"] for s in store.list() if s["case_id"] == ids["noreason"])
    store.assign(fid, "Lead", "Analyst")
    store.record_fix(fid, "Analyst", "Flow now sets the closure reason")
    fix_noreason(fake, ids)
    again = make_report(fake, [ids["noreason"]], "2026-11-06T11:00:00Z")
    assert store.revalidate(fid, "Analyst", again) is True
    store.close(fid, "Lead")
    s = store.state(fid)
    assert s["state"] == "closed" and [e["type"] for e in s["events"]] == ["opened", "assigned", "fix_recorded", "revalidated", "closed"]
    assert s["events"][0]["data"]["failed_checks"] == ["chk_reason_filled"]      # the original failure stays on record
    with pytest.raises(FindingError, match="already closed"):
        store.assign(fid, "Lead", "Someone")


def test_revalidation_rules_same_plan_new_audit_after_the_fix(world):
    fake, store, rep, ids = world
    store.open_from_report(rep, "Lead")
    fid = next(s["finding_id"] for s in store.list() if s["case_id"] == ids["noreason"])
    store.record_fix(fid, "Analyst", "Flow now sets the closure reason")
    with pytest.raises(FindingError, match="not the one that found"):
        store.revalidate(fid, "Analyst", rep)
    old = make_report(fake, [ids["noreason"]], "2026-11-06T09:30:00Z")          # before the fix (10:00)
    with pytest.raises(FindingError, match="predates"):
        store.revalidate(fid, "Analyst", old)
    other = dict(make_report(fake, [ids["noreason"]], "2026-11-06T11:00:00Z"), plan_hash="sha256:" + "0" * 64)
    with pytest.raises(FindingError, match="different plan"):
        store.revalidate(fid, "Analyst", other)


def test_failed_revalidation_does_not_allow_closing(world):
    fake, store, rep, ids = world
    store.open_from_report(rep, "Lead")
    fid = next(s["finding_id"] for s in store.list() if s["case_id"] == ids["noreason"])
    store.record_fix(fid, "Analyst", "Believed fixed but the Flow was not")
    later = make_report(fake, [ids["noreason"]], "2026-11-06T11:00:00Z")        # still empty
    assert store.revalidate(fid, "Analyst", later) is False
    assert store.state(fid)["state"] == "revalidation_failed"
    with pytest.raises(FindingError):
        store.close(fid, "Lead")


def test_risk_acceptance_needs_justification_and_stays_unresolved(world):
    _, store, rep, ids = world
    store.open_from_report(rep, "Lead")
    fid = next(s["finding_id"] for s in store.list() if s["case_id"] == ids["notask"])
    with pytest.raises(FindingError, match="justification"):
        store.accept_risk(fid, "Director", "ok")
    store.accept_risk(fid, "Director", "Low impact, the Task is created manually by the team this quarter.")
    s = store.state(fid)
    assert s["state"] == "risk_accepted" and s["events"][-1]["data"]["unresolved"] is True and s["events"][-1]["actor"] == "Director"


def test_dossier_verifies_and_detects_any_tampering(world):
    fake, store, rep, ids = world
    store.open_from_report(rep, "Lead")
    fid = next(s["finding_id"] for s in store.list() if s["case_id"] == ids["noreason"])
    b = build_bundle(store, fid, [rep])
    assert verify_bundle(b) == []
    t = json.loads(json.dumps(b)); t["files"]["finding"]["case_id"] = "500000000000000AAA"
    assert any("Hash mismatch" in p for p in verify_bundle(t))
    t2 = json.loads(json.dumps(b)); k = next(k for k in t2["files"] if k.startswith("report:")); t2["files"][k]["totals"]["correct"] = 99
    assert verify_bundle(t2)
    t3 = json.loads(json.dumps(b)); t3["manifest"]["manifest_sha256"] = "sha256:" + "1" * 64
    assert any("Manifest" in p for p in verify_bundle(t3))


def test_masked_dossier_hides_ids_and_still_verifies(world):
    _, store, rep, ids = world
    store.open_from_report(rep, "Lead")
    fid = next(s["finding_id"] for s in store.list() if s["case_id"] == ids["noreason"])
    b = build_bundle(store, fid, [rep], mask=True)
    assert verify_bundle(b) == [] and not re.search(r"\b500[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?\b", json.dumps(b))
    assert b["manifest"]["masking"]


def test_canonical_json_is_browser_compatible_for_integral_floats():
    assert canonical({"b": 1.0, "a": [0.6667, "é"]}) == '{"a":[0.6667,"é"],"b":1}'
