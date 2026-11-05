"""Operator CLI: prepare draft, then explicitly approve and execute its exact hash."""
from __future__ import annotations

import argparse
import copy
import getpass
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

from connector.agent_api import AgentClient
from connector.auth import AuthError, get_token
from connector.config import ConfigError, SalesforceConfig
from connector.rest import SalesforceRest
from connector.snapshot import utc_now
from connector.transport import UrllibTransport
from contracts.plan_hash import compute_plan_hash
from planner import bind_case, create_plan, ready_for_approval
from planner.errors import PlannerError
from .run import RunBlocked, execute_run
from .store import EvidenceStore


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _save_new(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())


def prepare(args, transport):
    meta = _load(args.metadata)
    if meta.get("source") != "salesforce_describe":
        raise ValueError("Este teste integrado exige metadados Salesforce Describe.")
    if Path(args.output).exists():
        raise ValueError("Arquivo de saida ja existe; nao sera sobrescrito.")
    result = create_plan(_load(args.rule), meta,
                         {"process": "close_case", "closure_reason": args.reason,
                          "task_subject": args.subject}, transport)
    plan = bind_case(result.plan, args.case_id)
    issues = ready_for_approval(plan)
    if issues:
        raise ValueError("; ".join(issues))
    _save_new(args.output, {"plan": plan, "generation": {
        "metadata_source": result.metadata_source, "metadata_collected_at": result.metadata_collected_at,
        "model": result.model, "served_model": result.served_model, "usage": result.usage,
        "calls": result.calls, "warnings": result.warnings}})
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    print("Rascunho salvo sem aprovacao:", args.output)


def run(args, transport, confirm, secret):
    bundle = _load(args.plan)
    plan = copy.deepcopy(bundle["plan"])
    if bundle.get("generation", {}).get("metadata_source") != "salesforce_describe":
        raise ValueError("Origem dos metadados deve ser salesforce_describe.")
    issues = ready_for_approval(plan)
    if issues or plan.get("plan_hash") != compute_plan_hash(plan):
        raise ValueError("Plano invalido ou hash alterado; gere novo rascunho antes de aprovar.")
    plan["approval"] = None
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    expected = "APROVAR " + plan["plan_hash"]
    print("Esta acao fecha o Case e cria uma Task. Confira tambem o escopo monitored.")
    if confirm("Digite " + expected + ": ").strip() != expected:
        print("Cancelado. Nenhuma chamada ao Salesforce.")
        return 0
    plan["approval"] = {"approved_by": args.approved_by, "approved_at": utc_now(),
                        "approved_plan_hash": plan["plan_hash"]}
    env = dict(os.environ)
    for key in ("SF_CLIENT_ID", "SF_CLIENT_SECRET"):
        if not env.get(key):
            env[key] = secret(key + " (oculto): ")
    cfg = SalesforceConfig.from_env(env)
    case_id = plan["action"]["input"]["case_id"]
    # Local per-org/Case reservation survives a crash and changed plan IDs. This is
    # not a distributed exactly-once guarantee. Never delete to blindly retry.
    guards = Path(args.runs_dir) / "attempts"
    guards.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256((cfg.my_domain + "|" + case_id).encode()).hexdigest()
    _save_new(guards / (key + ".json"), {"plan_hash": plan["plan_hash"], "at": utc_now()})
    run_id = "integrated-" + uuid.uuid4().hex
    store = EvidenceStore(args.runs_dir, run_id)
    store.save("generation", bundle["generation"])
    store.save("approved_plan", plan)
    print("Evidencias:", store.dir.resolve())
    token = get_token(cfg, transport)
    report = execute_run(plan, case_id=case_id, run_id=run_id,
                         rest=SalesforceRest(cfg, token, transport),
                         agent=AgentClient(cfg, token, transport, utc_now),
                         store=store, sleep=time.sleep)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


def main(argv=None, *, transport=None, confirm=None, secret=None):
    ap = argparse.ArgumentParser(prog="python -m orchestrator")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare", help="Gera plano pela Vultr; nao chama Salesforce.")
    p.add_argument("--rule", required=True)
    p.add_argument("--metadata", required=True)
    p.add_argument("--case-id", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--subject", required=True)
    p.add_argument("--output", required=True)
    r = sub.add_parser("run", help="Revisa, aprova hash e executa uma tentativa.")
    r.add_argument("--plan", required=True)
    r.add_argument("--approved-by", required=True)
    r.add_argument("--runs-dir", default="runs")
    args = ap.parse_args(argv)
    try:
        http = transport or UrllibTransport()
        if args.command == "prepare":
            prepare(args, http)
            return 0
        return run(args, http, confirm or input, secret or getpass.getpass)
    except FileExistsError:
        print("Arquivo ou tentativa ja existe. Nao repetir; reconciliar evidencias antes de nova tentativa.")
        return 1
    except PlannerError as error:
        print(json.dumps(error.to_public(), ensure_ascii=False))
        return 1
    except (ValueError, KeyError, TypeError, OSError, AuthError, ConfigError, RunBlocked):
        print("Operacao interrompida. Confira configuracao, plano e evidencias; nao repita uma execucao automaticamente.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
