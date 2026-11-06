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
    assert next(k for k in dup["checks"] if k["check_id"] == "chk_followup_task")["found"] == "2 matching Tasks"
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


def test_real_audit_report_carries_expected_and_found_per_check(tmp_path):
    from tests.test_audit import make_case, rest_for, sim, run_audit, approved_plan
    fake = sim.FakeSalesforce(); fake.cases.clear()
    ids = [make_case(fake, 1, reason=None), make_case(fake, 2, tasks=2)]
    r = run_audit(approved_plan(), rest_for(fake), case_ids=ids)
    by = {c["case_id"]: {k["check_id"]: k for k in c["checks"]} for c in r["cases"]}
    empty = by[ids[0]]["chk_reason_filled"] if "chk_reason_filled" in by[ids[0]] else next(k for k in by[ids[0]].values() if k["status"] == "failed")
    assert empty["status"] == "failed" and empty["found"] == "Empty" and empty["expected"] == "A value is recorded"
    dup = next(k for k in by[ids[1]].values() if k["status"] == "failed")
    assert dup["expected"] == "1 matching Task" and dup["found"] == "2 matching Tasks"


def test_audit_can_list_all_cases_and_attach_the_agents_own_account(validator):
    from tests.test_audit import make_case, rest_for, sim, run_audit, approved_plan
    fake = sim.FakeSalesforce(); fake.cases.clear()
    ids = [make_case(fake, 1), make_case(fake, 2, reason=None)]
    runs = {ids[1][:15]: {"outcome": "finished", "final_message": "Closed it and added the task.",
                          "steps": [{"at": "2026-11-06T14:00:00Z", "tool": "close_case", "result": "{\"ok\": true}"}]}}
    r = run_audit(approved_plan(), rest_for(fake), case_ids=ids, list_all=True, agent_runs=runs)
    assert not list(validator("audit_report").iter_errors(r))
    assert r["all_cases_listed"] is True and [c["status"] for c in r["cases"]] == ["correct", "incorrect"]
    assert r["cases"][1]["agent"]["final_message"].startswith("Closed it") and "agent" not in r["cases"][0]
    assert r["totals"]["correct"] == 1
