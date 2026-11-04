"""Cliente do Agent API (Agentforce). A mensagem que executa a acao NUNCA e repetida.

Resultado da chamada principal e independente do encerramento da sessao. A resposta do
agente e narrativa: serve de registro, nao de prova (a prova sao os snapshots).
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .auth import Token
from .config import SalesforceConfig
from .transport import Transport, TransportError

# Resultado da chamada que envia o pedido:
SENT_OK = "response_received"        # HTTP 2xx
REJECTED = "rejected_before_action"  # sessao nao abriu ou 4xx: a acao provavelmente nao rodou
UNCERTAIN = "uncertain"              # timeout/5xx/erro de rede apos enviar: a acao PODE ter rodado


@dataclass
class AgentCallRecord:
    """Evidencia da chamada, serializavel e sem token."""
    outcome: str
    session_id: str | None = None
    external_session_key: str | None = None
    request_text: str = ""
    http_status: int | None = None
    response: Any = None
    agent_text: list[str] = field(default_factory=list)
    error: str | None = None
    session_close_error: str | None = None
    started_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def extract_agent_text(body: Any) -> list[str]:
    if not isinstance(body, dict):
        return []
    out = []
    for m in body.get("messages", []) or []:
        if isinstance(m, dict) and m.get("type") == "Inform" and isinstance(m.get("message"), str):
            out.append(m["message"])
    return out


class AgentClient:
    def __init__(self, cfg: SalesforceConfig, token: Token, transport: Transport,
                 now: Callable[[], str], key_factory: Callable[[], str] = lambda: str(uuid.uuid4())):
        self.cfg, self.token, self.transport, self.now, self.key_factory = cfg, token, transport, now, key_factory

    def _h(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h = {"Authorization": f"Bearer {self.token.access_token}", "Accept": "application/json",
             "Content-Type": "application/json"}
        h.update(extra or {})
        return h

    def run_once(self, text: str) -> AgentCallRecord:
        rec = AgentCallRecord(outcome=REJECTED, request_text=text, started_at=self.now())
        rec.external_session_key = self.key_factory()
        try:
            self._open(rec)
            if rec.session_id:
                self._send(rec, text)
        finally:
            if rec.session_id:
                self._close(rec)
            rec.finished_at = self.now()
        return rec

    def _open(self, rec: AgentCallRecord) -> None:
        body = {"externalSessionKey": rec.external_session_key,
                "instanceConfig": {"endpoint": self.cfg.my_domain},
                "streamingCapabilities": {"chunkTypes": ["Text"]}, "bypassUser": True}
        try:
            resp = self.transport.request("POST", f"{self.cfg.agent_api_base}/agents/{self.cfg.agent_id}/sessions",
                                          headers=self._h(), body=json.dumps(body).encode(),
                                          timeout=self.cfg.rest_timeout_seconds)
        except TransportError as e:
            rec.error = f"falha ao abrir sessao (nenhuma mensagem foi enviada): {e}"
            return
        sid = resp.body.get("sessionId") if isinstance(resp.body, dict) else None
        if not resp.ok or not sid:
            rec.http_status = resp.status
            rec.error = f"sessao nao aberta (HTTP {resp.status}); nenhuma mensagem foi enviada"
            return
        rec.session_id = sid

    def _send(self, rec: AgentCallRecord, text: str) -> None:
        payload = {"message": {"sequenceId": 1, "type": "Text", "text": text}}
        try:
            resp = self.transport.request("POST", f"{self.cfg.agent_api_base}/sessions/{rec.session_id}/messages",
                                          headers=self._h(), body=json.dumps(payload).encode(),
                                          timeout=self.cfg.agent_timeout_seconds)
        except TransportError as e:
            rec.outcome = UNCERTAIN
            rec.error = (f"{'timeout' if e.timed_out else 'erro de rede'} apos enviar o pedido: {e}. "
                         "A acao pode ter sido executada; reconciliar por evidencia e revisao humana antes de tentar de novo.")
            return
        rec.http_status, rec.response = resp.status, resp.body
        rec.agent_text = extract_agent_text(resp.body)
        if resp.ok:
            rec.outcome = SENT_OK
        elif 400 <= resp.status < 500:
            rec.outcome = REJECTED
            rec.error = f"pedido recusado (HTTP {resp.status})"
        else:
            rec.outcome = UNCERTAIN
            rec.error = f"erro do servidor (HTTP {resp.status}) apos enviar o pedido; a acao pode ter sido executada"

    def _close(self, rec: AgentCallRecord) -> None:
        try:
            resp = self.transport.request("DELETE", f"{self.cfg.agent_api_base}/sessions/{rec.session_id}",
                                          headers=self._h({"x-session-end-reason": "UserRequest"}),
                                          timeout=self.cfg.rest_timeout_seconds)
            if not resp.ok:
                rec.session_close_error = f"encerramento recusado (HTTP {resp.status})"
        except TransportError as e:
            rec.session_close_error = f"falha ao encerrar sessao: {e}"
