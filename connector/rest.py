"""Consultas REST com paginacao. Falha NUNCA vira lista vazia."""
from __future__ import annotations

import json
import urllib.parse
from typing import Any

from .auth import Token
from .config import SalesforceConfig
from .transport import Transport, TransportError


class QueryError(Exception):
    pass


class SalesforceRest:
    def __init__(self, cfg: SalesforceConfig, token: Token, transport: Transport):
        self.cfg, self.token, self.transport = cfg, token, transport

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token.access_token}", "Accept": "application/json"}

    def query(self, soql: str, include_deleted: bool = False, max_pages: int = 50) -> list[dict[str, Any]]:
        path = "queryAll" if include_deleted else "query"
        url = (f"{self.cfg.my_domain}/services/data/v{self.cfg.api_version}/{path}?"
               + urllib.parse.urlencode({"q": soql}))
        records: list[dict[str, Any]] = []
        for _ in range(max_pages):
            try:
                resp = self.transport.request("GET", url, headers=self._headers(),
                                              timeout=self.cfg.rest_timeout_seconds)
            except TransportError as e:
                raise QueryError(f"consulta falhou: {e}") from e
            if not resp.ok or not isinstance(resp.body, dict):
                raise QueryError(f"consulta recusada (HTTP {resp.status}): {_first_error(resp.body)}")
            page = resp.body.get("records")
            if not isinstance(page, list):
                raise QueryError("resposta sem lista 'records'")
            records.extend(page)
            if type(resp.body.get("done")) is not bool:
                raise QueryError("paginacao incompleta: done ausente ou invalido")
            if resp.body["done"]:
                return records
            nxt = resp.body.get("nextRecordsUrl")
            if not nxt:
                raise QueryError("paginacao incompleta: done=false sem nextRecordsUrl")
            url = f"{self.cfg.my_domain}{nxt}"
        raise QueryError(f"paginacao excedeu {max_pages} paginas")

    def create(self, sobject: str, fields: dict[str, Any]) -> str:
        url = f"{self.cfg.my_domain}/services/data/v{self.cfg.api_version}/sobjects/{sobject}"
        try:
            resp = self.transport.request("POST", url, headers={**self._headers(), "Content-Type": "application/json"},
                                          body=json.dumps(fields).encode(), timeout=self.cfg.rest_timeout_seconds)
        except TransportError as e:
            raise QueryError(f"criacao falhou: {e}") from e
        if not resp.ok or not isinstance(resp.body, dict) or not resp.body.get("id"):
            raise QueryError(f"criacao recusada (HTTP {resp.status}): {_first_error(resp.body)}")
        return resp.body["id"]


def _first_error(body: Any) -> str:
    if isinstance(body, list) and body and isinstance(body[0], dict):
        return f"{body[0].get('errorCode')}: {body[0].get('message')}"
    return "sem detalhe"

