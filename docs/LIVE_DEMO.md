# Live demo (off by default)

A visitor opens a synthetic Case, a Vultr agent handles it (or the server applies a labeled controlled fault), and Action Guard checks the record. Two origins stay separate on screen: a real agent run, and a fault injected by us with no agent involved.

## What the server enforces
- The browser sends only a session id, a scenario key (fixed list) and a mode. It never chooses Case Ids, tool arguments or the plan; extra fields are rejected.
- Every session creates its own Case (Subject starts with `[SYNTHETIC]`); the agent's tools can touch only that Case.
- An agent run starts once per session (atomic state change plus the reservation ledger). A double click or reload never re-runs it. An uncertain write blocks any repeat; checking stays available.
- Limits count sessions STARTED, failed ones included, and persist across restarts (sqlite): hourly, daily, at most 2 running, wrong access codes locked after 20 per hour.
- The check uses a fixed approved plan from a file the operator mounts; the visitor never approves JSON.
- Reports and agent messages are masked before leaving the server; sessions expire after 6 hours.
- Separate from `ACTION_GUARD_DEMO_MODE`: operational endpoints stay blocked on the public instance.

## Turning it on (operator)
Add to the private env file: `ACTION_GUARD_LIVE_DEMO=on`, `ACTION_GUARD_LIVE_CODE=<8+ characters>`, `ACTION_GUARD_LIVE_DAILY_LIMIT=<n>`, optional `ACTION_GUARD_LIVE_HOURLY_LIMIT` (default 4). Export `ACTION_GUARD_LIVE_PLAN_FILE` (host path of an approved plan JSON) before `docker compose up`. Missing or invalid settings keep it off. Remove `ACTION_GUARD_LIVE_DEMO` (or set it to `off`) and restart to switch it off.

## Limits
Checks the outcome of closing a Case with a follow-up Task. It does not show that the customer's problem was resolved, and the customer message is a fixed entry, not a free conversation. Names are declared, not authenticated. The Salesforce record is shown through the API, not an embedded Salesforce page.
