"""CLI.
  python -m vultr_agent seed --count 1 --out agent_runs            # creates synthetic Cases, writes authorized.json
  python -m vultr_agent run  --authorized agent_runs/authorized.json --limit 1 --confirm-write
Writes only to Cases listed in authorized.json, one Case at a time, and only if the Case Subject carries the
synthetic marker. A write with an uncertain outcome is never repeated.
"""
from __future__ import annotations

import argparse
import dataclasses
import getpass
import json
import os
import sys
import uuid
from pathlib import Path

from connector.auth import AuthError, get_token
from connector.config import ConfigError, SalesforceConfig
from connector.ids import key15
from connector.rest import QueryError, SalesforceRest
from connector.transport import UrllibTransport
from planner.client import VultrChatClient
from planner.config import PlannerConfig
from planner.errors import PlannerError

from .agent import run_agent
from .tools import MARKER, REASONS, Guard, SalesforceTools

TOPICS = ["Cannot reset password", "Invoice shows wrong amount", "Delivery date question", "Account locked after update",
          "Refund status request", "Change billing address", "App crashes on login", "Missing order confirmation",
          "Upgrade plan question", "Duplicate charge", "Cancel subscription", "Export my data",
          "Two-factor code not arriving", "Late shipment", "Wrong item received", "Update company name",
          "Promo code rejected", "Cannot download receipt", "Product manual request", "Warranty claim"]
MAX_SEED = 25


def _rest(transport, secret=None) -> tuple[SalesforceRest, SalesforceConfig]:
    env = dict(os.environ)
    for key in ("SF_CLIENT_ID", "SF_CLIENT_SECRET"):
        if not env.get(key):
            env[key] = (secret or getpass.getpass)(key + " (hidden): ")
    cfg = SalesforceConfig.from_env(env)
    return SalesforceRest(cfg, get_token(cfg, transport), transport), cfg


def main(argv=None, *, transport=None, secret=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m vultr_agent")
    sub = ap.add_subparsers(dest="command", required=True)
    s = sub.add_parser("seed", help="Create synthetic Cases (marker in Subject) and record their Ids.")
    s.add_argument("--count", type=int, default=1)
    s.add_argument("--out", default="agent_runs")
    r = sub.add_parser("run", help="Let the Vultr agent handle the authorized Cases (writes to Salesforce).")
    r.add_argument("--authorized", required=True)
    r.add_argument("--limit", type=int, default=1)
    r.add_argument("--max-steps", type=int, default=6)
    r.add_argument("--confirm-write", action="store_true", help="required: acknowledges real writes to the synthetic Cases")
    args = ap.parse_args(argv)
    http = transport or UrllibTransport()
    try:
        rest, _ = _rest(http, secret)
        if args.command == "seed":
            if not 1 <= args.count <= MAX_SEED:
                print(f"--count must be between 1 and {MAX_SEED}.")
                return 1
            ids = [rest.create("Case", {"Subject": f"{MARKER} {TOPICS[i % len(TOPICS)]}", "Status": "New", "Origin": "Web"})
                   for i in range(args.count)]
            out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
            (out / "authorized.json").write_text(json.dumps({"case_ids": ids, "marker": MARKER}, indent=2))
            print(f"Created {len(ids)} synthetic Case(s):", *ids, sep="\n")
            return 0
        if not args.confirm_write:
            print("Refused: pass --confirm-write to acknowledge that this run writes to the synthetic Cases.")
            return 1
        auth_path = Path(args.authorized)
        authorized = json.loads(auth_path.read_text())["case_ids"]
        run_dir = auth_path.parent / ("vultr-run-" + uuid.uuid4().hex[:8])
        run_dir.mkdir(parents=True)
        cfg = dataclasses.replace(PlannerConfig.from_env(), max_calls=args.max_steps)
        client, claims, done = VultrChatClient(cfg, http), {}, 0
        for idx, cid in enumerate(authorized):
            if done >= args.limit:
                break
            tools = SalesforceTools(rest, Guard(frozenset({key15(cid)}), max_writes=3))
            ev = run_agent(client, tools, cid, REASONS[idx % len(REASONS)], model=cfg.model, max_steps=args.max_steps)
            (run_dir / f"{key15(cid)}.json").write_text(json.dumps(ev, indent=2, ensure_ascii=False))
            claims[cid] = {"source": "vultr-agent", "outcome": ev["outcome"], "final_message": ev["final_message"],
                           "steps": [{"at": st["at"], "tool": (st.get("request") or {}).get("tool") or ("final" if st.get("final") else st.get("error", "none")),
                                      "result": json.dumps(st["result"])[:300] if "result" in st else None} for st in ev["steps"]]}
            print(f"{cid}: {ev['outcome']} · {len(ev['steps'])} steps · {ev['writes']} writes")
            done += 1
            if ev["outcome"] == "uncertain_write":
                print("Stopping: a write has an uncertain outcome. Check this Case in Salesforce before continuing.")
                break
        (run_dir / "claims.json").write_text(json.dumps(claims, indent=2, ensure_ascii=False))
        print("Evidence saved in", run_dir)
        return 0
    except (QueryError, AuthError, ConfigError, PlannerError, KeyError, ValueError, OSError) as e:
        print("Operation interrupted:", type(e).__name__, str(e)[:200] if not isinstance(e, PlannerError) else e.to_public())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
