"""Execucao de um plano aprovado contra o Salesforce (via Agent API).

Ordem e garantias:
1. Portoes antes de qualquer efeito: aprovacao valida (hash), plano coerente, entradas, Case ligado ao plano.
2. Snapshot anterior completo e precondicoes satisfeitas, senao NAO executa.
3. O pedido e gravado ANTES de ser enviado; a mensagem de acao e enviada uma unica vez.
4. Snapshots posteriores com janela assincrona; avaliacao deterministica; relatorio e evidencia gravados.
A narrativa do agente nunca entra no calculo do resultado.
"""
from __future__ import annotations

import copy
from typing import Any, Callable

from connector.agent_api import REJECTED, SENT_OK, UNCERTAIN, AgentClient
from connector.ids import InvalidSalesforceId, same_record, to_sfid18
from connector.rest import SalesforceRest
from connector.snapshot import collect_snapshot, utc_now
from contracts.plan_hash import approval_is_valid
from contracts.semantics import validate_plan_semantics, validate_snapshot_pair

from engine import evaluate

from .store import EvidenceStore

# evaluator(plan, before, after) -> (check_results, unexpected_changes)
Evaluator = Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], tuple[list[dict[str, Any]], list[dict[str, Any]]]]


class RunBlocked(Exception):
    """Nada foi enviado ao agente."""


def build_request_text(case_id: str, closure_reason: str) -> str:
    return f"Close the synthetic test Case {case_id} with closure reason '{closure_reason}'. Execute the action once."


def create_synthetic_case(rest: SalesforceRest) -> str:
    """Cria um Case sintetico novo. Chamada explicita; nunca reutilize um Case ja encerrado."""
    return rest.create("Case", {"Subject": "Action Guard - Evidence Test",
                                "Description": "Synthetic case for before and after verification.", "Origin": "Web"})


def _gates(plan: dict[str, Any], case_id: str) -> str:
    if not approval_is_valid(plan):
        raise RunBlocked("plan without a valid approval (missing, or changed after approval)")
    issues = validate_plan_semantics(plan)
    if issues:
        raise RunBlocked("inconsistent plan: " + "; ".join(issues))
    action = plan["action"]
    if action["executed_via"] != "agentforce_agent_api":
        raise RunBlocked("this orchestrator only runs agentforce_agent_api")
    reason = (action.get("input") or {}).get("closure_reason")
    if not isinstance(reason, str) or not reason.strip():
        raise RunBlocked("action.input.closure_reason missing or empty")
    bound = (action.get("input") or {}).get("case_id")
    if not isinstance(bound, str) or not bound.strip():
        raise RunBlocked("action.input.case_id is required before approval")
    try:
        if not same_record(bound, case_id):
            raise RunBlocked("the given Case differs from the Case approved in the plan")
    except InvalidSalesforceId:
        raise RunBlocked("Invalid Case Id") from None
    return reason


def _preconditions_ok(plan: dict[str, Any], before: dict[str, Any]) -> list[str]:
    problems = []
    prim = before["primary_record"]
    rec = next((r for r in before["records"].get(prim["object"], []) if r["id"] == prim["id"]), None)
    for pre in plan.get("preconditions", []):
        if "object" not in pre:
            continue
        if pre["object"] != prim["object"] or rec is None or pre["field"] not in rec["fields"]:
            problems.append(f"{pre['id']}: not verifiable in the previous snapshot")
        elif rec["fields"][pre["field"]] != pre["expected"]:
            problems.append(f"{pre['id']}: expected {pre['expected']!r}, observed {rec['fields'][pre['field']]!r}")
    return problems


def execute_run(plan: dict[str, Any], *, case_id: str, run_id: str, rest: SalesforceRest, agent: AgentClient,
                evaluator: Evaluator = evaluate, store: EvidenceStore, sleep: Callable[[float], None],
                now: Callable[[], str] = utc_now) -> dict[str, Any]:
    reason = _gates(plan, case_id)
    case_id = to_sfid18(case_id)          # a REST devolve 18 caracteres; todas as comparacoes usam essa forma
    primary = {"object": "Case", "id": case_id}
    store.save("plan", plan)

    before = collect_snapshot(rest, plan, run_id, "before", primary, now=now)
    store.save("before", before)
    if not before["complete"]:
        raise RunBlocked("incomplete previous snapshot: " + "; ".join(e["message"] for e in before.get("collection_errors", [])))
    missing = [f"{mon['object']}.{field} em {rec['id']}"
               for mon in plan["monitored"]["objects"]
               for rec in before["records"].get(mon["object"], [])
               for field in mon["fields"] if field not in rec["fields"]]
    if missing:
        raise RunBlocked("previous snapshot with fields not collected: " + "; ".join(missing))
    if not any(same_record(r["id"], case_id) for r in before["records"].get("Case", [])):
        raise RunBlocked("Approved Case missing from the previous snapshot")
    problems = _preconditions_ok(plan, before)
    if problems:
        raise RunBlocked("preconditions not satisfied: " + "; ".join(problems))

    text = build_request_text(case_id, reason)
    store.save("agent_request", {"run_id": run_id, "text": text, "saved_before_sending": True, "at": now()})
    call = agent.run_once(text)                      # unica chamada que executa a acao
    store.save("agent_call", call.to_dict())

    window = plan["async_window"]
    attempts = window["max_wait_seconds"] // window["poll_interval_seconds"] + 1
    after = results = unexpected = None
    for i in range(attempts):
        after = collect_snapshot(rest, plan, run_id, "after", primary, before=before, now=now)
        results, unexpected = evaluator(plan, before, after)
        if call.outcome == REJECTED or all(r["status"] == "passed" for r in results):
            break
        if i < attempts - 1:
            sleep(window["poll_interval_seconds"])
    store.save("after", after)

    limitations = [
        "no_unexpected_change covers only the records and fields monitored by the plan; it does not observe other objects or Tasks not linked to the Case.",
        "The Task count only counts new Tasks that match the expected link and Subject; other new Tasks linked to the Case are flagged but do not change the status.",
        "The after-collection stops as soon as all checks pass; late effects after that moment are not seen.",
        "The action was triggered through the Agentforce Agent API; the agent's response is narrative and does not replace the evidence in the records.",
        "No exactly-once guarantee: a single client call reduces, but does not eliminate, repetition.",
    ]
    limitations += [f"snapshot: {i}" for i in validate_snapshot_pair(plan, before, after)]
    if call.outcome == UNCERTAIN:
        limitations.append("The agent call result is uncertain (timeout or error after sending): reconcile using evidence and human review before any new attempt.")
    if call.outcome == REJECTED and call.session_id is None:
        limitations.append(f"The agent call did not execute (the session did not open and no request was sent): {call.error}")
    elif call.outcome == REJECTED:
        limitations.append(f"The request was refused by the Agent API ({call.error}). This does not prove that nothing was executed: the collected records apply.")
    for r in results:
        ids = (r.get("evidence", {}).get("after") or {}).get("linked_unmatched_ids") if isinstance(r.get("evidence", {}).get("after"), dict) else None
        if ids:
            limitations.append(f"WARNING {r['check_id']}: {len(ids)} new Task(s) linked to the Case do not match the expected Subject ({', '.join(ids)}). The status of the checks does not change; review manually.")
    if call.session_close_error:
        limitations.append(f"Failed to close the agent session (does not change the result): {call.session_close_error}")
    if not after["complete"]:
        limitations.append("Incomplete after-snapshot: dependent checks are inconclusive.")

    coverage = copy.deepcopy(plan.get("rule_coverage"))
    if coverage is None:
        coverage_status = "not_assessed"
    elif all(i["status"] == "covered" for i in coverage) and coverage:
        coverage_status = "complete"
    else:
        coverage_status = "partial" if coverage else "not_assessed"
    if coverage_status == "partial":
        gaps = [f"{i['clause_id']} ({'conflict' if i['status'] == 'conflicts_with_policy' else 'not verified'})"
                for i in coverage if i["status"] != "covered"]
        limitations.insert(0, f"PARTIAL COVERAGE: {len(gaps)} of {len(coverage)} clauses of the rule are NOT verified by this plan: "
                              + ", ".join(gaps) + ". A 'passed' result only applies to the listed checks.")
    statuses = {r["status"] for r in results}
    status = "failed" if "failed" in statuses else "inconclusive" if "inconclusive" in statuses else "passed"
    report = {
        "schema_version": "1.0", "run_id": run_id, "plan_id": plan["plan_id"], "plan_version": plan["plan_version"],
        "plan_hash": plan["plan_hash"], "executed_via": plan["action"]["executed_via"],
        "action": {"identifier": plan["action"]["identifier"], "started_at": call.started_at, "finished_at": call.finished_at},
        "status": status, "results": copy.deepcopy(results), "unexpected_changes": unexpected,
        "limitations": limitations, "containment_events": [], "generated_at": now(),
        "coverage_status": coverage_status,
    }
    if coverage is not None:
        report["rule_coverage"] = coverage
    store.save("report", report)
    return report

