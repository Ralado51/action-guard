import copy
import json
from types import SimpleNamespace

import pytest

from contracts.plan_hash import approval_is_valid, with_hash
from orchestrator import __main__ as cli
from tests import sim
from tests.test_salesforce_integration import approved_plan


def bundle(tmp_path, plan=None):
    path = tmp_path / "draft.json"
    p = copy.deepcopy(plan or approved_plan())
    p["approval"] = None
    path.write_text(json.dumps({"plan": p, "generation": {"metadata_source": "salesforce_describe"}}))
    return path


@pytest.fixture
def env(monkeypatch):
    for key, value in {"SF_LOGIN_URL": "https://example.my.salesforce.com", "SF_API_VERSION": "68.0",
                       "SF_AGENT_ID": "0XxSYN", "SF_CLIENT_ID": "cid", "SF_CLIENT_SECRET": sim.CLIENT_SECRET}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)


def args(path, tmp_path):
    return ["run", "--plan", str(path), "--approved-by", "operator", "--runs-dir", str(tmp_path / "runs")]


def approve(prompt):
    return prompt.split("Digite ", 1)[1].removesuffix(": ")


def test_cli_decline_performs_no_http(tmp_path, env):
    fake = sim.FakeSalesforce()
    assert cli.main(args(bundle(tmp_path), tmp_path), transport=fake, confirm=lambda _: "nao") == 0
    assert fake.log == []


def test_cli_exact_hash_approval_and_real_evaluator(tmp_path, env):
    path = bundle(tmp_path)
    fake = sim.FakeSalesforce()
    assert cli.main(args(path, tmp_path), transport=fake, confirm=approve) == 0
    assert fake.action_calls == 1
    reports = list((tmp_path / "runs").glob("integrated-*/report.json"))
    assert json.loads(reports[0].read_text())["status"] == "passed"
    plan = json.loads(next((tmp_path / "runs").glob("integrated-*/approved_plan.json")).read_text())
    assert approval_is_valid(plan)
    assert json.loads(path.read_text())["plan"]["approval"] is None
    assert sim.TOKEN not in reports[0].read_text()


def test_cli_tampered_plan_rejected_before_network(tmp_path, env):
    plan = approved_plan()
    plan["action"]["input"]["closure_reason"] = "Duplicate"
    fake = sim.FakeSalesforce()
    assert cli.main(args(bundle(tmp_path, plan), tmp_path), transport=fake, confirm=approve) == 1
    assert fake.log == []


def test_cli_reservation_prevents_replay_even_with_new_plan_hash(tmp_path, env):
    path = bundle(tmp_path)
    assert cli.main(args(path, tmp_path), transport=sim.FakeSalesforce(), confirm=approve) == 0
    data = json.loads(path.read_text())
    data["plan"]["plan_id"] = "different-plan"
    data["plan"] = with_hash(data["plan"])
    path.write_text(json.dumps(data))
    fake = sim.FakeSalesforce()
    assert cli.main(args(path, tmp_path), transport=fake, confirm=approve) == 1
    assert fake.log == []


def test_cli_failed_auth_keeps_attempt_marker(tmp_path, env):
    fake = sim.FakeSalesforce()
    fake.oauth_status = 400
    assert cli.main(args(bundle(tmp_path), tmp_path), transport=fake, confirm=approve) == 1
    assert len(list((tmp_path / "runs" / "attempts").glob("*.json"))) == 1
    assert fake.action_calls == 0


def test_cli_prepare_saves_bound_unapproved_plan(tmp_path, monkeypatch):
    draft = approved_plan()
    draft["approval"] = None
    del draft["action"]["input"]["case_id"]
    draft = with_hash(draft)
    calls = []
    def generate(*a):
        calls.append(a)
        return SimpleNamespace(plan=draft, metadata_source="salesforce_describe", metadata_collected_at="now",
                               model="model", served_model="model", usage={}, calls=1, warnings=[])
    monkeypatch.setattr(cli, "create_plan", generate)
    meta, rule, output = [tmp_path / n for n in ("meta.json", "rule.json", "out.json")]
    meta.write_text(json.dumps({"source": "salesforce_describe"}))
    rule.write_text("{}")
    cmd = ["prepare", "--rule", str(rule), "--metadata", str(meta), "--case-id", sim.CASE,
           "--reason", sim.REASON, "--subject", sim.SUBJECT, "--output", str(output)]
    fake = sim.FakeSalesforce()
    assert cli.main(cmd, transport=fake) == 0
    plan = json.loads(output.read_text())["plan"]
    assert plan["action"]["input"]["case_id"] == sim.CASE
    assert plan["plan_version"] == draft["plan_version"] + 1
    assert plan["approval"] is None and not approval_is_valid(plan)
    assert fake.log == [] and len(calls) == 1
    assert cli.main(cmd, transport=fake) == 1
    assert len(calls) == 1


def test_cli_rejects_fixture_before_generation(tmp_path, monkeypatch):
    def fail(*a):
        pytest.fail("Nao deve chamar o modelo")
    monkeypatch.setattr(cli, "create_plan", fail)
    meta = tmp_path / "fixture.json"
    meta.write_text('{"source":"fixture"}')
    assert cli.main(["prepare", "--rule", "unused", "--metadata", str(meta), "--case-id", sim.CASE,
                     "--reason", sim.REASON, "--subject", sim.SUBJECT,
                     "--output", str(tmp_path / "out.json")]) == 1
