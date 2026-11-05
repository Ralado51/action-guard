"""Identidade de registros Salesforce: Ids de 15 e 18 caracteres apontam para o MESMO registro.

A identidade real sao os 15 primeiros caracteres (sensiveis a maiusculas); os 3 finais sao
um sufixo de checagem de caixa. A API REST devolve sempre 18. Compare por `same_record`,
nunca por igualdade de string, e chaves de reserva usem `key15`.
"""
from __future__ import annotations

import re

_ID = re.compile(r"^[A-Za-z0-9]{15}([A-Za-z0-9]{3})?$")
_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"


class InvalidSalesforceId(ValueError):
    pass


def _check(value: object) -> str:
    if not isinstance(value, str) or not _ID.match(value):
        raise InvalidSalesforceId("Id Salesforce deve ter 15 ou 18 caracteres alfanumericos")
    return value


def key15(value: str) -> str:
    return _check(value)[:15]


def to_sfid18(value: str) -> str:
    """Forma de 18 caracteres. Um Id de 18 caracteres e mantido como veio (o sufixo nao e revalidado)."""
    value = _check(value)
    if len(value) == 18:
        return value
    suffix = ""
    for chunk in (value[0:5], value[5:10], value[10:15]):
        bits = sum(1 << i for i, c in enumerate(chunk) if "A" <= c <= "Z")
        suffix += _ALPHABET[bits]
    return value + suffix


def same_record(a: str, b: str) -> bool:
    return key15(a) == key15(b)
