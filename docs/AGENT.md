# Vultr agent (second executor)

`vultr_agent/` is a small business agent hosted on Vultr that handles the same process as Agentforce: close a Case with a
reason and create exactly one follow-up Task. It uses Vultr Serverless Inference with a plain JSON protocol (one action per
turn, validated by the server). It has three tools: `read_case`, `close_case` and `create_followup_task`. Closing and creating
the Task are separate calls, so the agent has to do both.

Action Guard then audits the records read-only with the approved plan. The agent never sees the plan, cannot change it and
does not grade itself: its final message is a *claim*, shown next to what the data says.

## Guards (enforced in code, not in the prompt)

- Only Case Ids in `authorized.json` can be touched, one Case per run; 15 and 18-character forms are both recognized.
- A Case is written only if its Subject starts with `[SYNTHETIC]`.
- At most 3 writes and `--max-steps` model calls per Case.
- A write with an uncertain outcome (timeout or HTTP 5xx) is never repeated; the run stops and a human reconciles.
- `--confirm-write` is mandatory.

## Usage (run on the VM, outside the public container)

```bash
python -m vultr_agent seed --count 1 --out agent_runs
python -m vultr_agent run --authorized agent_runs/authorized.json --limit 1 --confirm-write
python -m audit run --plan approved_plan.json --case-ids agent_runs/ids.txt \
    --agent-runs agent_runs/vultr-run-XXXX/claims.json --list-all
```

Evidence per Case (`<run>/<case15>.json`): source, model, task text, every step with timestamp, tool call and result,
final message, outcome and write count.

## What this does not prove

- It is not an isolated sandbox; it limits *where* the agent can write, not what code it could run.
- With a handful of Cases no ranking between agents is possible or claimed.

## Second executor: Agentforce on the same Cases

```bash
python -m agentforce_runner run --authorized agent_runs/authorized.json --limit 10 --confirm-write
python -m audit run --plan approved_plan.json --case-ids ids.txt \
    --agent-runs vultr-run-XXXX/claims.json --agent-runs agentforce-run-YYYY/claims.json --list-all
```

Each Case is sent to the Agentforce Agent API once (never repeated; an uncertain outcome stops the run). Its reply is stored as a
claim. The audit labels every Case with its executor and shows counts per executor, never a ranking: the samples are small and the
two agents receive different instructions (Agentforce keeps its original instruction; the Vultr agent gets the business rule).

## Reservation ledger (no re-sending)

Both runners write `ledger.jsonl` next to `authorized.json` and reserve each Case **before** sending anything. A Case that is
already in the ledger is skipped on every later run, whatever happened the first time (finished, uncertain, or a crash after the
reservation), because re-sending could duplicate Tasks. Cases from earlier run folders are imported as already handled. To try
again, reconcile the Case in Salesforce and use a new Case. A refusal *after* a message was sent is not treated as proof that
nothing ran: the run stops and the Case must be checked.
