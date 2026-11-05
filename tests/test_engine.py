"""Production evaluator vs independent oracle; no calls to external systems."""
import copy
import inspect

import pytest

from engine import evaluate
from tests import oracle
from tests.conftest import EXAMPLES, SCENARIOS, load


def pair(name="success"):
    return (load(EXAMPLES / "test_plan.json"), load(EXAMPLES / name / "before.json"),
            load(EXAMPLES / name / "after.json"))


@pytest.mark.parametrize("name", SCENARIOS)
def test_fixtures_match_independent_oracle(name, validator):
    plan, before, after = pair(name)
    original = copy.deepcopy((plan, before, after))
    results, changes = evaluate(plan, before, after)
    assert [r["status"] for r in results] == [oracle.expected_status(c, plan, before, after) for c in plan["checks"]]
    assert changes == oracle.unexpected_changes(plan, before, after)
    for result in results:
        assert not list(validator("check_result").iter_errors(result))
    assert (plan, before, after) == original


@pytest.mark.parametrize("phase", ["before", "after"])
@pytest.mark.parametrize("field", ["OwnerId", "Status", "Closure_Reason__c", "Priority", "Subject"])
def test_missing_field_matches_oracle(phase, field):
    plan, before, after = pair()
    snap = before if phase == "before" else after
    snap["records"]["Case"][0]["fields"].pop(field, None)
    results, _ = evaluate(plan, before, after)
    assert [r["status"] for r in results] == [oracle.expected_status(c, plan, before, after) for c in plan["checks"]]


@pytest.mark.parametrize("field", ["WhatId", "Subject"])
def test_unknown_new_candidate_prevents_exact_count_pass(field):
    plan, before, after = pair()
    candidate = copy.deepcopy(after["records"]["Task"][0])
    candidate["id"] = "00TSYN000000999AAA"
    del candidate["fields"][field]
    after["records"]["Task"].append(candidate)
    results, _ = evaluate(plan, before, after)
    assert next(r for r in results if r["kind"] == "record_created")["status"] == "inconclusive"


def test_proven_change_wins_over_other_missing_evidence():
    plan, before, after = pair()
    after["records"]["Case"][0]["fields"]["OwnerId"] = "005OTHER"
    del after["records"]["Case"][0]["fields"]["Priority"]
    results, changes = evaluate(plan, before, after)
    assert next(r for r in results if r["kind"] == "no_unexpected_change")["status"] == "failed"
    assert changes[0]["field"] == "OwnerId"


@pytest.mark.parametrize("bad", ["run", "phase", "primary"])
def test_unrelated_snapshots_never_pass(bad):
    plan, before, after = pair()
    if bad == "run":
        after["run_id"] = "other"
    elif bad == "phase":
        after["phase"] = "before"
    else:
        after["primary_record"]["id"] = "other"
    results, changes = evaluate(plan, before, after)
    assert {r["status"] for r in results} == {"inconclusive"}
    assert changes == []


def test_no_oracle_dependency_and_default_wiring():
    from orchestrator.run import execute_run
    assert execute_run.__kwdefaults__["evaluator"] is evaluate
    assert "tests" not in inspect.getmodule(evaluate).__dict__


def test_duplicate_observations_do_not_establish_success():
    plan, before, after = pair()
    after["records"]["Task"].append(copy.deepcopy(after["records"]["Task"][0]))
    results, _ = evaluate(plan, before, after)
    assert next(r for r in results if r["kind"] == "record_created")["status"] == "inconclusive"
