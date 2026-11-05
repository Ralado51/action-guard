"""Erros recuperaveis do planner, com categoria e mensagem segura para o frontend.

Nunca carregam corpo bruto de resposta, chave ou cabecalhos. `details` traz somente
problemas de validacao gerados por este codigo (truncados).
"""
from __future__ import annotations

from typing import Any

CATEGORIES = {
    "config": "Configuracao do planner ausente ou invalida.",
    "auth": "A Vultr recusou as credenciais (401/403). Verifique a chave no ambiente do servidor.",
    "timeout": "A inferencia nao respondeu a tempo.",
    "rate_limit": "A inferencia limitou as requisicoes (429) e o orcamento de tentativas acabou.",
    "upstream": "A inferencia falhou (erro HTTP ou de rede).",
    "invalid_response": "A resposta do modelo veio vazia, truncada ou fora do formato esperado.",
    "schema": "O plano proposto nao respeita o schema de test_plan.",
    "semantics": "O plano proposto viola regras de coerencia, metadados ou invariantes do MVP.",
    "insufficient_context": "O contexto de metadados ou da acao e insuficiente para gerar o plano.",
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
