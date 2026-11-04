"""Casos de borda do oraculo: falha comprovada versus evidencia insuficiente.

Cobrem os defeitos encontrados na revisao: campo ausente (None == None) e registro
monitorado que some do snapshot final.
"""
import copy

import pytest

from contracts.semantics import validate_plan_semantics, validate_snapshot_pair
from tests import oracle
from tests.conftest import EXAMPLES, load

REASON = "Closure_Reason__c"
CASE_ID = "500SYN000000001AAA"
OLD_TASK = "00TSYN000000000AAA"
NEW_TASK = "00TSYN000000001AAA"


@pytest.fixture
def ctx():
    plan = load(EXAMPLES / "test_plan.json")
    before = load(EXAMPLES / "success" / "before.json")
    after = load(EXAMPLES / "success" / "after.json")
    return plan, before, after


def check_of(plan, check_id):
    return next(c for c in plan["checks"] if c["check_id"] == check_id)


def status(ctx_, check_id, before=None, after=None):
    plan, b, a = ctx_
    return oracle.expected_status(check_of(plan, check_id), plan, before or b, after or a)


def case(snapshot):
    return snapshot["records"]["Case"][0]["fields"]


def task(snapshot, task_id):
    return next(r for r in snapshot["records"]["Task"] if r["id"] == task_id)["fields"]


# ---------- defeito 1: chave ausente nao e valor nulo ----------

def test_owner_absent_in_both_snapshots_is_inconclusive(ctx):
    _, b, a = ctx
    b, a = copy.deepcopy(b), copy.deepcopy(a)
    del case(b)["OwnerId"], case(a)["OwnerId"]
    assert status(ctx, "chk_owner_unchanged", b, a) == "inconclusive"


@pytest.mark.parametrize("drop_in", ["before", "after"])
def test_owner_absent_in_one_snapshot_is_inconclusive(ctx, drop_in):
    _, b, a = ctx
    b, a = copy.deepcopy(b), copy.deepcopy(a)
    del case(b if drop_in == "before" else a)["OwnerId"]
    assert status(ctx, "chk_owner_unchanged", b, a) == "inconclusive"


def test_owner_null_in_both_snapshots_is_observed_and_unchanged(ctx):
    _, b, a = ctx
    b, a = copy.deepcopy(b), copy.deepcopy(a)
    case(b)["OwnerId"] = case(a)["OwnerId"] = None
    assert status(ctx, "chk_owner_unchanged", b, a) == "passed"


def test_field_equals_missing_key_is_inconclusive_and_null_is_observed(ctx):
    plan, b, a = ctx
    a = copy.deepcopy(a)
    chk = {"check_id": "x", "kind": "field_equals", "object": "Case", "field": REASON, "expected": None}
    case(a)[REASON] = None
    assert oracle.expected_status(chk, plan, b, a) == "passed"
    del case(a)[REASON]
    assert oracle.expected_status(chk, plan, b, a) == "inconclusive"


def test_field_not_empty_distinguishes_empty_missing_and_filled(ctx):
    _, b, a = ctx
    a = copy.deepcopy(a)
    case(a)[REASON] = ""
    assert status(ctx, "chk_reason_filled", after=a) == "failed"
    del case(a)[REASON]
    assert status(ctx, "chk_reason_filled", after=a) == "inconclusive"


def test_no_unexpected_change_with_uncollected_monitored_field_is_inconclusive(ctx):
    _, b, a = ctx
    b, a = copy.deepcopy(b), copy.deepcopy(a)
    del case(b)["Priority"], case(a)["Priority"]
    assert status(ctx, "chk_no_unexpected", b, a) == "inconclusive"


def test_uncollected_allowed_field_does_not_block_the_check(ctx):
    _, b, a = ctx
    a = copy.deepcopy(a)
    del case(a)["ClosedDate"]  # esta em allowed_changes
    assert status(ctx, "chk_no_unexpected", after=a) == "passed"
    assert any("Case.ClosedDate" in i for i in validate_snapshot_pair(ctx[0], b, a))


# ---------- defeito 2: registro monitorado some do snapshot final ----------

def test_case_gone_without_confirmation_is_inconclusive_not_passed_and_not_a_crash(ctx):
    plan, b, a = ctx
    a = copy.deepcopy(a)
    a["records"]["Case"] = []  # complete continua true: o coletor violou o contrato
    for cid in ("chk_status_closed", "chk_reason_filled", "chk_owner_unchanged", "chk_no_unexpected"):
        assert status(ctx, cid, after=a) == "inconclusive", cid
    assert oracle.unexpected_changes(plan, b, a) == []
    assert any("sumiu sem estar em records nem em confirmed_absent" in i
               for i in validate_snapshot_pair(plan, b, a))


def test_case_deletion_confirmed_is_a_proven_failure(ctx):
    plan, b, a = ctx
    a = copy.deepcopy(a)
    a["records"]["Case"] = []
    a["confirmed_absent"] = [{"object": "Case", "id": CASE_ID, "basis": "queryAll IsDeleted = true"}]
    for cid in ("chk_status_closed", "chk_reason_filled", "chk_owner_unchanged", "chk_no_unexpected"):
        assert status(ctx, cid, after=a) == "failed", cid
    assert oracle.unexpected_changes(plan, b, a) == [
        {"object": "Case", "record_id": CASE_ID, "field": "__record__", "before": "present", "after": "deleted"}]
    assert validate_snapshot_pair(plan, b, a) == []


def test_preexisting_task_deleted_confirmed_is_unexpected_and_unaccounted_is_not(ctx):
    plan, b, a = ctx
    gone = copy.deepcopy(a)
    gone["records"]["Task"] = [r for r in gone["records"]["Task"] if r["id"] != OLD_TASK]
    assert status(ctx, "chk_no_unexpected", after=gone) == "inconclusive"
    gone["confirmed_absent"] = [{"object": "Task", "id": OLD_TASK, "basis": "queryAll IsDeleted = true"}]
    assert status(ctx, "chk_no_unexpected", after=gone) == "failed"


def test_proven_failure_beats_insufficient_evidence(ctx):
    """Dono mudou (comprovado) e a coleta de Task falhou: continua failed, nao inconclusive."""
    plan, b, a = ctx
    a = copy.deepcopy(a)
    case(a)["OwnerId"] = "005SYN000000002AAA"
    a["complete"] = False
    a["collection_errors"] = [{"object": "Task", "message": "timeout"}]
    assert status(ctx, "chk_no_unexpected", after=a) == "failed"
    assert status(ctx, "chk_followup_task", after=a) == "inconclusive"
    statuses = [oracle.expected_status(c, plan, b, a) for c in plan["checks"]]
    assert oracle.overall_status(statuses) == "failed"


def test_object_missing_from_final_snapshot_is_inconclusive(ctx):
    plan, b, a = ctx
    a = copy.deepcopy(a)
    del a["records"]["Task"]
    assert status(ctx, "chk_followup_task", after=a) == "inconclusive"
    assert status(ctx, "chk_no_unexpected", after=a) == "inconclusive"
    assert any("Task ausente de records" in i for i in validate_snapshot_pair(plan, b, a))


def test_incomplete_before_snapshot_is_inconclusive(ctx):
    _, b, a = ctx
    b = copy.deepcopy(b)
    b["complete"] = False
    b["collection_errors"] = [{"object": "Task", "message": "timeout"}]
    assert status(ctx, "chk_no_unexpected", b, a) == "inconclusive"


# ---------- record_created ----------

def test_task_linked_to_another_record_does_not_count(ctx):
    _, b, a = ctx
    a = copy.deepcopy(a)
    task(a, NEW_TASK)["WhatId"] = "500SYN000000999AAA"
    assert status(ctx, "chk_followup_task", after=a) == "failed"


def test_new_task_without_link_field_is_inconclusive(ctx):
    _, b, a = ctx
    a = copy.deepcopy(a)
    del task(a, NEW_TASK)["WhatId"]
    assert status(ctx, "chk_followup_task", after=a) == "inconclusive"


def test_preexisting_task_does_not_count_as_created(ctx):
    _, b, a = ctx
    a = copy.deepcopy(a)
    a["records"]["Task"] = [r for r in a["records"]["Task"] if r["id"] != NEW_TASK]
    assert status(ctx, "chk_followup_task", after=a) == "failed"


# ---------- registro principal ----------

def test_primary_record_mismatch_is_inconclusive(ctx):
    plan, b, a = ctx
    a = copy.deepcopy(a)
    a["primary_record"] = {"object": "Case", "id": "500SYN000000777AAA"}
    assert status(ctx, "chk_status_closed", after=a) == "inconclusive"
    assert any("primary_record" in i for i in validate_snapshot_pair(plan, b, a))


def test_field_check_on_non_primary_object_is_rejected_explicitly(ctx):
    plan, b, a = ctx
    chk = {"check_id": "x", "kind": "field_not_empty", "object": "Task", "field": "Subject"}
    with pytest.raises(ValueError):
        oracle.expected_status(chk, plan, b, a)


def test_overall_precedence():
    assert oracle.overall_status(["passed", "inconclusive", "failed"]) == "failed"
    assert oracle.overall_status(["passed", "inconclusive"]) == "inconclusive"
    assert oracle.overall_status(["passed"]) == "passed"


# ---------- semantica do plano ----------

def test_plan_semantics_catches_incoherent_plans(ctx):
    plan, _, _ = ctx
    p = copy.deepcopy(plan)
    p["checks"][0]["field"] = "NaoMonitorado"
    assert any("NaoMonitorado" in i for i in validate_plan_semantics(p))

    p = copy.deepcopy(plan)
    p["checks"].append(copy.deepcopy(p["checks"][0]))
    assert any("check_id duplicado" in i for i in validate_plan_semantics(p))

    p = copy.deepcopy(plan)
    p["checks"].append({**copy.deepcopy(check_of(plan, "chk_no_unexpected")), "check_id": "chk_no_unexpected_2"})
    assert any("no maximo uma" in i for i in validate_plan_semantics(p))

    p = copy.deepcopy(plan)
    check_of(p, "chk_no_unexpected")["allowed_changes"].append("Case.Inexistente")
    assert any("Case.Inexistente" in i for i in validate_plan_semantics(p))

    p = copy.deepcopy(plan)
    check_of(p, "chk_followup_task")["link_field"] = "CampoSemMonitorar"
    assert any("link_field" in i for i in validate_plan_semantics(p))


# ---- record_created: expected_count / match (dossie Salesforce) ----
import copy as _copy

from contracts.semantics import validate_plan_semantics as _vps
from tests.conftest import EXAMPLES as _EX, load as _load
from tests import oracle as _oracle


def _ctx(scn="success"):
    plan = _load(_EX / "test_plan.json")
    return plan, _load(_EX / scn / "before.json"), _load(_EX / scn / "after.json")


def _followup(plan):
    return next(c for c in plan["checks"] if c["check_id"] == "chk_followup_task")


def test_followup_check_requires_exactly_one_matching_task():
    plan, b, a = _ctx()
    chk = _followup(plan)
    assert chk["expected_count"] == 1 and chk["match"]["Subject"]
    assert _vps(plan) == []
    assert _oracle.expected_status(chk, plan, b, a) == "passed"


def test_wrong_subject_task_is_failure_not_pass():
    plan, b, a = _ctx()
    for r in a["records"]["Task"]:
        if r["id"].endswith("001AAA"):
            r["fields"]["Subject"] = "Outro assunto"
    assert _oracle.expected_status(_followup(plan), plan, b, a) == "failed"


def test_duplicate_matching_tasks_fail():
    plan, b, a = _ctx("duplicate_tasks")
    assert _oracle.expected_status(_followup(plan), plan, b, a) == "failed"


def test_new_task_with_uncollected_subject_is_inconclusive():
    plan, b, a = _ctx()
    for r in a["records"]["Task"]:
        if r["id"].endswith("001AAA"):
            del r["fields"]["Subject"]
    assert _oracle.expected_status(_followup(plan), plan, b, a) == "inconclusive"


def test_duplicate_wins_over_unknown_candidate():
    plan, b, a = _ctx("duplicate_tasks")
    extra = _copy.deepcopy(a["records"]["Task"][-1])
    extra["id"] = "00TSYN000000009AAA"
    del extra["fields"]["Subject"]
    a["records"]["Task"].append(extra)
    assert _oracle.expected_status(_followup(plan), plan, b, a) == "failed"


def test_match_field_must_be_monitored():
    plan, _, _ = _ctx()
    _followup(plan)["match"]["Description"] = "x"
    assert any("match" in i for i in _vps(plan))
