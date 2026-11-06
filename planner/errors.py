"""Erros recuperaveis do planner, com categoria e mensagem segura para o frontend.

Nunca carregam corpo bruto de resposta, chave ou cabecalhos. `details` traz somente
problemas de validacao gerados por este codigo (truncados).
"""
from __future__ import annotations

from typing import Any

CATEGORIES = {
    "config": "Planner configuration missing or invalid.",
    "auth": "A Vultr recusou as credenciais (401/403). Verifique a chave no ambiente do servidor.",
    "timeout": "The inference did not respond in time.",
    "rate_limit": "Inference rate-limited the requests (429) and the retry budget ran out.",
    "upstream": "The inference failed (HTTP or network error).",
    "invalid_response": "The model response was empty, truncated or in an unexpected format.",
    "schema": "The proposed plan does not conform to the test_plan schema.",
    "semantics": "The proposed plan violates consistency rules, metadata or MVP invariants.",
    "insufficient_context": "The metadata or action context is insufficient to generate the plan.",
}


class PlannerError(Exception):
    def __init__(self, category: str, details: list[str] | None = None, message: str | None = None):
        assert category in CATEGORIES, category
        self.category = category
        self.message = message or CATEGORIES[category]
        self.details = [d[:200] for d in (details or [])][:10]
        super().__init__(f"{category}: {self.message}")

    @property
    def recoverable(self) -> bool:
        return self.category != "auth"  # auth exige acao do operador; os demais admitem nova tentativa humana

    def to_public(self) -> dict[str, Any]:
        return {"category": self.category, "message": self.message,
                "recoverable": self.recoverable, "details": list(self.details)}
