"""Controlled live demo against a simulated org and a scripted agent. No network, no real writes."""
import json
import re

import pytest
from fastapi.testclient import TestClient

from connector.ids import key15
from connector.rest import QueryError
from vultr_agent.agent import FOLLOWUP_SUBJECT
from vultr_agent.tools import Guard, SalesforceTools
from web.app import main as m
from web.app.live import LiveConfig, LiveDemo
from tests.test_audit import approved_plan
from tests.test_calibration import Org, client

CODE = "judge-code-123"
IDS = re.compile(r"\b500[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?\b")


class Clock:
    def __init__(self): self.t = 1_000_000.0
    def __call__(self): return self.t


def scripted_agent(calls, outcome="finished", skip_reason=False):
    def run(rest, case_id, reason):
        calls.append(case_id)
        tools = SalesforceTools(rest, Guard(frozenset({key15(case_id)}), max_writes=3))
        steps = [{"n": 1, "at": "2026-11-06T18:00:00Z", "request": {"tool": "create_followup_task"}, "result": tools.create_followup_task(case_id, FOLLOWUP_SUBJECT)}]
        if outcome == "finished":
            steps.append({"n": 2, "at": "2026-11-06T18:00:01Z", "request": {"tool": "close_case"}, "result": tools.close_case(case_id, reason)})
            steps.append({"n": 3, "at": "2026-11-06T18:00:02Z", "final": True})
        return {"source": "vultr-agent", "outcome": outcome, "final_message": f"Closed {case_id} and created the follow-up Task.", "steps": steps, "writes": 2}
    return run


@pytest.fixture
def env(tmp_path):
    plan = tmp_path / "plan.json"; plan.write_text(json.dumps(approved_plan()))
    org, clock, calls = Org(), Clock(), []
    cfg = LiveConfig(True, None, CODE, daily=3, hourly=2, plan_file=str(plan))
    demo = LiveDemo(tmp_path / "live", cfg, rest_factory=lambda: client(org), agent_runner=scripted_agent(calls), clock=clock)
    m.app.dependency_overrides[m.live_demo] = lambda: demo
    yield demo, org, clock, calls, TestClient(m.app), cfg, tmp_path
    m.app.dependency_overrides.clear()


def start(c, mode="agent", scenario="wrong_item", code=CODE):
    return c.post("/api/live/sessions", json={"code": code, "scenario": scenario, "mode": mode})


def test_switched_off_by_default_and_misconfiguration_stays_off(tmp_path, monkeypatch):
    assert LiveConfig.from_env({}).enabled is False
    assert LiveConfig.from_env({"ACTION_GUARD_LIVE_DEMO": "on"}).reason == "misconfigured"
    plan = tmp_path / "p.json"; plan.write_text("{}")
    base = {"ACTION_GUARD_LIVE_DEMO": "on", "ACTION_GUARD_LIVE_CODE": "short", "ACTION_GUARD_LIVE_DAILY_LIMIT": "10", "ACTION_GUARD_LIVE_PLAN_FILE": str(plan)}
    assert LiveConfig.from_env(base).enabled is False                                   # code too short
    assert LiveConfig.from_env({**base, "ACTION_GUARD_LIVE_CODE": "long-enough-code", "ACTION_GUARD_LIVE_DAILY_LIMIT": "0"}).enabled is False
    assert LiveConfig.from_env({**base, "ACTION_GUARD_LIVE_CODE": "long-enough-code"}).enabled is True
    off = LiveDemo(tmp_path / "x", LiveConfig(False, "off"), rest_factory=lambda: 1 / 0)
    m.app.dependency_overrides[m.live_demo] = lambda: off
    try:
        c = TestClient(m.app)
        assert c.get("/api/live/status").json()["enabled"] is False
        assert start(c).status_code == 503
    finally:
        m.app.dependency_overrides.clear()


def test_wrong_code_writes_nothing_and_repeated_guessing_is_locked(env):
    demo, org, clock, calls, c, *_ = env
    assert start(c, code="wrong").status_code == 403 and org.writes == []
    for _ in range(25):
        start(c, code="wrong")
    assert start(c, code=CODE).status_code == 429 and org.writes == []


def test_browser_cannot_choose_ids_or_parameters(env):
    _, org, _, _, c, *_ = env
    r = c.post("/api/live/sessions", json={"code": CODE, "scenario": "wrong_item", "mode": "agent", "case_id": "500SYN000000001AAA"})
    assert r.status_code == 422
    assert start(c, scenario="anything").status_code == 422 and start(c, mode="x").status_code == 422
    assert org.writes == []


def test_agent_flow_runs_once_then_check_accepts_and_ids_are_masked(env):
    demo, org, _, calls, c, *_ = env
    s = start(c).json(); sid = s["session_id"]
    assert s["state"] == "created" and all(v["Subject"].startswith("[SYNTHETIC]") for v in org.cases.values())
    r1 = c.post(f"/api/live/sessions/{sid}/run").json(); r2 = c.post(f"/api/live/sessions/{sid}/run").json()
    assert len(calls) == 1 and r2["state"] == "agent_done"                                   # double click never re-runs
    v = c.get(f"/api/live/sessions/{sid}").json()
    assert v["claims"]["outcome"] == "finished" and v["claims"]["source"] == "vultr-agent"
    out = c.post(f"/api/live/sessions/{sid}/check").json()
    assert out["reports"][0]["decision"] == {"accepted": True, "status": "correct", "severity": None}
    assert not IDS.search(json.dumps(out)) and not IDS.search(json.dumps(v))


def test_uncertain_agent_result_blocks_repeat_but_allows_checking(env):
    demo, org, _, calls, c, *_ = env
    demo.agent_runner = scripted_agent(calls, outcome="uncertain_write")
    sid = start(c).json()["session_id"]; c.post(f"/api/live/sessions/{sid}/run")
    assert c.get(f"/api/live/sessions/{sid}").json()["state"] == "uncertain"
    c.post(f"/api/live/sessions/{sid}/run")
    assert len(calls) == 1
    out = c.post(f"/api/live/sessions/{sid}/check").json()
    assert out["reports"][0]["decision"]["accepted"] is False                                # closed? no: the audit reads the record


def test_verifier_test_detects_then_fix_revalidates_and_closes_with_history(env):
    demo, org, _, calls, c, *_ = env
    s = start(c, mode="verifier_test").json(); sid = s["session_id"]
    assert s["state"] == "agent_done" and s["claims"]["source"] == "controlled-fault" and calls == []
    chk = c.post(f"/api/live/sessions/{sid}/check").json()
    assert chk["reports"][0]["decision"] == {"accepted": False, "status": "incorrect", "severity": "critical"}
    fx = c.post(f"/api/live/sessions/{sid}/fix").json()
    assert [e["type"] for e in fx["finding"]["events"]] == ["opened", "assigned", "fix_recorded", "revalidated", "closed"]
    assert fx["finding"]["state"] == "closed" and len(fx["reports"]) == 2
    assert fx["reports"][0]["decision"]["accepted"] is False and fx["reports"][1]["decision"]["accepted"] is True   # history kept
    assert c.post(f"/api/live/sessions/{sid}/fix").status_code == 409
    assert not IDS.search(json.dumps(fx))


def test_fix_is_refused_for_agent_sessions_and_before_a_check(env):
    _, _, _, _, c, *_ = env
    a = start(c).json()["session_id"]; c.post(f"/api/live/sessions/{a}/run")
    assert c.post(f"/api/live/sessions/{a}/fix").status_code == 409
    v = start(c, mode="verifier_test").json()["session_id"]
    assert c.post(f"/api/live/sessions/{v}/fix").status_code == 409                            # needs a failing check first


def test_limits_count_started_sessions_including_failed_and_survive_restart(env):
    demo, org, clock, calls, c, cfg, tmp = env
    def boom(): raise QueryError("down")
    demo.rest_factory = boom
    r = start(c).json()
    assert r["state"] == "failed"
    assert start(c).json()["state"] == "failed"
    assert start(c).status_code == 429                                                          # hourly limit of 2, failures counted
    again = LiveDemo(tmp / "live", cfg, rest_factory=lambda: client(org), agent_runner=scripted_agent(calls), clock=clock)
    m.app.dependency_overrides[m.live_demo] = lambda: again
    assert start(c).status_code == 429                                                          # a restart does not reset it
    clock.t += 3601
    assert start(c).status_code == 201                                                          # hourly window passes
    clock.t += 3601; start(c)
    clock.t += 3601
    assert start(c).status_code == 429                                                          # daily limit of 3 reached within 24h


def test_unknown_expired_and_busy_sessions(env):
    demo, org, clock, calls, c, *_ = env
    assert c.get("/api/live/sessions/" + "a" * 32).status_code == 404 and c.get("/api/live/sessions/not-an-id").status_code == 404
    sid = start(c).json()["session_id"]
    clock.t += 7 * 3600
    assert c.get(f"/api/live/sessions/{sid}").status_code == 410
    clock.t += 1
    with demo._c() as db:
        for i in range(2):
            db.execute("INSERT INTO sessions VALUES (?,?,?,?)", (f"{i:032x}", clock.t, "running", "{}"))
    assert start(c).status_code == 429


def test_missing_evidence_is_reported_as_not_confirmed_not_as_a_failure(env):
    demo, org, _, calls, c, *_ = env
    sid = start(c, mode="verifier_test").json()["session_id"]
    real = demo._audit
    def doctored(s):
        rep = real(s); row = rep["cases"][0]
        row["status"], row["failed_checks"] = "inconclusive", []
        for k in row["checks"]:
            if k["status"] == "failed": k["status"] = "inconclusive"
        row["inconclusive_checks"] = [k["check_id"] for k in row["checks"] if k["status"] == "inconclusive"]
        return rep
    demo._audit = doctored
    d = c.post(f"/api/live/sessions/{sid}/check").json()["reports"][0]["decision"]
    assert d == {"accepted": False, "status": "inconclusive", "severity": None}


def test_scenarios_do_not_promise_a_resolution_the_agent_does_not_perform():
    from web.app.live import SCENARIOS
    for title, text, _ in SCENARIOS.values():
        assert "already" in text and "Record the closure" in text and "follow-up" in text


def test_activity_is_aggregate_only(env):
    demo, org, clock, calls, c, cfg, tmp = env
    assert c.get("/api/live/activity").json()["sessions"] == 0
    sid = start(c, mode="verifier_test").json()["session_id"]
    c.post(f"/api/live/sessions/{sid}/check")
    a = c.get("/api/live/activity").json()
    assert a["sessions"] == 1 and a["faults_injected"] == 1 and a["faults_detected"] == 1
    assert not IDS.search(json.dumps(a)) and CODE not in json.dumps(a)
