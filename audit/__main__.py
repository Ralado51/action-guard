"""CLI: python -m audit run --plan <plano aprovado> (--case-ids arquivo | --since ISO) [--explain]. SOMENTE LEITURA."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time

from connector.auth import AuthError, get_token
from connector.config import ConfigError, SalesforceConfig
from connector.rest import SalesforceRest
from connector.snapshot import utc_now
from connector.transport import UrllibTransport
from orchestrator.store import EvidenceStore
from planner.client import VultrChatClient
from planner.config import PlannerConfig
from planner.errors import PlannerError

from .explain import explain
from .run import AuditBlocked, run_audit


def _merge(paths):
    out = {}
    for p in paths or []:
        with open(p, encoding="utf-8") as fh:
            out.update(json.load(fh))
    return out or None


def main(argv=None, *, transport=None, secret=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m audit")
    sub = ap.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="Audits records (read-only).")
    r.add_argument("--plan", required=True, help="approved plan (plan JSON or a bundle with a 'plan' key)")
    g = r.add_mutually_exclusive_group(required=True)
    g.add_argument("--case-ids", help="file with one Id per line (the Cases the agent reported)")
    g.add_argument("--since", help="window: Cases closed since 2026-11-01T00:00:00Z")
    r.add_argument("--modified-by", help="agent user Id (optional window filter)")
    r.add_argument("--limit", type=int, default=200)
    r.add_argument("--runs-dir", default="runs")
    r.add_argument("--agent-runs", action="append", help="claims.json written by python -m vultr_agent run (adds the agent's own account to each Case)")
    r.add_argument("--list-all", action="store_true", help="list passing Cases too (for a recorded, shareable run)")
    r.add_argument("--explain", action="store_true", help="summary with the Vultr model (counts only)")
    m = sub.add_parser("mask", help="Print a saved report with Salesforce Ids masked (for public display).")
    m.add_argument("--report", required=True)
    args = ap.parse_args(argv)
    if args.command == "mask":
        from .mask import mask_report
        with open(args.report, encoding="utf-8") as fh:
            print(json.dumps(mask_report(json.load(fh)), ensure_ascii=False, separators=(",", ":")))
        return 0
    try:
        with open(args.plan, encoding="utf-8") as fh:
            data = json.load(fh)
        plan = data["plan"] if isinstance(data, dict) and "plan" in data else data
        ids = None
        if args.case_ids:
            with open(args.case_ids, encoding="utf-8") as fh:
                ids = [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
        env = dict(os.environ)
        for key in ("SF_CLIENT_ID", "SF_CLIENT_SECRET"):
            if not env.get(key):
                env[key] = (secret or getpass.getpass)(key + " (oculto): ")
        http = transport or UrllibTransport()
        cfg = SalesforceConfig.from_env(env)
        rest = SalesforceRest(cfg, get_token(cfg, http), http)
        report = run_audit(plan, rest, case_ids=ids, since=args.since, modified_by=args.modified_by, limit=args.limit,
                          agent_runs=_merge(args.agent_runs), list_all=args.list_all)
        if args.explain:
            explain(report, VultrChatClient(PlannerConfig.from_env(), http))
        path = EvidenceStore(args.runs_dir, report["audit_id"]).save("audit_report", report)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        print("Relatorio salvo:", path, file=sys.stderr)
        return 0
    except AuditBlocked as e:
        print("Auditoria bloqueada:", e)
        return 1
    except PlannerError as e:
        print(json.dumps(e.to_public(), ensure_ascii=False))
        return 1
    except (ValueError, KeyError, TypeError, OSError, AuthError, ConfigError):
        print("Operation interrupted. Check the configuration, plan and selection; nothing was changed in Salesforce.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
