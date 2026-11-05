"""Cobertura da regra por clausula: o servidor nunca promove alem do que consegue sustentar."""
import copy
import json

import pytest

from contracts.plan_hash import approval_is_valid, compute_plan_hash, with_hash
from contracts.semantics import validate_plan_semantics
from planner import bind_case, coverage as cov, coverage_eval as ev
from tests import sim
from tests.test_planner import FakeVultr, good_proposal, plan_with, reply, rule
from tests.test_salesforce_integration import approved_plan, reapprove, run

CHECKS = [{"check_id": i, "kind": "x"} for i in ev.CANONICAL]
DATA = ev.load(str(__import__("pathlib").Path(__file__).parent / "data" / "rule_coverage_labeled.json"))


def one(text, model_item, checks=CHECKS):
    clauses = cov.segment(text)
    assert len(clauses) == 1, [c["text"] for c in clauses]
    items, warnings = cov.finalize(clauses, [dict(model_item, clause_id=clauses[0]["clause_id"])], checks)
    return items[0], warnings


# ---- segmentacao ----
def test_segmentation_basic_and_ids_assigned_by_server():
    cl = cov.segment("Ao encerrar um Case, grave o motivo informado, preserve o proprietário e crie exatamente uma tarefa de acompanhamento vinculada. Verifique as alterações pelos dados antes e depois.")
    assert [c["clause_id"] for c in cl] == ["cl_01", "cl_02", "cl_03", "cl_04"]
    assert cl[0]["text"].startswith("Ao encerrar um Case, grave o motivo")      # condicao vira prefixo
    assert cl[3]["text"].endswith("antes e depois")                              # "antes e depois" nao se parte


def test_segmentation_overflow_is_merged_and_never_covered():
    text = ". ".join(f"Encerrar o Case numero {i}" for i in range(1, 16))
    cl = cov.segment(text)
    assert len(cl) == cov.MAX_CLAUSES and cl[-1]["overflow"]
    items, _ = cov.finalize(cl, [{"clause_id": c["clause_id"], "status": "covered", "check_ids": ["chk_status_closed"], "reason": "x"} for c in cl], CHECKS)
    assert items[-1]["status"] == cov.NOT_VERIFIABLE and all(i["status"] == cov.COVERED for i in items[:-1])


def test_segmentation_handles_empty_and_noise():
    assert cov.segment("") == [] and cov.segment("  \n . ; ") == []


# ---- travas do servidor ----
@pytest.mark.parametrize("model_item,why", [
    ({"status": "covered", "check_ids": ["chk_inexistente"], "reason": "x"}, "inexistentes"),
    ({"status": "covered", "check_ids": [], "reason": "x"}, "inexistentes"),
    ({"status": "covered", "check_ids": "chk_owner_unchanged", "reason": "x"}, "inexistentes"),
    ({"status": "covered", "check_ids": ["chk_status_closed"], "reason": "x"}, "vocabulario"),   # clausula sobre proprietario
])
def test_covered_is_downgraded_when_mapping_is_unsound(model_item, why):
    item, _ = one("Preserve o proprietário", model_item)
    assert item["status"] == cov.NOT_VERIFIABLE and why in item["reason"] and item["check_ids"] == []


def test_covered_requires_topic_match_and_keeps_only_compatible_checks():
    item, _ = one("Preserve o proprietário", {"status": "covered", "check_ids": ["chk_owner_unchanged", "chk_status_closed"], "reason": "x"})
    assert item["status"] == cov.COVERED and item["check_ids"] == ["chk_owner_unchanged"] and item["basis"] == "model"


@pytest.mark.parametrize("text", ["Envie um e-mail ao cliente", "Notifique o gestor", "Cumpra o SLA", "Atualize a conta do cliente"])
def test_out_of_scope_terms_force_not_verifiable_even_if_model_claims_covered(text):
    item, _ = one(text, {"status": "covered", "check_ids": ["chk_status_closed"], "reason": "x"})
    assert item["status"] == cov.NOT_VERIFIABLE and item["basis"] == "server_rule"


@pytest.mark.parametrize("text,cid", [
    ("Não crie nenhuma tarefa", "chk_followup_task"), ("Sem tarefa de acompanhamento", "chk_followup_task"),
    ("Crie duas tarefas", "chk_followup_task"), ("O motivo é opcional", "chk_reason_filled"),
    ("O proprietário pode ser alterado", "chk_owner_unchanged")])
def test_policy_conflicts_are_detected_by_server(text, cid):
    item, _ = one(text, {"status": "covered", "check_ids": [cid], "reason": "x"})
    assert item["status"] == cov.CONFLICT and item["check_ids"] == [cid] and item["basis"] == "server_rule"


@pytest.mark.parametrize("text", ["O proprietário não deve mudar", "O motivo não pode ficar vazio", "Preserve o proprietário"])
def test_negated_phrasing_is_not_a_false_conflict(text):
    item, _ = one(text, {"status": "covered", "check_ids": ["chk_owner_unchanged", "chk_reason_filled"], "reason": "x"})
    assert item["status"] == cov.COVERED


def test_missing_or_malformed_model_coverage_never_yields_covered():
    clauses = cov.segment("Encerrar o Case. Preservar o proprietário.")
    for bad in (None, "texto", {"a": 1}, [], [1, "x"], [{"clause_id": "cl_99", "status": "covered", "check_ids": ["chk_status_closed"]}]):
        items, _ = cov.finalize(clauses, bad, CHECKS)
        assert [i["status"] for i in items] == [cov.NOT_VERIFIABLE] * 2
        assert cov.coverage_status(items) == "partial"


def test_duplicates_first_wins_and_unknown_status_is_not_verifiable():
    clauses = cov.segment("Encerrar o Case")
    items, w = cov.finalize(clauses, [
        {"clause_id": "cl_01", "status": "not_verifiable", "check_ids": [], "reason": "a"},
        {"clause_id": "cl_01", "status": "covered", "check_ids": ["chk_status_closed"], "reason": "b"}], CHECKS)
    assert items[0]["status"] == cov.NOT_VERIFIABLE and any("duplicado" in x for x in w)
    items, _ = cov.finalize(clauses, [{"clause_id": "cl_01", "status": "mais-ou-menos", "check_ids": ["chk_status_closed"]}], CHECKS)
    assert items[0]["status"] == cov.NOT_VERIFIABLE


def test_model_text_is_sanitized_and_clause_text_is_server_owned():
    item, _ = one("Encerrar o Case", {"status": "covered", "check_ids": ["chk_status_closed"], "reason": "x\x00\x07" + "y" * 500, "text": "texto forjado"})
    assert "\x00" not in item["reason"] and len(item["reason"]) <= cov.MAX_REASON and item["text"] == "Encerrar o Case"


def test_extra_check_gets_field_topic():
    checks = CHECKS + [{"check_id": "chk_extra_01", "kind": "field_unchanged", "object": "Case", "field": "Priority"}]
    item, _ = one("Mantenha a prioridade do Case", {"status": "covered", "check_ids": ["chk_extra_01"], "reason": "x"}, checks)
    assert item["status"] == cov.COVERED


# ---- conjunto rotulado ----
def test_labeled_set_oracle_model_matches_every_label():
    r = ev.evaluate(DATA, lambda rid, cl, ex: ev.simulated_model("oracle", cl, ex))
    assert r["counts"] == {"ok": 33, "false_covered": 0, "false_uncovered": 0, "conflict_missed": 0}, [x for x in r["rows"] if x["result"] != "ok"]


def test_labeled_set_worst_case_model_only_fails_on_documented_gaps():
    """Modelo que declara TUDO coberto: o servidor ainda segura tudo, exceto as lacunas conhecidas (e documentadas)."""
    r = ev.evaluate(DATA, lambda rid, cl, ex: ev.simulated_model("optimist", cl, ex))
    bad = [x for x in r["rows"] if x["result"] != "ok"]
    assert r["counts"]["conflict_missed"] == 0 and r["counts"]["false_uncovered"] == 0
    assert {x["rule"] for x in bad if x["result"] == "false_covered"} == {x["rule"] for x in bad if x["known_gap"]}
    assert all(x["known_gap"] for x in bad), bad               # nenhuma falsa cobertura fora da lista conhecida
    assert len(bad) == 2


def test_labeled_set_labels_are_unambiguous_and_cover_all_statuses():
    statuses = set()
    for rule_ in DATA["rules"]:
        for _, label in ev.locate(cov.segment(rule_["text"]), rule_["expect"]):
            statuses.add(label["status"])
    assert statuses == set(cov.STATUSES) and len(DATA["rules"]) >= 15


# ---- integracao com o planner ----
def with_cov(rule_text, status="covered", ids=None):
    p = good_proposal()
    clauses = cov.segment(rule_text)
    p["coverage"] = [{"clause_id": c["clause_id"], "status": status, "check_ids": ids or ["chk_status_closed"], "reason": "r"} for c in clauses]
    return p


def test_create_plan_attaches_server_checked_coverage_and_binds_it_to_hash(validator):
    r = rule()
    res = plan_with(FakeVultr(reply(with_cov(r["text_pt"]))), rule=r)
    plan = res.plan
    assert not list(validator("test_plan").iter_errors(plan)) and validate_plan_semantics(plan) == []
    assert plan["rule_coverage"] and plan["plan_hash"] == compute_plan_hash(plan)
    edited = copy.deepcopy(plan)
    edited["rule_coverage"][0]["status"] = "covered"
    edited["rule_coverage"][0]["reason"] = "alterado"
    assert compute_plan_hash(edited) != plan["plan_hash"]
    assert bind_case(plan, sim.CASE)["rule_coverage"] == plan["rule_coverage"]


def test_overconfident_model_cannot_inflate_coverage_in_final_plan():
    r = rule()
    r["text_pt"] = "Encerrar o Case. Enviar e-mail ao cliente. Não crie nenhuma tarefa."
    res = plan_with(FakeVultr(reply(with_cov(r["text_pt"], ids=list(ev.CANONICAL)))), rule=r)
    st = {i["text"]: i["status"] for i in res.plan["rule_coverage"]}
    assert st == {"Encerrar o Case": "covered", "Enviar e-mail ao cliente": "not_verifiable", "Não crie nenhuma tarefa": "conflicts_with_policy"}


def test_missing_coverage_key_does_not_fail_but_marks_everything_not_verifiable():
    res = plan_with(FakeVultr(reply(good_proposal())))
    assert all(i["status"] == "not_verifiable" for i in res.plan["rule_coverage"])
    assert res.plan["rule_coverage"] and cov.coverage_status(res.plan["rule_coverage"]) == "partial"


def test_coverage_does_not_consume_extra_model_calls():
    fake = FakeVultr(reply(with_cov(rule()["text_pt"])))
    assert plan_with(fake).calls == 1 and len(fake.requests) == 1
    assert "clausulas" in fake.requests[0][3]["messages"][1]["content"]


def test_semantics_reject_coverage_pointing_to_missing_checks():
    plan = plan_with(FakeVultr(reply(with_cov(rule()["text_pt"])))).plan
    bad = copy.deepcopy(plan)
    bad["rule_coverage"][0]["check_ids"] = ["chk_nao_existe"]
    assert any("nao existe" in i for i in validate_plan_semantics(bad))
    bad = copy.deepcopy(plan)
    bad["rule_coverage"][0].update(status="covered", check_ids=[])
    assert any("covered exige" in i for i in validate_plan_semantics(bad))


# ---- relatorio ----
def approved_with(coverage):
    plan = approved_plan()
    plan.pop("rule_coverage", None)
    if coverage is not None:
        plan["rule_coverage"] = coverage
    return reapprove(plan)


def item(i, status, ids):
    return {"clause_id": f"cl_{i:02d}", "text": f"clausula {i}", "status": status, "check_ids": ids, "reason": "r", "basis": "server_rule"}


def test_report_is_partial_and_says_so_even_when_all_checks_pass(tmp_path, validator):
    plan = approved_with([item(1, "covered", ["chk_status_closed"]), item(2, "not_verifiable", [])])
    _, rep = run(sim.close_ok, tmp_path, plan=plan)
    assert rep["status"] == "passed" and rep["coverage_status"] == "partial"
    assert rep["limitations"][0].startswith("COBERTURA PARCIAL") and "cl_02" in rep["limitations"][0]
    assert rep["rule_coverage"] == plan["rule_coverage"]
    assert not list(validator("report").iter_errors(rep))


def test_report_complete_and_not_assessed(tmp_path, validator):
    _, rep = run(sim.close_ok, tmp_path / "a", plan=approved_with([item(1, "covered", ["chk_status_closed"])]))
    assert rep["coverage_status"] == "complete" and not rep["limitations"][0].startswith("COBERTURA")
    _, rep2 = run(sim.close_ok, tmp_path / "b", plan=approved_with(None))
    assert rep2["coverage_status"] == "not_assessed" and "rule_coverage" not in rep2
    for r in (rep, rep2):
        assert not list(validator("report").iter_errors(r))


def test_conflict_clause_makes_report_partial(tmp_path):
    _, rep = run(sim.close_ok, tmp_path, plan=approved_with([item(1, "conflicts_with_policy", ["chk_followup_task"])]))
    assert rep["coverage_status"] == "partial" and "conflito" in rep["limitations"][0]


# ---- CLI ----
def test_cli_requires_second_confirmation_for_partial_coverage(tmp_path, monkeypatch):
    from orchestrator import __main__ as cli
    from tests.test_orchestrator_cli import args, bundle, env  # noqa: F401
    for k, v in {"SF_LOGIN_URL": "https://example.my.salesforce.com", "SF_API_VERSION": "68.0", "SF_AGENT_ID": "0XxSYN",
                 "SF_CLIENT_ID": "cid", "SF_CLIENT_SECRET": sim.CLIENT_SECRET}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(cli.time, "sleep", lambda _: None)
    plan = approved_with([item(1, "covered", ["chk_status_closed"]), item(2, "not_verifiable", [])])
    plan["approval"] = None
    path = bundle(tmp_path, with_hash(plan))
    prompts = []

    def only_hash(prompt):
        prompts.append(prompt)
        return prompt.split("Digite ", 1)[1].removesuffix(": ") if "APROVAR" in prompt else "nao"
    fake = sim.FakeSalesforce()
    assert cli.main(args(path, tmp_path), transport=fake, confirm=only_hash) == 0
    assert fake.log == [] and any("ACEITAR COBERTURA PARCIAL" in p for p in prompts)       # recusou a 2a confirmacao: nada foi enviado

    def both(prompt):
        return "ACEITAR COBERTURA PARCIAL" if "ACEITAR" in prompt else prompt.split("Digite ", 1)[1].removesuffix(": ")
    fake = sim.FakeSalesforce()
    assert cli.main(args(path, tmp_path), transport=fake, confirm=both) == 0 and fake.action_calls == 1
    approved = json.loads(next((tmp_path / "runs").glob("integrated-*/approved_plan.json")).read_text())
    assert approved["approval"]["coverage_acknowledged"] == ["cl_01", "cl_02"] and approval_is_valid(approved)


# ---- web: confirmacao por clausula ----
from tests.test_api import HEADERS, bind, create, setup  # noqa: E402,F401


def _with_coverage(svc, calls_plan):
    items = [item(1, "covered", ["chk_status_closed"]), item(2, "not_verifiable", [])]

    def generate(rule, metadata, action):
        plan = copy.deepcopy(calls_plan)
        plan["rule_id"] = rule["rule_id"]
        plan["rule_coverage"] = items
        return with_hash(plan), {"metadata_source": "salesforce_describe", "model": "m", "calls": 1}
    svc.generate = generate
    return items


def _draft():
    plan = copy.deepcopy(approved_plan())
    plan["approval"] = None
    plan["action"]["input"].pop("case_id", None)
    return with_hash(plan)


def test_web_approve_requires_acknowledging_every_clause(setup):
    client, svc, fake, calls = setup
    _with_coverage(svc, _draft())
    plan = bind(client, create(client))
    url = "/api/plans/" + plan["plan_id"] + "/approve"
    body = {"approved_by": "operator", "approved_plan_hash": plan["plan_hash"]}
    assert client.post(url, json=body).status_code == 409
    assert client.post(url, json={**body, "acknowledged_clauses": ["cl_01"]}).status_code == 409
    assert client.post(url, json={**body, "acknowledged_clauses": ["cl_01", "cl_02", "cl_99"]}).status_code == 409
    r = client.post(url, json={**body, "acknowledged_clauses": ["cl_02", "cl_01"]})
    assert r.status_code == 200 and r.json()["approval"]["coverage_acknowledged"] == ["cl_01", "cl_02"]
    assert approval_is_valid(r.json())


def test_web_cannot_edit_rule_coverage(setup):
    client, svc, fake, calls = setup
    _with_coverage(svc, _draft())
    plan = bind(client, create(client))
    edited = copy.deepcopy(plan)
    edited["rule_coverage"][1].update(status="covered", check_ids=["chk_status_closed"])
    r = client.put("/api/plans/" + plan["plan_id"], json={"plan": edited, "expected_plan_hash": plan["plan_hash"]})
    assert r.status_code == 422


def test_web_plan_without_coverage_still_approves_without_ack(setup):
    client, svc, fake, calls = setup
    plan = bind(client, create(client))
    assert "rule_coverage" not in plan
    r = client.post("/api/plans/" + plan["plan_id"] + "/approve", json={"approved_by": "operator", "approved_plan_hash": plan["plan_hash"]})
    assert r.status_code == 200 and "coverage_acknowledged" not in r.json()["approval"]


# ---- CLI de avaliacao ----
def test_coverage_eval_cli_with_fake_model(capsys, monkeypatch):
    from tests.test_planner import Response  # noqa: F401
    dataset = str(__import__("pathlib").Path(__file__).parent / "data" / "rule_coverage_labeled.json")
    seen = []

    class Fake(FakeVultr):
        def request(self, method, url, *, headers=None, body=None, timeout=30.0):
            payload = json.loads(body)
            seen.append(payload)
            text = json.loads(payload["messages"][1]["content"].split("\n", 1)[1])
            clauses = text.get("clausulas", [])
            p = good_proposal()
            p["coverage"] = [{"clause_id": c["clause_id"], "status": "not_verifiable", "check_ids": [], "reason": "n"} for c in clauses]
            return reply(p)
    monkeypatch.setenv("VULTR_INFERENCE_API_KEY", "k")
    monkeypatch.setenv("VULTR_INFERENCE_MODEL", "m")
    code = ev.main([dataset, "--fixture-metadata"], transport=Fake())
    out = json.loads(capsys.readouterr().out)
    assert seen and out["errors"] == [] and out["counts"]["false_covered"] == 0 and out["counts"]["conflict_missed"] == 0 and out["counts"]["false_uncovered"] > 0
    assert code == 0 and out["source"] == "fixture"
