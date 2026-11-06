"""Integracao Salesforce com respostas SIMULADAS: nenhuma chamada de rede real."""
import copy
import json

import pytest
from jsonschema import Draft202012Validator

from connector.agent_api import REJECTED, SENT_OK, UNCERTAIN, AgentClient
from connector.auth import AuthError, get_token
from connector.config import ConfigError, SalesforceConfig
from connector.rest import QueryError, SalesforceRest
from connector.snapshot import collect_snapshot
from contracts.plan_hash import with_hash
from contracts.semantics import validate_snapshot_pair
from orchestrator.run import RunBlocked, build_request_text, create_synthetic_case, execute_run
from orchestrator.store import EvidenceStore
from tests import sim
from tests.conftest import EXAMPLES, load

ENV = {"SF_LOGIN_URL": "https://example.my.salesforce.com/", "SF_API_VERSION": "v68.0", "SF_AGENT_ID": "0XxSYN",
       "SF_CLIENT_ID": "cid", "SF_CLIENT_SECRET": sim.CLIENT_SECRET}
NOW = lambda: "2026-11-04T19:00:00Z"  # noqa: E731


def reapprove(plan):
    plan = with_hash(plan)
    plan["approval"] = {"approved_by": "test-operator", "approved_at": NOW(),
                        "approved_plan_hash": plan["plan_hash"]}
    return plan


def approved_plan():
    plan = load(EXAMPLES / "test_plan.json")
    plan["action"]["input"]["case_id"] = sim.CASE
    return reapprove(plan)


def build(fake, tmp_path, plan=None, run_id="run-sim-001"):
    cfg = SalesforceConfig.from_env(ENV)
    tok = get_token(cfg, fake)
    rest = SalesforceRest(cfg, tok, fake)
    agent = AgentClient(cfg, tok, fake, NOW, key_factory=lambda: "key-1")
    return dict(plan=plan or approved_plan(), case_id=sim.CASE, run_id=run_id, rest=rest, agent=agent,
                store=EvidenceStore(tmp_path, run_id), sleep=lambda s: None, now=NOW)


def run(behavior, tmp_path, configure=None, **over):
    fake = sim.FakeSalesforce(behavior)
    if configure:
        configure(fake)
    kw = build(fake, tmp_path)
    kw.update(over)
    return fake, execute_run(**kw)


def by_id(report):
    return {r["check_id"]: r["status"] for r in report["results"]}


def assert_valid_report(report, validator):
    assert not list(validator("report").iter_errors(report))


# ---- 10 cenarios do dossie ----
def test_happy_path(tmp_path, validator):
    fake, rep = run(sim.close_ok, tmp_path)
    assert rep["status"] == "passed" and fake.action_calls == 1
    assert set(by_id(rep).values()) == {"passed"}
    assert_valid_report(rep, validator)


def test_reason_not_persisted_is_failure_despite_agent_success_message(tmp_path):
    fake, rep = run(sim.reason_not_persisted, tmp_path)
    s = by_id(rep)
    assert rep["status"] == "failed" and s["chk_reason_filled"] == "failed" and s["chk_reason_matches"] == "failed"
    call = json.loads((tmp_path / "run-sim-001" / "agent_call.json").read_text())
    assert "fechado" in " ".join(call["agent_text"])  # a narrativa disse sucesso; os dados decidem


def test_owner_changed(tmp_path):
    _, rep = run(sim.owner_changed, tmp_path)
    assert rep["status"] == "failed" and by_id(rep)["chk_owner_unchanged"] == "failed"
    assert rep["unexpected_changes"][0]["field"] == "OwnerId"


def test_no_task(tmp_path):
    _, rep = run(sim.no_task, tmp_path)
    assert by_id(rep)["chk_followup_task"] == "failed" and rep["status"] == "failed"


def test_multiple_new_tasks(tmp_path):
    _, rep = run(sim.many_tasks, tmp_path)
    assert by_id(rep)["chk_followup_task"] == "failed"


def test_preexisting_tasks_do_not_count_as_new(tmp_path):
    def cfg(f): f.add_task(1, subject="Contato inicial")
    fake, rep = run(sim.close_ok, tmp_path, cfg)
    assert rep["status"] == "passed"


def test_preexisting_task_with_expected_subject_does_not_hide_missing_new_one(tmp_path):
    def cfg(f): f.add_task(1)  # ja existia uma com o mesmo Subject
    _, rep = run(sim.no_task, tmp_path, cfg)
    assert by_id(rep)["chk_followup_task"] == "failed"


def test_omitted_fields_are_inconclusive_not_passed(tmp_path):
    def omit_after(f):
        sim.close_ok(f)
        f.omit_fields.add("OwnerId")
    _, rep = run(omit_after, tmp_path)
    s = by_id(rep)
    assert s["chk_owner_unchanged"] == "inconclusive" and s["chk_no_unexpected"] == "inconclusive"
    assert rep["status"] == "inconclusive"


def test_oauth_error_blocks_before_any_effect():
    fake = sim.FakeSalesforce()
    fake.oauth_status = 400
    with pytest.raises(AuthError) as e:
        get_token(SalesforceConfig.from_env(ENV), fake)
    assert sim.CLIENT_SECRET not in str(e.value) and fake.action_calls == 0


def test_action_timeout_is_uncertain_not_retried_and_reconciled_by_evidence(tmp_path):
    fake, rep = run(sim.close_ok, tmp_path, lambda f: setattr(f, "message_error", "timeout"))
    assert fake.action_calls == 1                       # nunca repetiu a mensagem
    call = json.loads((tmp_path / "run-sim-001" / "agent_call.json").read_text())
    assert call["outcome"] == UNCERTAIN
    assert any("uncertain" in l for l in rep["limitations"])
    assert rep["status"] == "passed"                    # os dados mostram o efeito; revisao humana ainda e exigida


def test_action_timeout_without_effect_fails_on_evidence(tmp_path):
    fake, rep = run(sim.nothing, tmp_path, lambda f: setattr(f, "message_error", "timeout"))
    assert fake.action_calls == 1 and rep["status"] == "failed"


def test_server_error_after_send_is_uncertain_and_not_retried(tmp_path):
    fake, rep = run(sim.nothing, tmp_path, lambda f: setattr(f, "message_error", "500"))
    assert fake.action_calls == 1
    assert json.loads((tmp_path / "run-sim-001" / "agent_call.json").read_text())["outcome"] == UNCERTAIN


def test_client_error_is_rejected(tmp_path):
    fake, rep = run(sim.nothing, tmp_path, lambda f: setattr(f, "message_error", "400"))
    assert json.loads((tmp_path / "run-sim-001" / "agent_call.json").read_text())["outcome"] == REJECTED


def test_session_not_opened_means_no_message_sent(tmp_path):
    fake, rep = run(sim.close_ok, tmp_path, lambda f: setattr(f, "open_status", 500))
    assert fake.action_calls == 0 and rep["status"] == "failed"
    assert any("did not execute" in l for l in rep["limitations"])


def test_after_snapshot_failure_is_inconclusive(tmp_path):
    _, rep = run(sim.close_ok, tmp_path, lambda f: setattr(f, "fail_task_query_after_action", True))
    s = by_id(rep)
    assert s["chk_followup_task"] == "inconclusive" and rep["status"] == "inconclusive"
    assert any("ncomplete" in l for l in rep["limitations"])


def test_session_close_failure_keeps_main_result(tmp_path):
    _, rep = run(sim.close_ok, tmp_path, lambda f: setattr(f, "close_fails", True))
    assert rep["status"] == "passed"
    assert any("close the agent session" in l for l in rep["limitations"])
    assert json.loads((tmp_path / "run-sim-001" / "agent_call.json").read_text())["session_close_error"]


# ---- coletor ----
def test_pagination_collects_all_pages(tmp_path):
    fake = sim.FakeSalesforce()
    fake.add_task(5)
    fake.page_size = 2
    kw = build(fake, tmp_path)
    snap = collect_snapshot(kw["rest"], kw["plan"], "r", "before", {"object": "Case", "id": sim.CASE}, now=NOW)
    assert len(snap["records"]["Task"]) == 5 and snap["complete"]


def test_incomplete_pagination_is_a_collection_error():
    fake = sim.FakeSalesforce()
    fake.add_task(3); fake.page_size = 2
    cfg = SalesforceConfig.from_env(ENV)
    rest = SalesforceRest(cfg, get_token(cfg, fake), fake)
    orig = fake.request
    def broken(method, url, **kw):
        if "/query/" in url:
            return sim.Response(500, [{"errorCode": "X", "message": "m"}])
        return orig(method, url, **kw)
    fake.request = broken
    snap = collect_snapshot(rest, approved_plan(), "r", "before", {"object": "Case", "id": sim.CASE}, now=NOW)
    assert not snap["complete"] and "Task" not in snap["records"]
    assert snap["collection_errors"][0]["object"] == "Task"


def test_read_failure_is_never_zero_records(tmp_path):
    fake = sim.FakeSalesforce()
    cfg = SalesforceConfig.from_env(ENV)
    rest = SalesforceRest(cfg, get_token(cfg, fake), fake)
    fake.action_calls = 1
    fake.fail_task_query_after_action = True
    snap = collect_snapshot(rest, approved_plan(), "r", "after", {"object": "Case", "id": sim.CASE}, now=NOW)
    assert "Task" not in snap["records"] and snap["collection_errors"]


def test_confirmed_deletion_via_queryall(tmp_path, validator):
    fake = sim.FakeSalesforce()
    kw = build(fake, tmp_path)
    prim = {"object": "Case", "id": sim.CASE}
    before = collect_snapshot(kw["rest"], kw["plan"], "r", "before", prim, now=NOW)
    del fake.cases[sim.CASE]; fake.deleted.add(sim.CASE)
    after = collect_snapshot(kw["rest"], kw["plan"], "r", "after", prim, before=before, now=NOW)
    assert after["confirmed_absent"][0]["id"] == sim.CASE and after["complete"]
    assert validate_snapshot_pair(kw["plan"], before, after) == []
    for s in (before, after):
        assert not list(validator("snapshot").iter_errors(s))


def test_vanished_without_confirmation_is_not_deletion(tmp_path):
    fake = sim.FakeSalesforce()
    kw = build(fake, tmp_path)
    prim = {"object": "Case", "id": sim.CASE}
    before = collect_snapshot(kw["rest"], kw["plan"], "r", "before", prim, now=NOW)
    del fake.cases[sim.CASE]  # sumiu, mas queryAll nao o acha
    after = collect_snapshot(kw["rest"], kw["plan"], "r", "after", prim, before=before, now=NOW)
    assert "confirmed_absent" not in after and not after["complete"]
    assert validate_snapshot_pair(kw["plan"], before, after) == []


def test_null_kept_and_absent_key_stays_absent(tmp_path):
    fake = sim.FakeSalesforce()
    kw = build(fake, tmp_path)
    snap = collect_snapshot(kw["rest"], kw["plan"], "r", "before", {"object": "Case", "id": sim.CASE}, now=NOW)
    assert snap["records"]["Case"][0]["fields"]["Closure_Reason__c"] is None
    fake.omit_fields.add("Priority")
    snap = collect_snapshot(kw["rest"], kw["plan"], "r", "before", {"object": "Case", "id": sim.CASE}, now=NOW)
    assert "Priority" not in snap["records"]["Case"][0]["fields"]


def test_soql_injection_rejected(tmp_path):
    fake = sim.FakeSalesforce()
    kw = build(fake, tmp_path)
    with pytest.raises(ValueError):
        collect_snapshot(kw["rest"], kw["plan"], "r", "before", {"object": "Case", "id": "x' OR Id != '"}, now=NOW)


# ---- portoes de aprovacao e seguranca ----
def blocked(plan, tmp_path, **over):
    fake = sim.FakeSalesforce()
    kw = build(fake, tmp_path, plan=plan)
    kw.update(over)
    with pytest.raises(RunBlocked):
        execute_run(**kw)
    return fake


def test_unapproved_plan_blocks_everything(tmp_path):
    fake = blocked(load(EXAMPLES / "test_plan_draft.json"), tmp_path)
    assert fake.action_calls == 0 and not any("einstein" in u for _, u in fake.log)


def test_edited_plan_invalidates_approval(tmp_path):
    plan = approved_plan()
    plan["action"]["input"]["closure_reason"] = "Duplicate"
    assert blocked(plan, tmp_path).action_calls == 0


def test_reapproval_after_edit_runs_with_new_reason(tmp_path):
    plan = approved_plan()
    plan["action"]["input"]["closure_reason"] = "Duplicate"
    plan = with_hash(plan)
    plan["approval"] = {"approved_by": "airton", "approved_at": "2026-11-04T10:00:00Z",
                        "approved_plan_hash": plan["plan_hash"]}
    plan["checks"] = [dict(c, expected="Duplicate") if c["check_id"] == "chk_reason_matches" else c for c in plan["checks"]]
    # alterar checks apos aprovar invalida de novo -> reaprovar
    plan = with_hash(plan)
    plan["approval"] = {"approved_by": "airton", "approved_at": "2026-11-04T10:00:00Z",
                        "approved_plan_hash": plan["plan_hash"]}
    def dup(sim_):
        sim._close(sim_, reason="Duplicate"); sim_.add_task(1)
    fake = sim.FakeSalesforce(dup)
    kw = build(fake, tmp_path, plan=plan)
    assert execute_run(**kw)["status"] == "passed"


def test_case_must_match_case_bound_in_plan(tmp_path):
    plan = approved_plan()
    plan["action"]["input"]["case_id"] = "500SYN000000099AAA"
    plan = with_hash(plan)
    plan["approval"] = {"approved_by": "a", "approved_at": "2026-11-04T10:00:00Z", "approved_plan_hash": plan["plan_hash"]}
    assert blocked(plan, tmp_path).action_calls == 0


def test_precondition_failure_blocks_without_sending(tmp_path):
    fake = sim.FakeSalesforce()
    fake.cases[sim.CASE].update(IsClosed=True, Status="Closed")  # Case ja encerrado: nao reutilizar
    kw = build(fake, tmp_path)
    with pytest.raises(RunBlocked, match="preconditions"):
        execute_run(**kw)
    assert fake.action_calls == 0


def test_incomplete_before_snapshot_blocks(tmp_path):
    fake = sim.FakeSalesforce()
    fake.fail_task_query_after_action = True
    fake.action_calls = 1  # simula falha de leitura ja no snapshot anterior
    kw = build(fake, tmp_path)
    with pytest.raises(RunBlocked, match="incomplete previous snapshot"):
        execute_run(**kw)
    fake.action_calls = 1


def test_request_saved_before_sending_and_no_secrets_in_evidence(tmp_path):
    fake, rep = run(sim.close_ok, tmp_path)
    files = sorted((tmp_path / "run-sim-001").glob("*.json"))
    names = {f.stem for f in files}
    assert {"plan", "before", "agent_request", "agent_call", "after", "report"} <= names
    blob = "".join(f.read_text() for f in files)
    assert sim.TOKEN not in blob and sim.CLIENT_SECRET not in blob


def test_config_requires_env_and_hides_secret():
    with pytest.raises(ConfigError):
        SalesforceConfig.from_env({})
    cfg = SalesforceConfig.from_env(ENV)
    assert sim.CLIENT_SECRET not in repr(cfg) and cfg.api_version == "68.0" and not cfg.my_domain.endswith("/")


def test_request_text_matches_validated_format():
    assert build_request_text("500X", "Resolved - Customer confirmed") == (
        "Close the synthetic test Case 500X with closure reason 'Resolved - Customer confirmed'. Execute the action once.")


def test_synthetic_case_creation_uses_post(tmp_path):
    fake = sim.FakeSalesforce()
    kw = build(fake, tmp_path)
    orig = fake.request
    def req(method, url, **k):
        if method == "POST" and url.endswith("/sobjects/Case"):
            assert json.loads(k["body"])["Subject"] == "Action Guard - Evidence Test"
            return sim.Response(201, {"id": "500SYN000000777AAA", "success": True})
        return orig(method, url, **k)
    fake.request = req
    assert create_synthetic_case(kw["rest"]) == "500SYN000000777AAA"



@pytest.mark.parametrize("bound", [None, "", "   "])
def test_case_binding_required_before_any_agent_call(tmp_path, bound):
    plan = approved_plan()
    if bound is None:
        del plan["action"]["input"]["case_id"]
    else:
        plan["action"]["input"]["case_id"] = bound
    fake = blocked(reapprove(plan), tmp_path)
    assert fake.action_calls == 0
    assert not any("einstein" in u for _, u in fake.log)


def test_changing_bound_case_invalidates_approval(tmp_path):
    plan = approved_plan()
    plan["action"]["input"]["case_id"] = "500SYN000000099AAA"
    assert blocked(plan, tmp_path).action_calls == 0


@pytest.mark.parametrize("field", ["OwnerId", "Subject", "Closure_Reason__c"])
def test_missing_before_field_blocks_before_agent_session(tmp_path, field):
    fake = sim.FakeSalesforce(sim.close_ok)
    fake.omit_fields.add(field)
    with pytest.raises(RunBlocked, match="fields not collected"):
        execute_run(**build(fake, tmp_path))
    assert fake.action_calls == 0
    assert not any("einstein" in u for _, u in fake.log)


@pytest.mark.parametrize("done", [None, "true", 1, [], {}])
def test_invalid_pagination_done_is_collection_failure(tmp_path, done):
    fake = sim.FakeSalesforce()
    original = fake.request
    def malformed(method, url, **kw):
        response = original(method, url, **kw)
        if "/query?" in url:
            if done is None:
                response.body.pop("done", None)
            else:
                response.body["done"] = done
        return response
    fake.request = malformed
    with pytest.raises(RunBlocked, match="incomplete previous snapshot"):
        execute_run(**build(fake, tmp_path))
    assert fake.action_calls == 0
