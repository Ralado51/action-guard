"""Auditoria de resultados (somente leitura) com Salesforce e Vultr SIMULADOS."""
import copy
import json

import pytest

from audit import explain as ex
from audit.__main__ import main as audit_main
from audit.evaluate import classify_checks
from audit.run import AuditBlocked, run_audit
from connector.auth import get_token
from connector.config import SalesforceConfig
from connector.ids import to_sfid18
from connector.rest import SalesforceRest
from connector.transport import Response
from planner.client import VultrChatClient
from planner.config import PlannerConfig
from tests import sim
from tests.test_salesforce_integration import ENV, approved_plan
from tests.test_planner import FakeVultr, reply

OK_REASON = "Resolved - Customer confirmed"


def rest_for(fake):
    cfg = SalesforceConfig.from_env(ENV)
    return SalesforceRest(cfg, get_token(cfg, fake), fake)


def case_id(n):
    return to_sfid18(f"500SYN{n:09d}")


def make_case(fake, n, *, reason=OK_REASON, status="Closed", tasks=1, subject=sim.SUBJECT, closed="2026-11-04T10:00:00.000+0000", user="005AGENT0000000001"):
    cid = case_id(n)
    fake.cases[cid] = {"Id": cid, "Status": status, "OwnerId": sim.OWNER, "Closure_Reason__c": reason,
                       "ClosedDate": closed if status == "Closed" else None, "IsClosed": status == "Closed",
                       "Priority": "Medium", "Subject": f"Caso {n}", "LastModifiedById": user}
    fake.add_task(tasks, subject=subject, case=cid)
    return cid


@pytest.fixture
def population():
    fake = sim.FakeSalesforce()
    fake.cases.clear()
    ids = {}
    for n in range(1, 8):                       # 7 corretos
        ids[n] = make_case(fake, n)
    ids["empty"] = make_case(fake, 8, reason=None)
    ids["notask"] = make_case(fake, 9, tasks=0)
    ids["dup"] = make_case(fake, 10, tasks=2)
    return fake, ids


def audit(fake, **kw):
    kw.setdefault("case_ids", None)
    return run_audit(approved_plan(), rest_for(fake), **kw)


# ---- bloqueios e classificacao ----
def test_unapproved_plan_is_blocked_before_any_query(population):
    fake, ids = population
    plan = approved_plan()
    plan["approval"] = None
    with pytest.raises(AuditBlocked):
        run_audit(plan, rest_for(fake), case_ids=list(ids.values()))
    assert not [u for m, u in fake.log if "query" in u]


def test_selection_must_be_exactly_one_mode(population):
    fake, ids = population
    with pytest.raises(AuditBlocked):
        audit(fake)
    with pytest.raises(AuditBlocked):
        audit(fake, case_ids=[case_id(1)], since="2026-11-01T00:00:00Z")


def test_checks_needing_before_state_are_not_auditable_and_never_pass():
    ok, skipped = classify_checks(approved_plan())
    assert {c["check_id"] for c in ok} == {"chk_status_closed", "chk_reason_filled", "chk_followup_task"}
    assert {s["check_id"] for s in skipped} == {"chk_reason_matches", "chk_owner_unchanged", "chk_no_unexpected"}


# ---- taxa e agrupamento ----
def test_rate_counts_and_failure_grouping(population, validator):
    fake, ids = population
    r = audit(fake, case_ids=list(ids.values()))
    assert r["totals"] == {"evaluated": 10, "correct": 7, "incorrect": 3, "inconclusive": 0}
    assert r["outcome_rate"] == 0.7
    by = {c["check_id"]: c for c in r["by_check"]}
    assert (by["chk_reason_filled"]["failed"], by["chk_followup_task"]["failed"], by["chk_status_closed"]["failed"]) == (1, 2, 0)
    bad = {c["case_id"]: c for c in r["cases"]}
    assert bad[ids["empty"]]["failed_checks"] == ["chk_reason_filled"] and bad[ids["empty"]]["evidence"]["chk_reason_filled"] == {"observed": None}
    assert bad[ids["notask"]]["failed_checks"] == ["chk_followup_task"] and bad[ids["dup"]]["failed_checks"] == ["chk_followup_task"]
    assert not list(validator("audit_report").iter_errors(r))
    assert r["summary"]["basis"] == "server" and "7 of 10" in r["summary"]["text"]
    assert any("not auditable" in x.lower() for x in r["limitations"])


def test_claimed_but_not_closed_is_caught_by_ids_but_invisible_to_window(population):
    fake, ids = population
    ghost = make_case(fake, 11, status="New", tasks=0)          # o agente "disse" que fechou; nao fechou
    by_ids = audit(fake, case_ids=[ghost])
    assert by_ids["totals"]["incorrect"] == 1 and "chk_status_closed" in by_ids["cases"][0]["failed_checks"]
    window = audit(fake, since="2026-11-01T00:00:00Z", limit=50)
    assert ghost not in {c["case_id"] for c in window["cases"]} and window["totals"]["evaluated"] == 10
    assert any("already closed" in x for x in window["limitations"])


def test_window_filters_by_user_and_limit(population):
    fake, ids = population
    make_case(fake, 12, user="005OTHER0000000001")
    mine = audit(fake, since="2026-11-01T00:00:00Z", modified_by="005AGENT0000000001", limit=500)
    assert mine["totals"]["evaluated"] == 10 and mine["selection"]["filtered_by_user"] is True
    assert "005AGENT0000000001" not in json.dumps(mine)           # o Id do usuario nao vai para o relatorio
    assert audit(fake, since="2026-11-01T00:00:00Z", limit=3)["totals"]["evaluated"] == 3
    with pytest.raises(ValueError):
        audit(fake, since="ontem")
    with pytest.raises(ValueError):
        audit(fake, since="2026-11-01T00:00:00Z", limit=0)


# ---- honestidade: evidencia insuficiente nunca vira correto ----
def test_task_read_failure_makes_cases_inconclusive_not_correct(population):
    fake, ids = population
    fake.fail_task_query_after_action = True
    fake.action_calls = 1
    r = audit(fake, case_ids=list(ids.values()))
    assert r["totals"]["correct"] == 0 and r["outcome_rate"] == 0.0
    assert r["totals"]["inconclusive"] == 9 and r["totals"]["incorrect"] == 1       # a falha comprovada (motivo vazio) vence
    assert r["collection_errors"] and any("read failure" in x.lower() for x in r["limitations"])


def test_missing_case_and_omitted_field_are_inconclusive(population):
    fake, ids = population
    r = audit(fake, case_ids=[case_id(999), ids[1]])
    assert r["totals"] == {"evaluated": 2, "correct": 1, "incorrect": 0, "inconclusive": 1}
    fake.omit_fields = {"Closure_Reason__c"}
    r = audit(fake, case_ids=[ids[1]])
    assert r["totals"]["inconclusive"] == 1 and r["totals"]["correct"] == 0


def test_main_read_failure_yields_no_results_not_a_green_report(population, monkeypatch):
    fake, ids = population
    from connector.rest import QueryError
    import audit.collect as c

    def failing(*a, **k):
        raise QueryError("recusada")
    monkeypatch.setattr(c, "fetch_cases_by_ids", failing)
    r = audit(fake, case_ids=[ids[1]])
    assert r["collection_errors"] and r["totals"]["correct"] == 0 and r["totals"]["inconclusive"] == 1


def test_fifteen_char_ids_are_accepted(population):
    fake, ids = population
    assert audit(fake, case_ids=[ids[1][:15]])["totals"]["correct"] == 1


def test_linked_task_with_15_char_whatid_still_counts_for_the_case(population):
    fake, ids = population
    for t in fake.tasks:
        if t["WhatId"] == ids[1]:
            t["WhatId"] = ids[1][:15]
    assert audit(fake, case_ids=[ids[1]])["totals"]["correct"] == 1


def test_coverage_status_comes_from_plan(population):
    fake, ids = population
    plan = approved_plan()
    from contracts.plan_hash import with_hash
    plan["rule_coverage"] = [{"clause_id": "cl_01", "text": "x", "status": "not_verifiable", "check_ids": [], "reason": "r", "basis": "server_rule"}]
    plan = with_hash(plan)
    plan["approval"] = {"approved_by": "x", "approved_at": "2026-11-05T10:00:00Z", "approved_plan_hash": plan["plan_hash"]}
    r = run_audit(plan, rest_for(fake), case_ids=[ids[1]])
    assert r["coverage_status"] == "partial" and r["rule_coverage"] == plan["rule_coverage"]


# ---- explicador ----
CFG = PlannerConfig(api_key="K", model="m")


def explained(population, text, finish="stop"):
    fake, ids = population
    rep = audit(fake, case_ids=list(ids.values()))
    v = FakeVultr(reply({"x": 1}) if text is None else _chat(text, finish))
    ex.explain(rep, VultrChatClient(CFG, v))
    return rep, v


def _chat(text, finish="stop"):
    from tests.test_planner import Response as R
    return R(200, {"model": "m", "choices": [{"index": 0, "finish_reason": finish, "message": {"role": "assistant", "content": text}}],
                   "usage": {"total_tokens": 10}})


def test_explainer_receives_only_counts_never_ids_or_values(population):
    rep, v = explained(population, "7 de 10 registros (70%) atenderam as verificacoes; 3 falharam.")
    sent = json.dumps(v.requests[0][3])
    assert "500SYN" not in sent and "Resolved" not in sent and "005SYN" not in sent
    assert rep["summary"]["basis"] == "model" and rep["summary"]["server_text"]


@pytest.mark.parametrize("bad", ["12 de 20 registros estao corretos.", "O caso 500SYN000000008AAA falhou.", "x" * 800, "70% de 15 registros", "Falhou o registro ABCDEFGHIJKLMNOP"])
def test_explainer_output_with_invented_numbers_or_ids_is_discarded(population, bad):
    rep, _ = explained(population, bad)
    assert rep["summary"]["basis"] == "server" and rep["summary"]["model_error"] == "rejected_by_validation"


def test_explainer_empty_content_keeps_server_summary(population):
    rep, _ = explained(population, "")
    assert rep["summary"]["basis"] == "server" and rep["summary"]["model_error"] == "invalid_response"


def test_numeric_guard_limit_is_documented_by_keeping_server_text_next_to_model_text(population):
    """O guarda so barra numeros inexistentes; um numero real usado no contexto errado passa. Por isso o texto do servidor acompanha."""
    rep, _ = explained(population, "8 de 10 registros estao corretos.")
    assert rep["summary"]["basis"] == "model" and "7 of 10" in rep["summary"]["server_text"]


def test_explainer_upstream_error_keeps_server_summary(population):
    fake, ids = population
    rep = audit(fake, case_ids=list(ids.values()))
    ex.explain(rep, VultrChatClient(CFG, FakeVultr(Response(401, {})), sleep=lambda s: None))
    assert rep["summary"]["basis"] == "server" and rep["summary"]["model_error"] == "auth"


# ---- CLI ----
def test_cli_is_read_only_and_saves_report(population, tmp_path, monkeypatch, capsys):
    fake, ids = population
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"plan": approved_plan()}))
    idf = tmp_path / "ids.txt"
    idf.write_text("# agente\n" + "\n".join(ids.values()) + "\n")
    code = audit_main(["run", "--plan", str(plan), "--case-ids", str(idf), "--runs-dir", str(tmp_path / "runs")], transport=fake)
    assert code == 0
    methods = {m for m, u in fake.log if "oauth2" not in u}
    assert methods == {"GET"} and fake.action_calls == 0
    saved = json.loads(next((tmp_path / "runs").glob("audit-*/audit_report.json")).read_text())
    assert saved["totals"]["evaluated"] == 10
    assert sim.TOKEN not in capsys.readouterr().out + json.dumps(saved) and sim.CLIENT_SECRET not in json.dumps(saved)


def test_cli_refuses_unapproved_plan(population, tmp_path, monkeypatch, capsys):
    fake, ids = population
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    p = approved_plan()
    p["approval"] = None
    f = tmp_path / "plan.json"
    f.write_text(json.dumps(p))
    assert audit_main(["run", "--plan", str(f), "--since", "2026-11-01T00:00:00Z", "--runs-dir", str(tmp_path / "r")], transport=fake) == 1
    assert not [u for m, u in fake.log if "query" in u]


# ---- API ----
from tests.test_api import HEADERS, approve, bind, create, setup  # noqa: E402,F401


def _approved(client):
    plan = bind(client, create(client))
    r = approve(client, plan)
    assert r.status_code == 200, r.text
    return r.json()


def test_api_audit_requires_approval_and_token(setup):
    client, svc, fake, calls = setup
    plan = bind(client, create(client))
    body = {"approved_plan_id": plan["plan_id"], "case_ids": [sim.CASE]}
    assert client.post("/api/audits", json=body).status_code == 409
    assert client.post("/api/audits", json=body, headers={"Authorization": ""}).status_code == 401


def test_api_audit_is_read_only_and_saves_evidence(setup):
    client, svc, fake, calls = setup
    plan = _approved(client)
    fake.cases.clear()
    ok = make_case(fake, 1)
    bad = make_case(fake, 2, reason=None)
    r = client.post("/api/audits", json={"approved_plan_id": plan["plan_id"], "case_ids": [ok, bad]})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["totals"] == {"evaluated": 2, "correct": 1, "incorrect": 1, "inconclusive": 0}
    assert {m for m, u in fake.log if "oauth2" not in u} == {"GET"} and fake.action_calls == 0
    assert list((svc.root / "audits").glob("audit-*/audit_report.json"))


@pytest.mark.parametrize("body", [
    {"case_ids": ["500SYN000000001YBA"], "since": "2026-11-01T00:00:00Z"},
    {},
    {"case_ids": ["curto"]},
    {"since": "ontem"},
    {"case_ids": ["500SYN000000001YBA"], "limit": 0},
    {"case_ids": ["500SYN000000001YBA"], "extra": 1},
    {"case_ids": ["500SYN000000001YBA"] * 501},
])
def test_api_audit_validates_input(setup, body):
    client, svc, fake, calls = setup
    plan = _approved(client)
    assert client.post("/api/audits", json={"approved_plan_id": plan["plan_id"], **body}).status_code == 422


def test_api_audit_explain_without_vultr_config_keeps_server_summary(setup, monkeypatch):
    client, svc, fake, calls = setup
    for k in ("VULTR_INFERENCE_API_KEY", "VULTR_INFERENCE_MODEL"):
        monkeypatch.delenv(k, raising=False)
    plan = _approved(client)
    fake.cases.clear()
    ok = make_case(fake, 1)
    rep = client.post("/api/audits", json={"approved_plan_id": plan["plan_id"], "case_ids": [ok], "explain": True}).json()
    assert rep["summary"]["basis"] == "server" and rep["summary"]["model_error"] == "config"
