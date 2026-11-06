"""Synthetic demonstration: public, in-memory, evaluated by the real audit engine."""
from fastapi.testclient import TestClient

from audit.demo import build_demo
from web.app.main import app


def test_demo_population_is_labeled_and_counts_add_up():
    d = build_demo()
    t = d["totals"]
    assert d["synthetic"] is True and "Synthetic" in d["label"]
    assert t["evaluated"] == len(d["cases"]) == d["agent_reported"] == 20
    assert t["correct"] + t["incorrect"] + t["inconclusive"] == 20
    assert d["outcome_rate"] == round(t["correct"] / 20, 4)
    assert all(c["case_id"].startswith("500SYN") for c in d["cases"])


def test_failures_show_expected_vs_found_and_inconclusive_never_counts_as_correct():
    d = build_demo()
    empty = next(c for c in d["cases"] if "reason was not recorded" in c["finding"])
    row = next(k for k in empty["checks"] if k["check_id"] == "chk_reason_filled")
    assert (row["status"], row["found"]) == ("failed", "Empty")
    dup = next(c for c in d["cases"] if "2 follow-up Tasks" in c["finding"])
    assert next(k for k in dup["checks"] if k["check_id"] == "chk_followup_task")["found"] == "2 follow-up Tasks"
    unread = [c for c in d["cases"] if c["status"] == "inconclusive"]
    assert len(unread) == 1 and d["totals"]["correct"] == 13


def test_unauditable_checks_are_listed_not_passed():
    d = build_demo()
    assert {x["check_id"] for x in d["not_auditable"]} == {"chk_reason_matches", "chk_owner_unchanged", "chk_no_unexpected"}
    assert all(k["check_id"] not in {x["check_id"] for x in d["not_auditable"]} for c in d["cases"] for k in c["checks"])


def test_demo_endpoint_is_public_and_needs_no_token(monkeypatch):
    monkeypatch.setenv("ACTION_GUARD_API_TOKEN", "t" * 40)
    r = TestClient(app).get("/api/demo/audit")
    assert r.status_code == 200 and r.json()["synthetic"] is True
