"""Regressoes dos achados da revisao de 05/11: IDs 15/18, header, erros, Task extra, estado nao-enviado."""
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from connector.ids import InvalidSalesforceId, key15, same_record, to_sfid18
from contracts.plan_hash import with_hash
from orchestrator.run import RunBlocked, execute_run
from planner import bind_case
from tests import sim
from tests.test_api import HEADERS, approve, bind, create, setup  # noqa: F401
from tests.test_salesforce_integration import build
from web.app.main import app


# ---- IDs ----
def _reference_sfid18(id15: str) -> str:
    """Implementacao de referencia independente (strings binarias) do sufixo de 3 caracteres."""
    table = "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"
    out = ""
    for k in range(0, 15, 5):
        bits = "".join("1" if c.isupper() else "0" for c in id15[k:k + 5])
        out += table[int(bits[::-1], 2)]
    return id15 + out


@pytest.mark.parametrize("id15", ["500SYN000000001", "500abcDEFghi123", "5000000000AbCdE", "ABCDEabcde12345"])
def test_to_sfid18_matches_reference(id15):
    assert to_sfid18(id15) == _reference_sfid18(id15)
    assert to_sfid18(to_sfid18(id15)) == to_sfid18(id15) and key15(to_sfid18(id15)) == id15


def test_case_variation_changes_suffix():
    assert to_sfid18("aaaaaaaaaaaaaaa")[15:] == "AAA" and to_sfid18("AAAAAAAAAAAAAAA")[15:] == "555"


@pytest.mark.parametrize("bad", ["", "x", "500SYN00000000", "500SYN0000000012", "500SYN00000000123", "500SYN000000001AA!", None, 15])
def test_invalid_ids_rejected(bad):
    with pytest.raises(InvalidSalesforceId):
        to_sfid18(bad)


def test_same_record_across_forms():
    assert same_record("500SYN000000001", sim.CASE) and not same_record("500SYN000000002", sim.CASE)


def test_bind_case_normalizes_15_to_18():
    plan = load_draft()
    assert bind_case(plan, "500SYN000000001")["action"]["input"]["case_id"] == sim.CASE


def load_draft():
    from tests.conftest import EXAMPLES, load
    return load(EXAMPLES / "test_plan_draft.json")


def _unique_plans(svc):
    orig = svc.generate

    def gen(rule, meta, action):
        plan, g = orig(rule, meta, action)
        plan = dict(plan, plan_id="plan-" + uuid.uuid4().hex[:8])
        return with_hash(plan), g
    svc.generate = gen


def _bind_approve(client, case_id):
    plan = create(client)
    p = client.post(f"/api/plans/{plan['plan_id']}/case", json={"case_id": case_id, "expected_plan_hash": plan["plan_hash"]}).json()
    approve(client, p)
    return client.get(f"/api/plans/{p['plan_id']}").json()


def _run(client, p):
    return client.post("/api/runs", json={"approved_plan_id": p["plan_id"], "expected_plan_hash": p["plan_hash"]})


def test_reservation_blocks_same_case_in_15_and_18_char_forms(setup):
    client, svc, fake, _ = setup
    _unique_plans(svc)
    assert _run(client, _bind_approve(client, "500SYN000000001")).status_code == 202
    assert _run(client, _bind_approve(client, sim.CASE)).status_code == 409


def test_orchestrator_runs_with_15_char_case_id(tmp_path):
    fake = sim.FakeSalesforce(sim.close_ok)
    kw = build(fake, tmp_path)
    # plano aprovado ja vinculado em 18; o argumento chega em 15 caracteres
    from tests.test_salesforce_integration import approved_plan
    plan = approved_plan()
    plan["action"]["input"]["case_id"] = sim.CASE
    plan = with_hash(plan)
    plan["approval"] = {"approved_by": "x", "approved_at": "2026-11-05T10:00:00Z", "approved_plan_hash": plan["plan_hash"]}
    kw.update(plan=plan, case_id=sim.CASE[:15])
    rep = execute_run(**kw)
    assert rep["status"] == "passed"


def test_different_case_still_blocked(tmp_path):
    from tests.test_salesforce_integration import approved_plan
    plan = approved_plan()
    plan["action"]["input"]["case_id"] = sim.CASE
    plan = with_hash(plan)
    plan["approval"] = {"approved_by": "x", "approved_at": "2026-11-05T10:00:00Z", "approved_plan_hash": plan["plan_hash"]}
    fake = sim.FakeSalesforce()
    kw = build(fake, tmp_path, plan=plan)
    kw["case_id"] = "500SYN000000002"
    with pytest.raises(RunBlocked):
        execute_run(**kw)
    assert fake.action_calls == 0


# ---- header e erros ----
def test_non_ascii_authorization_is_401_not_500(setup):
    client, *_ = setup
    r = client.get("/api/plans/x", headers={"Authorization": "Bearer ação".encode("latin-1")})
    assert r.status_code == 401


def test_internal_bug_is_500_generic_not_503_config(setup, monkeypatch):
    client, svc, *_ = setup
    monkeypatch.setattr(svc, "get", lambda key: {}["campo"])
    with TestClient(app, headers=HEADERS, raise_server_exceptions=False) as c:
        r = c.get("/api/plans/x")
    assert r.status_code == 500 and r.json() == {"detail": "Internal server error."}


def test_missing_metadata_file_is_still_503(setup, monkeypatch):
    client, *_ = setup
    monkeypatch.setenv("SF_METADATA_PATH", "/nao/existe.json")
    r = client.post("/api/plans", json={"rule_text_pt": "x", "closure_reason": sim.REASON})
    assert r.status_code == 503


# ---- Task extra e alcance ----
def _run_sim(behavior, tmp_path):
    from tests.test_salesforce_integration import run
    return run(behavior, tmp_path)


def test_extra_linked_task_with_other_subject_is_warned_not_hidden(tmp_path):
    _, rep = _run_sim(sim.extra_other_task, tmp_path)
    assert rep["status"] == "passed"
    assert any(l.startswith("WARNING chk_followup_task") for l in rep["limitations"])
    detail = next(r for r in rep["results"] if r["check_id"] == "chk_followup_task")["evidence"]["after"]
    assert len(detail["linked_unmatched_ids"]) == 1 and len(detail["matching_ids"]) == 1


def test_clean_run_has_no_task_warning_but_declares_scope(tmp_path):
    _, rep = _run_sim(sim.close_ok, tmp_path)
    assert not any(l.startswith("WARNING") for l in rep["limitations"])
    blob = " ".join(rep["limitations"])
    assert "does not observe other objects" in blob and "stops as soon as all checks pass" in blob


def test_rejected_after_send_does_not_claim_nothing_ran(tmp_path):
    from tests.test_salesforce_integration import run
    _, rep = run(sim.nothing, tmp_path, lambda f: setattr(f, "message_error", "400"))
    text = " ".join(rep["limitations"])
    assert "This does not prove that nothing was executed" in text and "did not execute" not in text


# ---- estado nao-enviado ----
def test_blocked_before_send_releases_reservation_and_is_reported(setup):
    client, svc, *_ = setup
    p = bind(client, create(client)); approve(client, p)

    def blocked(*a):
        raise RunBlocked("precondicoes nao satisfeitas: pre_open")
    svc.execute = blocked
    rid = _run(client, p).json()["run_id"]
    st = client.get("/api/runs/" + rid).json()
    assert st["state"] == "blocked" and st["sent"] is False and "pre_open" in st["blocked_reason"]
    svc.execute = lambda plan, run_id: {"status": "passed"}
    assert _run(client, p).status_code == 202            # reserva liberada: nada foi enviado


def test_error_after_request_saved_keeps_reservation(setup):
    client, svc, *_ = setup
    p = bind(client, create(client)); approve(client, p)

    def after_send(plan, run_id):
        d = svc.root / "evidence" / run_id
        d.mkdir(parents=True)
        (d / "agent_request.json").write_text("{}")
        raise RunBlocked("falha depois do pedido gravado")
    svc.execute = after_send
    rid = _run(client, p).json()["run_id"]
    st = client.get("/api/runs/" + rid).json()
    assert st["state"] == "error" and st["sent"] is True
    assert _run(client, p).status_code == 409


def test_unknown_exception_before_anything_is_treated_as_possibly_sent(setup):
    client, svc, *_ = setup
    p = bind(client, create(client)); approve(client, p)
    svc.execute = lambda plan, run_id: (_ for _ in ()).throw(RuntimeError("x"))
    rid = _run(client, p).json()["run_id"]
    assert client.get("/api/runs/" + rid).json()["state"] == "error"
    assert _run(client, p).status_code == 409


def test_reserve_key_is_independent_of_bind_normalization(setup):
    """Defesa em profundidade: mesmo um plano com Id de 15 caracteres gravado fora do bind colide na reserva."""
    client, svc, *_ = setup
    _unique_plans(svc)
    first = _bind_approve(client, sim.CASE)
    assert _run(client, first).status_code == 202
    second = _bind_approve(client, sim.CASE)
    with svc.connect() as db:
        row = json.loads(db.execute("SELECT body FROM plans WHERE id=?", (second["plan_id"],)).fetchone()[0])
        plan = row["plan"]
        plan["action"]["input"]["case_id"] = sim.CASE[:15]
        plan = with_hash(plan)
        plan["approval"] = {"approved_by": "x", "approved_at": "2026-11-05T10:00:00Z", "approved_plan_hash": plan["plan_hash"]}
        row["plan"] = plan
        db.execute("UPDATE plans SET body=? WHERE id=?", (json.dumps(row), second["plan_id"]))
    assert _run(client, plan).status_code == 409
