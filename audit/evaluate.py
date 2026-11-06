"""Avaliacao deterministica do ESTADO FINAL. Sem LLM, sem prosa do agente.

Sem snapshot "antes", so e possivel afirmar o que depende apenas do estado atual. Verificacoes que
exigem o antes (campo inalterado, nenhuma mudanca inesperada) ou um valor por registro (motivo
exato) ficam `not_auditable`: aparecem no relatorio como NAO verificadas, nunca como aprovadas.
Chave ausente != null; falha de leitura => inconclusive; falha comprovada vence inconclusivo.
"""
from __future__ import annotations

from typing import Any

from connector.ids import key15

PASSED, FAILED, INCONCLUSIVE = "passed", "failed", "inconclusive"
CORRECT, INCORRECT = "correct", "incorrect"


def classify_checks(plan: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    reason_value = ((plan.get("action") or {}).get("input") or {}).get("closure_reason")
    auditable, skipped = [], []
    for c in plan["checks"]:
        kind, cid = c["kind"], c["check_id"]
        if kind in ("field_unchanged", "no_unexpected_change"):
            skipped.append({"check_id": cid, "reason": "Needs the previous state; the audit only reads the final state."})
        elif kind == "field_equals" and reason_value is not None and c.get("expected") == reason_value:
            skipped.append({"check_id": cid, "reason": "Compares against the test plan's value; in an audit each record has its own reason (use the field-not-empty check)."})
        elif kind in ("field_equals", "field_not_empty", "record_created"):
            auditable.append(c)
        else:
            skipped.append({"check_id": cid, "reason": f"Tipo {kind} is not supported in the audit."})
    return auditable, skipped


def needed_fields(auditable: list[dict[str, Any]]) -> dict[str, list[str]]:
    out: dict[str, set[str]] = {}
    for c in auditable:
        if c["kind"] == "record_created":
            out.setdefault(c["object"], set()).update({c["link_field"], *c.get("match", {})})
        else:
            out.setdefault(c["object"], set()).add(c["field"])
    return {o: sorted(f) for o, f in out.items()}


def _result(check, status, reason, evidence=None):
    return {"check_id": check["check_id"], "kind": check["kind"], "status": status, "reason": reason,
            "evidence": evidence or {}}


def evaluate_case(auditable, primary_object, case_id, case_row, linked, linked_error):
    """case_row: campos do registro (ou None se nao encontrado). linked: {objeto: [linhas]} ou erro por objeto."""
    out = []
    for c in auditable:
        if c["kind"] == "record_created":
            obj = c["object"]
            if case_row is None:
                out.append(_result(c, INCONCLUSIVE, "Main record not found (or no access)."))
            elif obj in linked_error:
                out.append(_result(c, INCONCLUSIVE, "Reading the linked records failed."))
            else:
                link, match = c["link_field"], c.get("match", {})
                rows = [r for r in linked.get(obj, []) if isinstance(r.get(link), str) and key15(r[link]) == key15(case_id)]
                unknown = [r for r in rows if link not in r or any(f not in r for f in match)]
                hits = [r for r in rows if r not in unknown and all(r.get(f) == v for f, v in match.items())]
                other = len(rows) - len(hits) - len(unknown)
                expected = c.get("expected_count", 1)
                ev = {"matching": len(hits), "expected": expected, "linked_other": other, "unobserved": len(unknown)}
                label = f"{len(hits)} matching record(s); expected {expected}."
                if len(hits) > expected:
                    out.append(_result(c, FAILED, label, ev))
                elif unknown:
                    out.append(_result(c, INCONCLUSIVE, "Linked records without all the observed fields.", ev))
                elif len(hits) == expected:
                    out.append(_result(c, PASSED, label, ev))
                else:
                    out.append(_result(c, FAILED, label, ev))
            continue
        field = c["field"]
        if case_row is None:
            out.append(_result(c, INCONCLUSIVE, "Main record not found (or no access)."))
        elif field not in case_row:
            out.append(_result(c, INCONCLUSIVE, f"Field {field} not returned by the API."))
        else:
            value = case_row[field]
            ok = value == c["expected"] if c["kind"] == "field_equals" else value not in (None, "")
            out.append(_result(c, PASSED if ok else FAILED,
                               f"{primary_object}.{field}: condicao {'atendida' if ok else 'not met'}.",
                               {"observed": value} if not ok else {}))
    return out


def case_status(results: list[dict[str, Any]]) -> str:
    if any(r["status"] == FAILED for r in results):
        return INCORRECT
    if any(r["status"] == INCONCLUSIVE for r in results) or not results:
        return INCONCLUSIVE
    return CORRECT
