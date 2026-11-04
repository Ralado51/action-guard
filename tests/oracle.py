"""Oraculo de referencia para os exemplos de contrato.

Calcula, de forma independente, o resultado esperado de cada verificacao a
partir dos snapshots. Serve para provar que os exemplos em contracts/examples/
sao verdadeiros e para o motor real ser comparado contra ele. Nao e o motor.

Principio: falha COMPROVADA e evidencia INSUFICIENTE sao coisas diferentes.
- failed: a condicao foi observada e nao foi atendida, ou a exclusao do registro
  foi CONFIRMADA (confirmed_absent).
- inconclusive: faltou observar (objeto ou campo nao coletado, registro sumiu sem
  confirmacao, coleta incompleta). Nunca vira passed.
Ausencia de um campo (chave ausente) e diferente de valor nulo (chave presente
com null): so o segundo foi observado.
"""
from __future__ import annotations

from typing import Any

PRESENT, ABSENT, UNOBSERVED = "present", "absent", "unobserved"
DELETED_FIELD = "__record__"


def _errored(snapshot: dict[str, Any]) -> set[str]:
    return {e["object"] for e in snapshot.get("collection_errors", [])}


def observe(snapshot: dict[str, Any], obj: str, rid: str) -> tuple[str, dict[str, Any] | None]:
    """Estado de um registro: present (com campos), absent (exclusao confirmada) ou unobserved."""
    if obj in _errored(snapshot) or obj not in snapshot["records"]:
        return UNOBSERVED, None
    for r in snapshot["records"][obj]:
        if r["id"] == rid:
            return PRESENT, r["fields"]
    if any(a["object"] == obj and a["id"] == rid for a in snapshot.get("confirmed_absent", [])):
        return ABSENT, None
    return UNOBSERVED, None


def _primary(before, after) -> tuple[str, str] | None:
    if before["primary_record"] != after["primary_record"]:
        return None
    p = before["primary_record"]
    return p["object"], p["id"]


def scan_monitored(plan, before, after) -> tuple[list[dict[str, Any]], bool]:
    """(mudancas inesperadas comprovadas, houve algo nao observado?)."""
    check = next(c for c in plan["checks"] if c["kind"] == "no_unexpected_change")
    allowed = set(check["allowed_changes"])
    proven: list[dict[str, Any]] = []
    unobserved = not (before["complete"] and after["complete"])
    for mon in plan["monitored"]["objects"]:
        obj = mon["object"]
        if (obj in _errored(before) | _errored(after)
                or obj not in before["records"] or obj not in after["records"]):
            unobserved = True
            continue
        for rec in before["records"][obj]:
            state, a_fields = observe(after, obj, rec["id"])
            if state == ABSENT:
                proven.append({"object": obj, "record_id": rec["id"], "field": DELETED_FIELD,
                               "before": "present", "after": "deleted"})
                continue
            if state == UNOBSERVED:
                unobserved = True
                continue
            for field in mon["fields"]:
                if f"{obj}.{field}" in allowed:
                    continue
                if field in rec["fields"] and field in a_fields:
                    if rec["fields"][field] != a_fields[field]:
                        proven.append({"object": obj, "record_id": rec["id"], "field": field,
                                       "before": rec["fields"][field], "after": a_fields[field]})
                else:
                    unobserved = True
    return proven, unobserved


def unexpected_changes(plan, before, after) -> list[dict[str, Any]]:
    return scan_monitored(plan, before, after)[0]


def new_linked_records(check, before, after, primary_id) -> list[str]:
    """Ids dos registros novos vinculados ao registro principal e que satisfazem `match`."""
    obj, link = check["object"], check["link_field"]
    match = check.get("match", {})
    old = {r["id"] for r in before["records"].get(obj, [])}
    return [r["id"] for r in after["records"].get(obj, [])
            if r["id"] not in old and r["fields"].get(link) == primary_id
            and all(k in r["fields"] and r["fields"][k] == v for k, v in match.items())]


def _record_created_status(check, before, after, primary_id) -> str:
    obj, link = check["object"], check["link_field"]
    match = check.get("match", {})
    expected = check.get("expected_count", 1)
    old = {r["id"] for r in before["records"][obj]}
    new = [r for r in after["records"][obj] if r["id"] not in old]
    count = len(new_linked_records(check, before, after, primary_id))
    # Candidatos cuja correspondencia nao da para afirmar (campo de vinculo ou de match nao coletado).
    unknown = [r for r in new
               if link not in r["fields"]
               or (r["fields"][link] == primary_id and any(k not in r["fields"] for k in match))]
    if count > expected:
        return "failed"          # duplicata comprovada
    if unknown:
        return "inconclusive"    # pode haver mais correspondentes do que o observado
    return "passed" if count == expected else "failed"


def expected_status(check, plan, before, after, case_id: str | None = None) -> str:
    """case_id e ignorado (mantido por compatibilidade); o alvo vem de primary_record."""
    kind, obj = check["kind"], check["object"]

    if kind == "no_unexpected_change":
        proven, unobserved = scan_monitored(plan, before, after)
        if proven:
            return "failed"  # falha comprovada prevalece sobre evidencia insuficiente
        return "inconclusive" if unobserved else "passed"

    primary = _primary(before, after)
    if primary is None:
        return "inconclusive"
    p_obj, p_id = primary

    if kind == "record_created":
        if (obj in _errored(before) | _errored(after)
                or obj not in before["records"] or obj not in after["records"]):
            return "inconclusive"
        return _record_created_status(check, before, after, p_id)

    if obj != p_obj:
        raise ValueError(f"verificacao de campo precisa mirar o registro principal ({p_obj}), nao {obj}")
    field = check["field"]
    a_state, a_fields = observe(after, p_obj, p_id)

    if kind in ("field_equals", "field_not_empty"):
        if a_state == ABSENT:
            return "failed"
        if a_state == UNOBSERVED or field not in a_fields:
            return "inconclusive"
        value = a_fields[field]
        if kind == "field_equals":
            return "passed" if value == check["expected"] else "failed"
        return "passed" if value not in (None, "") else "failed"

    if kind == "field_unchanged":
        b_state, b_fields = observe(before, p_obj, p_id)
        if b_state != PRESENT or field not in b_fields:
            return "inconclusive"
        if a_state == ABSENT:
            return "failed"
        if a_state == UNOBSERVED or field not in a_fields:
            return "inconclusive"
        return "passed" if b_fields[field] == a_fields[field] else "failed"

    raise ValueError(f"kind desconhecido: {kind}")


def overall_status(statuses: list[str]) -> str:
    if "failed" in statuses:
        return "failed"
    if "inconclusive" in statuses:
        return "inconclusive"
    return "passed"
