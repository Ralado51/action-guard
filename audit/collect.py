"""Coleta SOMENTE LEITURA para a auditoria. Falha de consulta nunca vira "zero registros"."""
from __future__ import annotations

from typing import Any

from connector.ids import key15, to_sfid18
from connector.rest import QueryError, SalesforceRest
from connector.snapshot import _ident, _sfid

BATCH = 100
MAX_CASES = 500


def _ids(values: list[str]) -> str:
    return ", ".join(f"'{_sfid(v)}'" for v in values)


def fetch_cases_by_ids(rest: SalesforceRest, obj: str, fields: list[str], ids: list[str]) -> dict[str, dict[str, Any]]:
    """Id (15 chars) -> linha. Ids sem linha ficam ausentes (nao encontrado / sem acesso)."""
    out: dict[str, dict[str, Any]] = {}
    cols = ", ".join(["Id", *[_ident(f) for f in fields if f != "Id"]])
    for i in range(0, len(ids), BATCH):
        for row in rest.query(f"SELECT {cols} FROM {_ident(obj)} WHERE Id IN ({_ids(ids[i:i + BATCH])})"):
            out[key15(row["Id"])] = row
    return out


def fetch_cases_window(rest: SalesforceRest, obj: str, fields: list[str], since: str, limit: int,
                       modified_by: str | None) -> list[dict[str, Any]]:
    if not (len(since) == 20 and since[4] == "-" and since.endswith("Z") and "T" in since):
        raise ValueError("since deve estar em UTC no formato 2026-11-01T00:00:00Z")
    if not 1 <= limit <= MAX_CASES:
        raise ValueError(f"limit deve estar entre 1 e {MAX_CASES}")
    cols = ", ".join(["Id", *[_ident(f) for f in fields if f != "Id"]])
    soql = f"SELECT {cols} FROM {_ident(obj)} WHERE IsClosed = true AND ClosedDate >= {_ident_ts(since)}"
    if modified_by:
        soql += f" AND LastModifiedById = '{_sfid(modified_by)}'"
    return rest.query(soql + f" ORDER BY ClosedDate DESC LIMIT {int(limit)}")


def _ident_ts(value: str) -> str:
    if not all(ch.isdigit() or ch in "-:TZ" for ch in value):
        raise ValueError("timestamp invalido")
    return value


def fetch_linked(rest: SalesforceRest, obj: str, link_field: str, fields: list[str], case_ids: list[str]
                 ) -> list[dict[str, Any]]:
    cols = ", ".join(["Id", *[_ident(f) for f in dict.fromkeys([link_field, *fields]) if f != "Id"]])
    rows: list[dict[str, Any]] = []
    for i in range(0, len(case_ids), BATCH):
        rows += rest.query(f"SELECT {cols} FROM {_ident(obj)} WHERE {_ident(link_field)} IN ({_ids(case_ids[i:i + BATCH])})")
    return rows


__all__ = ["QueryError", "fetch_cases_by_ids", "fetch_cases_window", "fetch_linked", "to_sfid18", "MAX_CASES"]
