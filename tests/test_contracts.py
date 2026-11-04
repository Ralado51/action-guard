import copy
import re

import pytest

from contracts.plan_hash import approval_is_valid, compute_plan_hash
from contracts.semantics import validate_plan_semantics, validate_snapshot_pair
from tests import oracle
from tests.conftest import EXAMPLES, SCENARIOS, load

CASE_ID = "500SYN000000001AAA"


def plan():
    return load(EXAMPLES / "test_plan.json")


# ---------- validade dos exemplos contra os schemas ----------

def test_rule_and_plans_validate(validator):
    validator("rule").validate(load(EXAMPLES / "rule.json"))
    validator("test_plan").validate(load(EXAMPLES / "test_plan.json"))
    validator("test_plan").validate(load(EXAMPLES / "test_plan_draft.json"))


@pytest.mark.parametrize("name", SCENARIOS)
def test_snapshots_and_report_validate(validator, name):
    validator("snapshot").validate(load(EXAMPLES / name / "before.json"))
    validator("snapshot").validate(load(EXAMPLES / name / "after.json"))
    report = load(EXAMPLES / name / "report.json")
    validator("report").validate(report)
    for r in report["results"]:
        validator("check_result").validate(r)


# ---------- consistencia entre os exemplos ----------

@pytest.mark.parametrize("name", SCENARIOS)
def test_ids_are_consistent(name):
    before = load(EXAMPLES / name / "before.json")
    after = load(EXAMPLES / name / "after.json")
    report = load(EXAMPLES / name / "report.json")
    p = plan()
    assert before["run_id"] == after["run_id"] == report["run_id"]
    assert all(r["run_id"] == report["run_id"] for r in report["results"])
    assert report["plan_id"] == p["plan_id"]
    assert report["plan_hash"] == p["approval"]["approved_plan_hash"]
    assert [r["check_id"] for r in report["results"]] == [c["check_id"] for c in p["checks"]]
    assert {r["kind"] for r in report["results"]} == {c["kind"] for c in p["checks"]}
    assert report["executed_via"] == p["action"]["executed_via"]


@pytest.mark.parametrize("name", SCENARIOS)
def test_examples_are_truthful(name):
    """O status de cada verificacao confere com o calculo independente do oraculo."""
    before = load(EXAMPLES / name / "before.json")
    after = load(EXAMPLES / name / "after.json")
    report = load(EXAMPLES / name / "report.json")
    p = plan()
    checks = {c["check_id"]: c for c in p["checks"]}
    for r in report["results"]:
        expected = oracle.expected_status(checks[r["check_id"]], p, before, after, CASE_ID)
        assert r["status"] == expected, f"{name}/{r['check_id']}"
    assert report["status"] == oracle.overall_status([r["status"] for r in report["results"]])


@pytest.mark.parametrize("name", SCENARIOS)
def test_unexpected_changes_match_oracle(name):
    before = load(EXAMPLES / name / "before.json")
    after = load(EXAMPLES / name / "after.json")
    report = load(EXAMPLES / name / "report.json")
    assert report["unexpected_changes"] == oracle.unexpected_changes(plan(), before, after)


def test_expected_overall_outcomes():
    got = {n: load(EXAMPLES / n / "report.json")["status"] for n in SCENARIOS}
    assert got == {"success": "passed", "owner_changed": "failed", "task_missing": "failed",
                   "inconclusive": "inconclusive", "evidence_missing": "inconclusive",
                   "case_deleted": "failed", "case_unconfirmed": "inconclusive",
                   "duplicate_tasks": "failed"}


@pytest.mark.parametrize("name", SCENARIOS)
def test_snapshot_pairs_follow_collector_contract(name):
    """Somente evidence_missing viola o contrato do coletor (campo omitido sem erro de coleta)."""
    before = load(EXAMPLES / name / "before.json")
    after = load(EXAMPLES / name / "after.json")
    issues = validate_snapshot_pair(plan(), before, after)
    if name == "evidence_missing":
        assert any("Case.OwnerId" in i for i in issues)
    else:
        assert issues == []


def test_plan_semantics_ok():
    assert validate_plan_semantics(plan()) == []
    assert validate_plan_semantics(load(EXAMPLES / "test_plan_draft.json")) == []


def test_incomplete_collection_never_passes():
    after = load(EXAMPLES / "inconclusive" / "after.json")
    report = load(EXAMPLES / "inconclusive" / "report.json")
    assert after["complete"] is False and after["collection_errors"]
    by_id = {r["check_id"]: r["status"] for r in report["results"]}
    assert by_id["chk_followup_task"] == "inconclusive"
    assert by_id["chk_no_unexpected"] == "inconclusive"


def test_created_task_is_distinguished_from_preexisting():
    before = load(EXAMPLES / "success" / "before.json")
    after = load(EXAMPLES / "success" / "after.json")
    old = {r["id"] for r in before["records"]["Task"]}
    new = [r for r in after["records"]["Task"] if r["id"] not in old]
    assert len(new) == 1 and new[0]["fields"]["WhatId"] == CASE_ID
    assert len(old) == 1  # existe uma Task previa que nao pode contar como criada


# ---------- aprovacao do plano ----------

def test_draft_is_not_approved():
    assert not approval_is_valid(load(EXAMPLES / "test_plan_draft.json"))


def test_approved_plan_has_valid_approval_and_hash():
    p = plan()
    assert p["plan_hash"] == compute_plan_hash(p)
    assert approval_is_valid(p)


def test_editing_plan_invalidates_approval():
    p = plan()
    p["checks"][0]["expected"] = "Resolved"  # edicao posterior a aprovacao
    assert compute_plan_hash(p) != p["approval"]["approved_plan_hash"]
    assert not approval_is_valid(p)


def test_recomputed_hash_alone_does_not_restore_approval():
    p = plan()
    p["checks"][0]["expected"] = "Resolved"
    p["plan_hash"] = compute_plan_hash(p)  # novo hash, aprovacao antiga
    assert not approval_is_valid(p)


# ---------- casos negativos dos schemas ----------

def test_invalid_status_rejected(validator):
    r = load(EXAMPLES / "success" / "report.json")["results"][0]
    r["status"] = "success"
    assert list(validator("check_result").iter_errors(r))


def test_unknown_check_kind_rejected(validator):
    p = plan()
    p["checks"][0]["kind"] = "everything_is_fine"
    assert list(validator("test_plan").iter_errors(p))


def test_snapshot_phase_and_extra_fields_rejected(validator):
    s = load(EXAMPLES / "success" / "before.json")
    bad = copy.deepcopy(s)
    bad["phase"] = "during"
    assert list(validator("snapshot").iter_errors(bad))
    bad = copy.deepcopy(s)
    bad["access_token"] = "x"
    assert list(validator("snapshot").iter_errors(bad))


def test_plan_requires_executed_via(validator):
    p = plan()
    del p["action"]["executed_via"]
    assert list(validator("test_plan").iter_errors(p))


# ---------- higiene ----------

SECRET_PATTERNS = [r"Bearer\s+\S+", r"sk-[A-Za-z0-9]{10,}", r"access_token", r"client_secret",
                   r"password", r"private_key", r"\b00D[A-Za-z0-9]{12,15}\b"]


def test_examples_contain_no_secrets_or_real_ids():
    for path in EXAMPLES.rglob("*.json"):
        text = path.read_text(encoding="utf-8")
        for pat in SECRET_PATTERNS:
            assert not re.search(pat, text, re.IGNORECASE), f"{path}: {pat}"
        for rid in re.findall(r'"(?:id|record_id|snapshot_id)":\s*"([0-9A-Za-z]{15,18})"', text):
            assert "SYN" in rid, f"{path}: id nao sintetico {rid}"
