"""Avaliacao de fidelidade da cobertura: compara o resultado FINAL (apos as travas do servidor) com rotulos humanos.

Metricas (por clausula): `false_covered` (declarou coberta o que o plano nao verifica) e o erro PERIGOSO;
`false_uncovered` e o erro inofensivo (cobertura subdeclarada); `conflict_missed` e conflito nao detectado.
Uso com o modelo real (consome 1 a 2 chamadas por regra; chave no ambiente, nunca no chat):
    python -m planner.coverage_eval tests/data/rule_coverage_labeled.json --fixture-metadata
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable

from . import coverage as cov

CANONICAL = ["chk_status_closed", "chk_reason_filled", "chk_reason_matches", "chk_owner_unchanged",
             "chk_followup_task", "chk_no_unexpected"]


def load(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def locate(clauses: list[dict[str, Any]], expect: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Casa cada rotulo com UMA clausula pela substring (texto normalizado)."""
    out = []
    for e in expect:
        hits = [c for c in clauses if cov.norm(e["contains"]) in cov.norm(c["text"])]
        if len(hits) != 1:
            raise ValueError(f"rotulo {e['contains']!r} casa com {len(hits)} clausulas: {[c['text'] for c in clauses]}")
        out.append((hits[0], e))
    return out


def classify(final: dict[str, Any], label: dict[str, Any]) -> str:
    got, want = final["status"], label["status"]
    if got == want:
        return "ok"
    if got == cov.COVERED:
        return "false_covered"
    if want == cov.CONFLICT:
        return "conflict_missed"
    return "false_uncovered"


def simulated_model(policy: str, clauses: list[dict[str, Any]], expect: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`optimist`: declara tudo coberto, citando as seis verificacoes (pior caso). `oracle`: segue o rotulo."""
    if policy == "optimist":
        return [{"clause_id": c["clause_id"], "status": "covered", "check_ids": list(CANONICAL), "reason": "ok"} for c in clauses]
    labelled = {c["clause_id"]: e for c, e in locate(clauses, expect)}
    items = []
    for c in clauses:
        e = labelled.get(c["clause_id"])
        if e is None:
            items.append({"clause_id": c["clause_id"], "status": "not_verifiable", "check_ids": [], "reason": "sem rotulo"})
        else:
            items.append({"clause_id": c["clause_id"], "status": e["status"], "check_ids": e.get("checks", []), "reason": "rotulo"})
    return items


def evaluate(dataset: dict[str, Any], model: Callable[[str, list[dict[str, Any]], list[dict[str, Any]]], Any],
             checks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    checks = checks or [{"check_id": i, "kind": "x"} for i in CANONICAL]
    rows, counts = [], {"ok": 0, "false_covered": 0, "false_uncovered": 0, "conflict_missed": 0}
    for rule in dataset["rules"]:
        clauses = cov.segment(rule["text"])
        final, _ = cov.finalize(clauses, model(rule["id"], clauses, rule["expect"]), checks)
        by_id = {i["clause_id"]: i for i in final}
        for clause, label in locate(clauses, rule["expect"]):
            kind = classify(by_id[clause["clause_id"]], label)
            counts[kind] += 1
            rows.append({"rule": rule["id"], "clause": clause["text"], "expected": label["status"],
                         "got": by_id[clause["clause_id"]]["status"], "result": kind,
                         "known_gap": bool(label.get("known_gap"))})
    return {"counts": counts, "rows": rows}


def main(argv: list[str] | None = None, transport=None) -> int:
    from connector.transport import UrllibTransport
    from .__main__ import fixture_metadata
    from .errors import PlannerError
    from .service import create_plan

    ap = argparse.ArgumentParser(prog="python -m planner.coverage_eval")
    ap.add_argument("dataset")
    ap.add_argument("--metadata")
    ap.add_argument("--fixture-metadata", action="store_true")
    ap.add_argument("--reason", default="Resolved - Customer confirmed")
    ap.add_argument("--subject", default="Action Guard - Case closure follow-up")
    args = ap.parse_args(argv)
    if bool(args.metadata) == args.fixture_metadata:
        print("informe exatamente um entre --metadata e --fixture-metadata", file=sys.stderr)
        return 2
    meta = fixture_metadata() if args.fixture_metadata else json.load(open(args.metadata, encoding="utf-8"))
    http = transport or UrllibTransport()
    data = load(args.dataset)
    counts = {"ok": 0, "false_covered": 0, "false_uncovered": 0, "conflict_missed": 0}
    errors, rows, calls, tokens = [], [], 0, 0
    for rule in data["rules"]:
        text = {"schema_version": "1.0", "rule_id": "rule-" + rule["id"], "process": "close_case", "text_pt": rule["text"]}
        try:
            res = create_plan(text, meta, {"process": "close_case", "closure_reason": args.reason, "task_subject": args.subject}, http)
        except PlannerError as e:
            errors.append({"rule": rule["id"], "category": e.category})
            continue
        calls += res.calls
        tokens += res.usage.get("total_tokens", 0)
        by_id = {i["clause_id"]: i for i in res.plan.get("rule_coverage", [])}
        for clause, label in locate(cov.segment(rule["text"]), rule["expect"]):
            kind = classify(by_id[clause["clause_id"]], label)
            counts[kind] += 1
            rows.append({"rule": rule["id"], "clause": clause["text"], "expected": label["status"],
                         "got": by_id[clause["clause_id"]]["status"], "result": kind, "known_gap": bool(label.get("known_gap"))})
    print(json.dumps({"counts": counts, "errors": errors, "calls": calls, "total_tokens": tokens,
                      "source": meta["source"], "problems": [r for r in rows if r["result"] != "ok"]}, ensure_ascii=False, indent=2))
    return 0 if counts["false_covered"] == 0 and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
