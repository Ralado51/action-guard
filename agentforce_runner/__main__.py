"""CLI: python -m agentforce_runner run --authorized agent_runs/authorized.json --limit 10 --confirm-write

One Agent API message per Case, never repeated. Only Case Ids from authorized.json are used, and only if the Case
Subject carries the synthetic marker. An uncertain outcome (timeout, 5xx) stops the run. The agent's reply is stored as
a claim (narrative), never as proof: Action Guard audits the records afterwards with the same plan.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import uuid
from pathlib import Path

from connector.agent_api import REJECTED, SENT_OK, UNCERTAIN, AgentClient
from connector.auth import AuthError, get_token
from connector.config import ConfigError, SalesforceConfig
from connector.ids import key15
from connector.rest import QueryError, SalesforceRest
from connector.snapshot import utc_now
from connector.transport import UrllibTransport
from orchestrator.run import build_request_text
from vultr_agent.tools import MARKER, REASONS


def main(argv=None, *, transport=None, secret=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m agentforce_runner")
    sub = ap.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="Send each authorized Case to the Agentforce agent once (writes to Salesforce).")
    r.add_argument("--authorized", required=True)
    r.add_argument("--limit", type=int, default=1)
    r.add_argument("--confirm-write", action="store_true")
    args = ap.parse_args(argv)
    if not args.confirm_write:
        print("Refused: pass --confirm-write to acknowledge that this run makes the Agentforce agent write to the synthetic Cases.")
        return 1
    http = transport or UrllibTransport()
    try:
        env = dict(os.environ)
        for key in ("SF_CLIENT_ID", "SF_CLIENT_SECRET"):
            if not env.get(key):
                env[key] = (secret or getpass.getpass)(key + " (hidden): ")
        cfg = SalesforceConfig.from_env(env)
        token = get_token(cfg, http)
        rest, agent = SalesforceRest(cfg, token, http), AgentClient(cfg, token, http, utc_now)
        auth_path = Path(args.authorized)
        authorized = json.loads(auth_path.read_text())["case_ids"]
        run_dir = auth_path.parent / ("agentforce-run-" + uuid.uuid4().hex[:8])
        run_dir.mkdir(parents=True)
        claims, done = {}, 0
        for idx, cid in enumerate(authorized):
            if done >= args.limit:
                break
            rows = rest.query(f"SELECT Subject FROM Case WHERE Id = '{cid}'")
            if not rows or not str(rows[0].get("Subject") or "").startswith(MARKER):
                print(f"{cid}: skipped (not found or not marked as synthetic); nothing was sent.")
                continue
            rec = agent.run_once(build_request_text(cid, REASONS[idx % len(REASONS)]))
            outcome = "finished" if rec.outcome == SENT_OK else rec.outcome
            claims[cid] = {"source": "agentforce", "outcome": outcome, "final_message": " ".join(rec.agent_text) or None,
                           "steps": [{"at": rec.started_at, "tool": "agent_api.message",
                                      "result": json.dumps({"outcome": rec.outcome, "http_status": rec.http_status})},
                                     {"at": rec.finished_at, "tool": "final" if rec.agent_text else "no_reply", "result": None}]}
            (run_dir / f"{key15(cid)}.json").write_text(json.dumps(rec.to_dict(), indent=2, ensure_ascii=False, default=str))
            print(f"{cid}: {outcome}")
            done += 1
            if rec.outcome == UNCERTAIN:
                print("Stopping: the outcome is uncertain. Check this Case in Salesforce before continuing; nothing is retried.")
                break
            if rec.outcome == REJECTED:
                print("The request was refused before the action ran.")
        (run_dir / "claims.json").write_text(json.dumps(claims, indent=2, ensure_ascii=False))
        print("Evidence saved in", run_dir)
        return 0
    except (QueryError, AuthError, ConfigError, KeyError, ValueError, OSError) as e:
        print("Operation interrupted:", type(e).__name__, str(e)[:200])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
