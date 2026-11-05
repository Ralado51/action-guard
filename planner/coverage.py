"""Cobertura da regra por clausula: o que o plano verifica e, principalmente, o que NAO verifica.

Principio: a declaracao do modelo e apenas uma PROPOSTA nao verificada. O servidor:
- segmenta a regra (o modelo nao altera o texto das clausulas nem cria clausulas);
- so aceita `covered` se (a) os check_ids citados existem no plano e (b) o vocabulario da
  clausula e compativel com o tema de pelo menos um check citado e (c) a clausula nao cita
  assunto fora do escopo monitorado (e-mail, SLA, notificacao...) nem contradiz um invariante;
- NUNCA promove: qualquer duvida rebaixa para `not_verifiable`.
Isso reduz, nao elimina, o risco de falsa cobertura: o vocabulario e heuristico e finito. Por isso
a aprovacao exige confirmacao humana de cada clausula e a taxa de falsa cobertura e medida com um
conjunto rotulado (tests/data/rule_coverage_labeled.json).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

COVERED, NOT_VERIFIABLE, CONFLICT = "covered", "not_verifiable", "conflicts_with_policy"
STATUSES = (COVERED, NOT_VERIFIABLE, CONFLICT)
MAX_CLAUSES = 12
MAX_CLAUSE_CHARS = 300
MAX_REASON = 200
MAX_CITED = 4
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text)
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


# Tema de cada verificacao (sobre texto normalizado). Extras ganham tema a partir do nome do campo.
CHECK_TOPICS: dict[str, re.Pattern[str]] = {
    "chk_status_closed": re.compile(r"\b(encerr\w*|fech\w*|closed|status|conclu\w*)\b"),
    "chk_reason_filled": re.compile(r"\b(motivo\w*|razao|reason|closure)\b"),
    "chk_reason_matches": re.compile(r"\b(motivo\w*|razao|reason|closure)\b"),
    "chk_owner_unchanged": re.compile(r"\b(proprietari\w*|owner|dono|responsavel)\b"),
    "chk_followup_task": re.compile(r"\b(task\w*|tarefa\w*|acompanhamento|follow\W?up)\b"),
    "chk_no_unexpected": re.compile(r"\b(inesperad\w*|outros? campos?|nenhum\w* (outr\w+|alterac\w+|mudanc\w+)|alterac\w+|mudanc\w+|modificac\w+)\b"),
}
FIELD_TOPICS = {"Priority": r"priorid\w*|priority", "Subject": r"assunto|subject|titulo", "Origin": r"origem|origin",
                "Description": r"descri\w+|description", "Status": r"status"}

# Assuntos que os dados monitorados NAO observam: forcam not_verifiable (lista finita e heuristica).
OUT_OF_SCOPE = re.compile(
    r"\b(e-?mails?|mails?|sms|whatsapp|notific\w*|avis\w+|alert\w+|slack|teams|telefon\w*|ligac\w*|ligar|"
    r"sla|prazos?|horas?|dias? uteis|tempo de resposta|satisf\w*|csat|nps|pesquisa\w*|"
    r"anex\w*|coment\w*|chat|mensagem|mensagens|respost\w*|informar|informe|"
    r"fatur\w*|cobranc\w*|pagament\w*|reembols\w*|"
    r"conta|account|oportunidade\w*|lead\w*|contato\w*|cliente\w* (receb\w+|deve ser)|"
    r"audit\w*|historic\w*|log|permiss\w*|seguranc\w*|criptograf\w*|integrac\w*|sap|erp|"
    r"relatorio\w*|dashboard\w*|escalon\w*|fila\w*|roteament\w*|atribu\w+)\b")

_NEG = r"(?:nao|sem|nunca|jamais)"
# (padrao, check conflitante, motivo, ignorar_se_houver_negacao_no_trecho)
CONFLICTS: list[tuple[re.Pattern[str], str, str, bool]] = [
    (re.compile(rf"\b{_NEG}\b[^.;]{{0,40}}\b(?:cri\w+|ger\w+|abr\w+|haver|ter|existir)\b[^.;]{{0,30}}\b(?:task|tarefa)"),
     "chk_followup_task", "A regra pede nenhuma Task, mas o plano exige exatamente uma Task de acompanhamento.", False),
    (re.compile(r"\bsem\s+(?:criar\s+|gerar\s+)?(?:task|tarefa)"),
     "chk_followup_task", "A regra pede nenhuma Task, mas o plano exige exatamente uma Task de acompanhamento.", False),
    (re.compile(r"\b(?:duas|dois|2|tres|3|varias|multiplas|mais de uma|uma ou mais)\s+(?:task|tarefa)"),
     "chk_followup_task", "A regra admite mais de uma Task, mas o plano exige exatamente uma.", False),
    (re.compile(r"\bmotivo\w*[^.;]{0,30}\b(?:vazio|opcional|em branco)\b"),
     "chk_reason_filled", "A regra admite motivo vazio, mas o plano exige motivo preenchido.", True),
    (re.compile(r"\bmotivo\w*[^.;]{0,30}\b(?:nao precisa|nao e obrigatorio|dispensa\w*)\b"),
     "chk_reason_filled", "A regra dispensa o motivo, mas o plano exige motivo preenchido.", False),
]
OWNER_CHANGE = re.compile(r"propriet\w*[^.;]{0,30}\b(?:deve|pode|podera|sera|passa|passar)\b[^.;]{0,20}\b(?:mud\w+|alter\w+|troc\w+|transfer\w+)")
TRIGGER_PREFIX = re.compile(r"^(?:ao|quando|se|apos|depois|sempre que|no momento|caso)\b")


def _clean(text: Any, limit: int) -> str:
    return _CTRL.sub(" ", text).strip()[:limit] if isinstance(text, str) else ""


def segment(rule_text: str) -> list[dict[str, Any]]:
    """Clausulas atomicas aproximadas, com ids atribuidos pelo servidor."""
    pieces: list[str] = []
    for line in re.split(r"\n+", rule_text):
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", line).strip()
        for sentence in re.split(r"(?<=[.!?;])\s+", line):
            sentence = sentence.strip().rstrip(".;!?").strip()
            if not sentence:
                continue
            parts = [p.strip() for p in re.split(r",\s+(?:e\s+|ou\s+)?|\s+e\s+|\s+ou\s+", sentence, flags=re.IGNORECASE) if p.strip()]
            merged: list[str] = []
            carry = ""
            for p in parts:
                if len(p.split()) < 2 and merged:
                    merged[-1] = f"{merged[-1]} e {p}"       # "antes e depois": palavra solta nao e requisito
                    continue
                if not merged and not carry and TRIGGER_PREFIX.match(norm(p)) and len(parts) > 1:
                    carry = p            # condicao ("Ao encerrar um Case"): vira prefixo do primeiro requisito
                    continue
                merged.append(f"{carry}, {p}" if carry else p)
                carry = ""
            if carry:
                merged.append(carry)
            pieces.extend(merged)
    pieces = [p for p in pieces if len(p) >= 3]
    clauses = [{"clause_id": f"cl_{i:02d}", "text": p[:MAX_CLAUSE_CHARS], "overflow": False} for i, p in enumerate(pieces, 1)]
    if len(clauses) > MAX_CLAUSES:
        rest = " / ".join(c["text"] for c in clauses[MAX_CLAUSES - 1:])[:MAX_CLAUSE_CHARS]
        clauses = clauses[:MAX_CLAUSES - 1] + [{"clause_id": f"cl_{MAX_CLAUSES:02d}", "text": rest, "overflow": True}]
    return clauses


def _topic(check: dict[str, Any]) -> re.Pattern[str] | None:
    cid = check["check_id"]
    if cid in CHECK_TOPICS:
        return CHECK_TOPICS[cid]
    field = check.get("field")
    if isinstance(field, str):
        pattern = FIELD_TOPICS.get(field) or re.escape(norm(field.removesuffix("__c")).replace("_", " "))
        return re.compile(rf"\b(?:{pattern})\b")
    return None


def _server_verdict(text: str) -> tuple[str, list[str], str] | None:
    t = norm(text)
    for rx, cid, why, skip_if_neg in CONFLICTS:
        m = rx.search(t)
        if m and not (skip_if_neg and re.search(rf"\b{_NEG}\b", m.group(0))):
            return CONFLICT, [cid], why
    m = OWNER_CHANGE.search(t)
    if m and not re.search(rf"\b{_NEG}\b", m.group(0)):
        return CONFLICT, ["chk_owner_unchanged"], "A regra admite troca de proprietario, mas o plano exige que ele se mantenha."
    m = OUT_OF_SCOPE.search(t)
    if m:
        return NOT_VERIFIABLE, [], f"Assunto fora do que os dados monitorados observam (termo: {m.group(0)[:30]!r})."
    return None


def finalize(clauses: list[dict[str, Any]], model_items: Any, checks: list[dict[str, Any]]
             ) -> tuple[list[dict[str, Any]], list[str]]:
    """Itens finais de cobertura + avisos. Nunca promove alem do que o servidor consegue sustentar."""
    warnings: list[str] = []
    by_check = {c["check_id"]: c for c in checks}
    proposals: dict[str, dict[str, Any]] = {}
    if isinstance(model_items, list):
        for it in model_items:
            cid = it.get("clause_id") if isinstance(it, dict) else None
            if not isinstance(cid, str) or cid not in {c["clause_id"] for c in clauses}:
                warnings.append("cobertura do modelo: clause_id desconhecido ignorado")
            elif cid in proposals:
                warnings.append(f"cobertura do modelo: {cid} duplicado; vale o primeiro")
            else:
                proposals[cid] = it
    elif model_items is not None:
        warnings.append("cobertura do modelo ignorada: formato invalido")

    out: list[dict[str, Any]] = []
    for c in clauses:
        text = c["text"]

        def item(status: str, ids: list[str], reason: str, basis: str) -> dict[str, Any]:
            return {"clause_id": c["clause_id"], "text": text, "status": status, "check_ids": ids,
                    "reason": reason, "basis": basis}

        if c.get("overflow"):
            out.append(item(NOT_VERIFIABLE, [], "Clausulas alem do limite de analise; nao foram avaliadas.", "server_rule"))
            continue
        verdict = _server_verdict(text)
        if verdict:
            out.append(item(verdict[0], verdict[1], verdict[2], "server_rule"))
            continue
        prop = proposals.get(c["clause_id"])
        if prop is None:
            out.append(item(NOT_VERIFIABLE, [], "Sem analise do modelo para esta clausula.", "server_rule"))
            continue
        status = prop.get("status")
        ids = prop.get("check_ids")
        ids = [i for i in ids if isinstance(i, str)] if isinstance(ids, list) else []
        reason = _clean(prop.get("reason"), MAX_REASON)
        if status == COVERED:
            known = list(dict.fromkeys(ids))
            if not known or any(i not in by_check for i in known) or len(known) > len(by_check):
                out.append(item(NOT_VERIFIABLE, [], "Rebaixada: o modelo citou verificacoes inexistentes ou nenhuma.", "server_rule"))
                continue
            t = norm(text)
            compatible = [i for i in known if (tp := _topic(by_check[i])) is not None and tp.search(t)]
            if not compatible:
                out.append(item(NOT_VERIFIABLE, [], "Rebaixada: o vocabulario da clausula nao corresponde as verificacoes citadas.", "server_rule"))
                continue
            out.append(item(COVERED, compatible[:MAX_CITED], reason or "Mapeamento proposto pelo modelo; confirme na revisao.", "model"))
        elif status == CONFLICT:
            known = [i for i in dict.fromkeys(ids) if i in by_check][:MAX_CITED]
            out.append(item(CONFLICT, known, reason or "O modelo indicou conflito com um invariante do plano.", "model"))
        else:
            out.append(item(NOT_VERIFIABLE, [], reason or "O modelo indicou que a clausula nao e verificavel com os dados monitorados.", "model"))
    return out, warnings


def coverage_status(items: list[dict[str, Any]]) -> str:
    if not items:
        return "not_assessed"
    return "complete" if all(i["status"] == COVERED for i in items) else "partial"
