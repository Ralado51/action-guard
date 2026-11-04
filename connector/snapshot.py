"""Coleta de snapshots (contrato snapshot.schema.json).

Regras: campos explicitamente selecionados; chave ausente != null; falha de leitura ou
paginacao incompleta vira collection_errors (nunca "zero registros"); exclusao so e
afirmada com confirmacao via queryAll (IsDeleted = true).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable

from .rest import QueryError, SalesforceRest

_IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)*$")
_SFID = re.compile(r"^[A-Za-z0-9]{15,18}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ident(value: str) -> str:
    if not _IDENT.match(value):
        raise ValueError(f"identificador invalido para SOQL: {value!r}")
    return value


def _sfid(value: str) -> str:
    if not _SFID.match(value):
        raise ValueError(f"Id Salesforce invalido: {value!r}")
    return value


def scope_filters(plan: dict[str, Any], primary: dict[str, str]) -> dict[str, tuple[str, str]]:
    """objeto -> (campo de filtro, id do registro principal). Objeto sem escopo conhecido nao e coletado."""
    scopes = {primary["object"]: ("Id", primary["id"])}
    for c in plan["checks"]:
        if c["kind"] == "record_created" and c["object"] not in scopes:
            scopes[c["object"]] = (c["link_field"], primary["id"])
    return scopes


def collect_snapshot(rest: SalesforceRest, plan: dict[str, Any], run_id: str, phase: str,
                     primary: dict[str, str], before: dict[str, Any] | None = None,
                     now: Callable[[], str] = utc_now) -> dict[str, Any]:
    scopes = scope_filters(plan, primary)
    records: dict[str, list[dict[str, Any]]] = {}
    errors: list[dict[str, str]] = []
    absent: list[dict[str, str]] = []

    for mon in plan["monitored"]["objects"]:
        obj = mon["object"]
        if obj not in scopes:
            errors.append({"object": obj, "message": "sem escopo de consulta definido (nenhum registro principal ou link_field)"})
            continue
        flt, rid = scopes[obj]
        fields = list(mon["fields"])
        soql = (f"SELECT Id, {', '.join(_ident(f) for f in fields)} FROM {_ident(obj)} "
                f"WHERE {_ident(flt)} = '{_sfid(rid)}'")
        try:
            rows = rest.query(soql)
        except QueryError as e:
            errors.append({"object": obj, "message": str(e)})
            continue
        records[obj] = [{"id": r["Id"], "fields": {f: r[f] for f in fields if f in r}} for r in rows]

    if phase == "after" and before is not None:
        for obj, recs in list(records.items()):
            missing = sorted({r["id"] for r in before["records"].get(obj, [])} - {r["id"] for r in recs})
            if not missing:
                continue
            ids = ", ".join(f"'{_sfid(i)}'" for i in missing)
            try:
                found = rest.query(f"SELECT Id, IsDeleted FROM {_ident(obj)} WHERE Id IN ({ids})", include_deleted=True)
            except QueryError as e:
                errors.append({"object": obj, "message": f"ausencia nao confirmada: {e}"})
                del records[obj]
                continue
            deleted = {r["Id"] for r in found if r.get("IsDeleted") is True}
            for i in missing:
                if i in deleted:
                    absent.append({"object": obj, "id": i, "basis": "queryAll com IsDeleted = true retornou o registro"})
            if set(missing) - deleted:
                errors.append({"object": obj, "message": "registro sumiu e a exclusao nao foi confirmada por queryAll"})
                del records[obj]
                absent = [a for a in absent if a["object"] != obj]

    snap: dict[str, Any] = {
        "schema_version": "1.0", "snapshot_id": f"{run_id}-{phase}", "run_id": run_id, "phase": phase,
        "taken_at": now(), "complete": not errors, "primary_record": dict(primary), "records": records,
    }
    if errors:
        snap["collection_errors"] = errors
    if absent:
        snap["confirmed_absent"] = absent
    return snap
