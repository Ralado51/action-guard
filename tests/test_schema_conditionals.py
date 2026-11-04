"""Cada tipo de verificacao exige seus campos especificos e proibe os alheios."""
import copy

import pytest

from tests.conftest import EXAMPLES, load

REQUIRED = {
    "field_equals": ["field", "expected"],
    "field_not_empty": ["field"],
    "field_unchanged": ["field"],
    "record_created": ["link_field"],
    "no_unexpected_change": ["allowed_changes"],
}

VALID = {
    "field_equals": {"check_id": "c", "kind": "field_equals", "description": "d", "object": "Case",
                     "field": "Status", "expected": "Closed"},
    "field_not_empty": {"check_id": "c", "kind": "field_not_empty", "description": "d", "object": "Case",
                        "field": "Status"},
    "field_unchanged": {"check_id": "c", "kind": "field_unchanged", "description": "d", "object": "Case",
                        "field": "OwnerId"},
    "record_created": {"check_id": "c", "kind": "record_created", "description": "d", "object": "Task",
                       "link_field": "WhatId"},
    "no_unexpected_change": {"check_id": "c", "kind": "no_unexpected_change", "description": "d",
                             "object": "*", "allowed_changes": []},
}

FOREIGN = {"field": "Status", "expected": "x", "link_field": "WhatId", "allowed_changes": ["Case.Status"]}


def plan_with(check):
    p = load(EXAMPLES / "test_plan.json")
    p["checks"] = [check]
    return p


def errors(validator, check):
    return list(validator("test_plan").iter_errors(plan_with(check)))


@pytest.mark.parametrize("kind", REQUIRED)
def test_minimal_valid_check_passes(validator, kind):
    assert errors(validator, VALID[kind]) == []


@pytest.mark.parametrize("kind,missing", [(k, f) for k, fs in REQUIRED.items() for f in fs])
def test_missing_required_field_is_rejected(validator, kind, missing):
    c = copy.deepcopy(VALID[kind])
    del c[missing]
    assert errors(validator, c), f"{kind} sem {missing} deveria ser invalido"


def test_field_equals_accepts_null_expected(validator):
    c = copy.deepcopy(VALID["field_equals"])
    c["expected"] = None
    assert errors(validator, c) == []


@pytest.mark.parametrize("kind,foreign", [(k, f) for k in REQUIRED for f in FOREIGN
                                          if f not in REQUIRED[k] and not (k == "field_equals" and f == "expected")])
def test_foreign_field_is_rejected(validator, kind, foreign):
    c = copy.deepcopy(VALID[kind])
    c[foreign] = FOREIGN[foreign]
    assert errors(validator, c), f"{kind} nao deveria aceitar {foreign}"


def test_no_unexpected_change_requires_star_object_and_others_forbid_it(validator):
    c = copy.deepcopy(VALID["no_unexpected_change"])
    c["object"] = "Case"
    assert errors(validator, c)
    for kind in ("field_equals", "field_not_empty", "field_unchanged", "record_created"):
        c = copy.deepcopy(VALID[kind])
        c["object"] = "*"
        assert errors(validator, c), kind


# ---------- snapshot ----------

def snap(name="success", phase="before"):
    return load(EXAMPLES / name / f"{phase}.json")


def test_incomplete_snapshot_requires_collection_errors(validator):
    s = snap()
    s["complete"] = False
    assert list(validator("snapshot").iter_errors(s))


def test_complete_snapshot_must_not_carry_collection_errors(validator):
    s = snap()
    s["collection_errors"] = [{"object": "Task", "message": "x"}]
    assert list(validator("snapshot").iter_errors(s))


def test_confirmed_absent_is_only_allowed_after(validator):
    s = snap(phase="before")
    s["confirmed_absent"] = [{"object": "Case", "id": "500SYN000000001AAA", "basis": "x"}]
    assert list(validator("snapshot").iter_errors(s))
    assert not list(validator("snapshot").iter_errors(snap("case_deleted", "after")))


def test_confirmed_absent_requires_basis(validator):
    s = snap("case_deleted", "after")
    del s["confirmed_absent"][0]["basis"]
    assert list(validator("snapshot").iter_errors(s))


def test_primary_record_is_required(validator):
    s = snap()
    del s["primary_record"]
    assert list(validator("snapshot").iter_errors(s))
