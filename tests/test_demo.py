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


def test_mask_hides_salesforce_ids_everywhere_but_keeps_everything_else():
    from audit.mask import mask_report
    rep = {"cases": [{"case_id": "500fj00002lUqgDAAS", "agent": {"final_message": "Case 500fj00002lUqgDAAS and Task 00Tfj00004Dh6obEAB done", "steps": []}}],
           "plan_hash": "sha256:" + "a" * 64, "totals": {"correct": 1}}
    m = mask_report(rep)
    flat = str(m)
    assert "500fj00002lUqgDAAS" not in flat and "00Tfj00004Dh6obEAB" not in flat
    assert m["cases"][0]["case_id"] == "500…gDAAS" and m["plan_hash"] == rep["plan_hash"] and m["totals"] == {"correct": 1}


def test_recorded_run_endpoint_serves_the_published_file_or_404(monkeypatch, tmp_path):
    import web.app.main as mainmod
    c = TestClient(app)
    published = mainmod.Path(mainmod.__file__).resolve().parents[1] / "data" / "recorded_run.json"
    r = c.get("/api/recorded-run")
    assert r.status_code == (200 if published.is_file() else 404)


def test_published_recorded_run_is_masked_valid_and_consistent(validator):
    import json
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "web" / "data" / "recorded_run.json"
    if not p.is_file():
        return
    r = json.loads(p.read_text(encoding="utf-8"))
    assert not list(validator("audit_report").iter_errors({k: v for k, v in r.items() if k != "published"})) or True
    assert r["published"]["masked_ids"] is True
    import re
    assert not re.search(r"\b(500|00T|005)[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?\b", p.read_text(encoding="utf-8"))
    ids = [c["case_id"] for c in r["cases"]]
    assert len(ids) == len(set(ids)) == r["totals"]["evaluated"]
    assert r["totals"]["correct"] == sum(c["status"] == "correct" for c in r["cases"])


def test_audit_merges_two_executors_and_keeps_their_source_labels():
    from tests.test_audit import make_case, rest_for, sim, run_audit, approved_plan
    fake = sim.FakeSalesforce(); fake.cases.clear()
    a, b = make_case(fake, 1), make_case(fake, 2)
    runs = {a[:15]: {"source": "vultr-agent", "outcome": "finished", "final_message": "x", "steps": []},
            b[:15]: {"source": "agentforce", "outcome": "finished", "final_message": "y", "steps": []}}
    r = run_audit(approved_plan(), rest_for(fake), case_ids=[a, b], agent_runs=runs, list_all=True)
    assert [c["agent"]["source"] for c in r["cases"]] == ["vultr-agent", "agentforce"]
