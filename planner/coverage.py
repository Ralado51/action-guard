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
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return t.replace("'", "").replace("\u2019", "")


# Tema de cada verificacao (sobre texto normalizado). Extras ganham tema a partir do nome do campo.
CHECK_TOPICS: dict[str, re.Pattern[str]] = {
    "chk_status_closed": re.compile(r"\b(encerr\w*|fech\w*|clos\w*|status|conclu\w*|resolv\w*)\b"),
    "chk_reason_filled": re.compile(r"\b(motivo\w*|razao|reason|closure)\b"),
    "chk_reason_matches": re.compile(r"\b(motivo\w*|razao|reason|closure)\b"),
    "chk_owner_unchanged": re.compile(r"\b(proprietari\w*|owner\w*|dono|responsavel)\b"),
    "chk_followup_task": re.compile(r"\b(task\w*|tarefa\w*|acompanhamento|follow\W?ups?)\b"),
    "chk_no_unexpected": re.compile(r"\b(inesperad\w*|outros? campos?|nenhum\w* (outr\w+|alterac\w+|mudanc\w+)|alterac\w+|mudanc\w+|modificac\w+"
        r"|unexpected|unintended|side effects?|other (fields?|changes?|modifications?)|no (other|further|additional) \w*\s*(changes?|modifications?))\b"),
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
    r"relatorio\w*|dashboard\w*|escalon\w*|fila\w*|roteament\w*|atribu\w+|"
    r"notif\w*|alerts?|phone|calls?|deadlines?|business days?|working days?|response times?|"
    r"hours?|minutes?|satisf\w*|surveys?|attach\w*|comments?|messages?|repl(?:y|ies)|respond\w*|inform|"
    r"invoic\w*|billing|payments?|refund\w*|accounts?|opportunit\w*|leads?|contacts?|"
    r"customers? (?:receives?|gets?|should be|must be)|audit\w*|histor\w*|permissions?|security|"
    r"encrypt\w*|integrat\w*|reports?|escalat\w*|queues?|routing|assign\w*)\b")

_NEG = r"(?:nao|sem|nunca|jamais|no|not|never|without|dont|doesnt|isnt|cannot|cant)"
# (padrao, check conflitante, motivo, ignorar_se_houver_negacao_no_trecho)
CONFLICTS: list[tuple[re.Pattern[str], str, str, bool]] = [
    (re.compile(rf"\b{_NEG}\b[^.;]{{0,40}}\b(?:cri\w+|ger\w+|abr\w+|haver|ter|existir)\b[^.;]{{0,30}}\b(?:task|tarefa)"),
     "chk_followup_task", "The rule asks for no Task, but the plan requires exactly one follow-up Task.", False),
    (re.compile(r"\bsem\s+(?:criar\s+|gerar\s+)?(?:task|tarefa)"),
     "chk_followup_task", "The rule asks for no Task, but the plan requires exactly one follow-up Task.", False),
    (re.compile(r"\b(?:duas|dois|2|tres|3|varias|multiplas|mais de uma|uma ou mais)\s+(?:task|tarefa)"),
     "chk_followup_task", "The rule allows more than one Task, but the plan requires exactly one.", False),
    (re.compile(r"\bmotivo\w*[^.;]{0,30}\b(?:vazio|opcional|em branco)\b"),
     "chk_reason_filled", "The rule allows an empty reason, but the plan requires a filled reason.", True),
    (re.compile(r"\bmotivo\w*[^.;]{0,30}\b(?:nao precisa|nao e obrigatorio|dispensa\w*)\b"),
     "chk_reason_filled", "The rule waives the reason, but the plan requires a filled reason.", False),
    (re.compile(rf"\b{_NEG}\b[^.;]{{0,40}}\b(?:creat\w+|generat\w+|open\w*|hav\w+|exist\w*|add\w*)\b[^.;]{{0,30}}\b(?:tasks?|follow\W?ups?)"),
     "chk_followup_task", "The rule asks for no Task, but the plan requires exactly one follow-up Task.", False),
    (re.compile(r"\b(?:two|2|three|3|four|several|multiple|many|more than one|one or more|at least two)\s+(?:\w+\W?\s*)?(?:tasks?|follow\W?ups?)"),
     "chk_followup_task", "The rule allows more than one Task, but the plan requires exactly one.", False),
    (re.compile(r"\breasons?\b[^.;]{0,30}\b(?:empty|optional|blank)\b"),
     "chk_reason_filled", "The rule allows an empty reason, but the plan requires a filled reason.", True),
    (re.compile(r"\breasons?\b[^.;]{0,30}\b(?:not required|not needed|not mandatory|waived|can be skipped|may be skipped|does not need|doesnt need)\b"),
     "chk_reason_filled", "The rule waives the reason, but the plan requires a filled reason.", False),
    (re.compile(r"\bwithout\s+(?:a\s+|any\s+)?(?:closure\s+)?reason\b"),
     "chk_reason_filled", "The rule allows closing without a reason, but the plan requires a filled reason.", False),
]
OWNER_CHANGE = re.compile(
    r"propriet\w*[^.;]{0,30}\b(?:deve|pode|podera|sera|passa|passar)\b[^.;]{0,20}\b(?:mud\w+|alter\w+|troc\w+|transfer\w+)"
    r"|\bowner\w*[^.;]{0,30}\b(?:should|may|can|will|must|to)\b[^.;]{0,20}\b(?:chang\w+|reassign\w*|transfer\w*|switch\w*|updat\w+)"
    r"|\b(?:reassign\w*|chang\w+|transfer\w*|switch\w*)\s+(?:the\s+)?(?:case\s+)?owner")
TRIGGER_PREFIX = re.compile(r"^(?:ao|quando|se|apos|depois|sempre que|no momento|caso|when|whenever|if|once|after|upon|on|as soon as|in case)\b")


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
            parts = [p.strip() for p in re.split(
                r",\s+(?:e\s+|ou\s+|and\s+|or\s+)?|\s+e\s+|\s+ou\s+|(?<!before)(?<!after)(?<!between)(?<!both)\s+and\s+|\s+or\s+",
                sentence, flags=re.IGNORECASE) if p.strip()]
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
    if m and not re.search(rf"\b{_NEG}\b", t[max(0, m.start() - 25):m.end()]):
        return CONFLICT, ["chk_owner_unchanged"], "The rule allows an owner change, but the plan requires the owner to stay the same."
    m = OUT_OF_SCOPE.search(t)
    if m:
        return NOT_VERIFIABLE, [], f"Subject outside what the monitored data observes (term: {m.group(0)[:30]!r})."
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
                warnings.append("model coverage: unknown clause_id ignored")
            elif cid in proposals:
                warnings.append(f"model coverage: {cid} duplicated; the first one applies")
            else:
                proposals[cid] = it
    elif model_items is not None:
        warnings.append("model coverage ignored: invalid format")

    out: list[dict[str, Any]] = []
    for c in clauses:
        text = c["text"]

        def item(status: str, ids: list[str], reason: str, basis: str) -> dict[str, Any]:
            return {"clause_id": c["clause_id"], "text": text, "status": status, "check_ids": ids,
                    "reason": reason, "basis": basis}

        if c.get("overflow"):
            out.append(item(NOT_VERIFIABLE, [], "Clauses beyond the analysis limit; they were not evaluated.", "server_rule"))
            continue
        verdict = _server_verdict(text)
        if verdict:
            out.append(item(verdict[0], verdict[1], verdict[2], "server_rule"))
            continue
        prop = proposals.get(c["clause_id"])
        if prop is None:
            out.append(item(NOT_VERIFIABLE, [], "No model analysis for this clause.", "server_rule"))
            continue
        status = prop.get("status")
        ids = prop.get("check_ids")
        ids = [i for i in ids if isinstance(i, str)] if isinstance(ids, list) else []
        reason = _clean(prop.get("reason"), MAX_REASON)
        if status == COVERED:
            known = list(dict.fromkeys(ids))
            if not known or any(i not in by_check for i in known) or len(known) > len(by_check):
                out.append(item(NOT_VERIFIABLE, [], "Downgraded: the model cited checks that do not exist, or none.", "server_rule"))
                continue
            t = norm(text)
            compatible = [i for i in known if (tp := _topic(by_check[i])) is not None and tp.search(t)]
            if not compatible:
                out.append(item(NOT_VERIFIABLE, [], "Downgraded: the clause vocabulary does not match the cited checks.", "server_rule"))
                continue
            out.append(item(COVERED, compatible[:MAX_CITED], reason or "Mapping proposed by the model; confirm during review.", "model"))
        elif status == CONFLICT:
            known = [i for i in dict.fromkeys(ids) if i in by_check][:MAX_CITED]
            out.append(item(CONFLICT, known, reason or "The model flagged a conflict with a plan invariant.", "model"))
        else:
            out.append(item(NOT_VERIFIABLE, [], reason or "The model indicated the clause cannot be verified with the monitored data.", "model"))
    return out, warnings


def coverage_status(items: list[dict[str, Any]]) -> str:
    if not items:
        return "not_assessed"
    return "complete" if all(i["status"] == COVERED for i in items) else "partial"
