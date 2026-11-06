"""Gera SOMENTE um rascunho de plano (nenhum efeito no Salesforce, nenhum agente).

Uso na VM, com a chave no ambiente (nunca no chat nem em argumentos):
  python -m planner --rule contracts/examples/rule.json --metadata metadata.json \
      --reason "Resolved - Customer confirmed" --subject "Action Guard - Case closure follow-up"
`--metadata` e um JSON de contexto (ver docs/PLANNER.md). Sem ele o comando recusa; para um teste de
fumaca use `--fixture-metadata`, que marca a origem como "fixture" no resultado.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from connector.transport import Transport, UrllibTransport

from . import PlannerError, create_plan

FIXTURE_FIELDS = {
    "Case": {"Status": ("picklist", ["New", "Working", "Escalated", "Closed"]), "OwnerId": ("reference", []),
             "Closure_Reason__c": ("picklist", ["Resolved - Customer confirmed", "Resolved - Guidance provided", "Duplicate", "Cancelled"]),
             "ClosedDate": ("datetime", []), "IsClosed": ("boolean", []), "Priority": ("picklist", ["Low", "Medium", "High"]),
             "Subject": ("string", [])},
    "Task": {n: ("string", []) for n in ("Subject", "WhatId", "OwnerId", "Status", "CreatedDate")},
}


def fixture_metadata() -> dict[str, Any]:
    return {"source": "fixture", "collected_at": "fixture", "objects": {
        o: {"readable": True, "fields": {n: {"type": t, "readable": True, **({"values": v} if v else {})}
                                         for n, (t, v) in fs.items()}} for o, fs in FIXTURE_FIELDS.items()}}


def main(argv: list[str] | None = None, transport: Transport | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m planner")
    ap.add_argument("--rule", required=True)
    ap.add_argument("--metadata")
    ap.add_argument("--fixture-metadata", action="store_true")
    ap.add_argument("--reason", required=True)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--case-id", help="Case given by the operator/backend; omitted = draft without a Case")
    args = ap.parse_args(argv)
    if bool(args.metadata) == args.fixture_metadata:
        print("informe exatamente um entre --metadata e --fixture-metadata", file=sys.stderr)
        return 2
    with open(args.rule, encoding="utf-8") as fh:
        rule = json.load(fh)
    if args.metadata:
        with open(args.metadata, encoding="utf-8") as fh:
            meta = json.load(fh)
    else:
        meta = fixture_metadata()
    action = {"process": "close_case", "closure_reason": args.reason, "task_subject": args.subject}
    if args.case_id:
        action["case_id"] = args.case_id
    try:
        res = create_plan(rule, meta, action, transport or UrllibTransport())
    except PlannerError as e:
        print(json.dumps({"ok": False, "error": e.to_public()}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"ok": True, "metadata_source": res.metadata_source, "model": res.model,
                      "served_model": res.served_model, "usage": res.usage, "calls": res.calls,
                      "plan_hash": res.plan["plan_hash"], "warnings": res.warnings, "plan": res.plan},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
