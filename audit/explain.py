"""Resumo em linguagem natural. O modelo recebe SOMENTE contagens e descricoes de verificacoes
(nunca IDs nem valores de registros) e NAO decide veredito algum. A saida e validada: qualquer
numero que nao exista nos dados, ou qualquer cara de Id Salesforce, derruba o texto do modelo e
vale o resumo deterministico do servidor.
"""
from __future__ import annotations

import json
import re
from typing import Any

from planner.client import Budget, VultrChatClient
from planner.errors import PlannerError

MAX_CHARS = 700
_NUM = re.compile(r"\d+(?:[.,]\d+)?")
_ID = re.compile(r"\b[A-Za-z0-9]{15,18}\b")

SYSTEM = (
    "Voce resume resultados de uma auditoria de acoes de agente. Responda em portugues do Brasil, em ate 4 frases, "
    "somente com texto simples. Use APENAS os numeros fornecidos em 'dados'; nao calcule nem invente numeros, "
    "nao cite identificadores de registros e nao faca recomendacoes sobre o agente. Diga o que foi verificado, "
    "o resultado, e o que NAO foi verificado (campos 'nao_auditavel' e 'cobertura')."
)


def build_input(report: dict[str, Any]) -> dict[str, Any]:
    return {"totais": report["totals"], "taxa_resultado_correto": report["outcome_rate"],
            "por_verificacao": [{"descricao": c["description"], "aprovadas": c["passed"], "falhas": c["failed"],
                                 "inconclusivas": c["inconclusive"]} for c in report["by_check"]],
            "nao_auditavel": [n["check_id"] for n in report["not_auditable"]],
            "cobertura": report.get("coverage_status"),
            "clausulas_nao_cobertas": [i["text"] for i in report.get("rule_coverage", []) if i["status"] != "covered"][:12]}


def allowed_numbers(report: dict[str, Any]) -> set[str]:
    text = json.dumps(build_input(report), ensure_ascii=False) + " " + report["summary"]["text"]
    out = set(_NUM.findall(text))
    if report["outcome_rate"] is not None:
        pct = f"{report['outcome_rate'] * 100:.1f}"
        out |= {pct, pct.rstrip("0").rstrip("."), pct.replace(".", ",")}
    return {n.replace(",", ".") for n in out} | out


def validate(text: Any, report: dict[str, Any]) -> str | None:
    if not isinstance(text, str):
        return None
    text = text.strip()
    if not text or len(text) > MAX_CHARS or "\x00" in text or _ID.search(text):
        return None
    ok = allowed_numbers(report)
    if any(n not in ok and n.replace(",", ".") not in ok for n in _NUM.findall(text)):
        return None
    return text


def explain(report: dict[str, Any], client: VultrChatClient) -> dict[str, Any]:
    """Devolve report com summary do modelo se valido; senao mantem o do servidor e registra o motivo."""
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": "dados (JSON):\n" + json.dumps(build_input(report), ensure_ascii=False)}]
    try:
        res = client.chat(messages, Budget(1))
    except PlannerError as e:
        report["summary"]["model_error"] = e.category
        return report
    text = validate(res.content, report)
    if text is None:
        report["summary"]["model_error"] = "rejected_by_validation"
        return report
    report["summary"] = {"text": text, "basis": "model", "model": res.model, "usage": res.usage,
                         "server_text": report["summary"]["text"]}
    return report
