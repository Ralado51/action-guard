"""Cliente de chat da Vultr Serverless Inference (compativel com OpenAI).

POST {base}/chat/completions, Bearer. Orcamento unico de chamadas por operacao:
cada requisicao HTTP (inclusive retry de 429/5xx) consome uma unidade. 401/403 e timeout
nao sofrem retry. Nao assume suporte a JSON Schema nativo: a validacao e local.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from connector.transport import Transport, TransportError

from .config import PlannerConfig
from .errors import PlannerError


@dataclass
class Budget:
    left: int
    used: int = 0

    def take(self) -> bool:
        if self.left <= 0:
            return False
        self.left -= 1
        self.used += 1
        return True


@dataclass
class ChatResult:
    content: str
    model: str | None
    usage: dict[str, int] = field(default_factory=dict)


class VultrChatClient:
    def __init__(self, cfg: PlannerConfig, transport: Transport, sleep: Callable[[float], None] = time.sleep):
        self.cfg, self.transport, self.sleep = cfg, transport, sleep

    def chat(self, messages: list[dict[str, str]], budget: Budget) -> ChatResult:
        payload = json.dumps({"model": self.cfg.model, "messages": messages, "max_tokens": self.cfg.max_tokens,
                              "temperature": 0, "stream": False}).encode()
        headers = {"Authorization": f"Bearer {self.cfg.api_key}", "Content-Type": "application/json",
                   "Accept": "application/json"}
        while True:
            if not budget.take():
                raise PlannerError("upstream", message="Call budget exhausted before a usable response.")
            try:
                resp = self.transport.request("POST", f"{self.cfg.base_url}/chat/completions", headers=headers,
                                              body=payload, timeout=self.cfg.timeout_seconds)
            except TransportError as e:
                raise PlannerError("timeout" if e.timed_out else "upstream",
                                   message=None if e.timed_out else "Network failure while calling inference.") from None
            if resp.status in (401, 403):
                raise PlannerError("auth")
            if resp.status == 429 or resp.status >= 500:
                if budget.left > 0:
                    self.sleep(self.cfg.retry_backoff_seconds)
                    continue
                raise PlannerError("rate_limit" if resp.status == 429 else "upstream",
                                   message=None if resp.status == 429 else f"A inferencia respondeu HTTP {resp.status}.")
            if not 200 <= resp.status < 300:
                raise PlannerError("upstream", message=f"A inferencia recusou o pedido (HTTP {resp.status}).")
            return parse_chat_response(resp.body)


def parse_chat_response(body: Any) -> ChatResult:
    def bad(msg: str) -> PlannerError:
        return PlannerError("invalid_response", message=msg)

    if not isinstance(body, dict):
        raise bad("Response body is not a JSON object.")
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise bad("Response without choices.")
    choice = choices[0]
    msg = choice.get("message")
    if not isinstance(msg, dict):
        raise bad("Response without message.")
    if msg.get("tool_calls"):
        raise bad("Response asked for tool_calls; the planner does not run tools.")
    finish = choice.get("finish_reason")
    if finish == "length":
        raise bad("Response truncated (finish_reason=length).")
    if finish != "stop":
        raise bad(f"finish_reason inesperado: {str(finish)[:30]!r}.")
    content = msg.get("content")
    if not isinstance(content, str) or not content.strip():
        raise bad("Empty content (reasoning is not used as a plan).")
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    clean = {k: v for k, v in usage.items() if k in ("prompt_tokens", "completion_tokens", "total_tokens")
             and isinstance(v, int) and not isinstance(v, bool)}
    model = body.get("model") if isinstance(body.get("model"), str) else None
    return ChatResult(content=content, model=model, usage=clean)
