# Outcome audit (read-only)

**Question:** out of all the times the agent said it performed the action, in how many does the data confirm the result the business rule expects?

The flow "plan → approval → execution → verification" remains the **acceptance test** (before go-live). The audit is the production use: it reuses the approved plan and the verification engine, but **runs nothing and writes nothing to Salesforce**.

## How it works

1. An approved plan (current hash) defines the checks. The test plan's `case_id` is ignored: the plan is used as the rule template.
2. Record selection:
   - `--case-ids file`: the Cases the agent **reported** as closed. This catches "said it closed it, but did not".
   - `--since 2026-11-01T00:00:00Z [--modified-by <AgentUserId>] [--limit N]`: Cases already closed in the window. It **cannot see** a Case the agent claimed to close that is still open.
3. Reads via REST (GET only): Cases and linked Tasks, in batches. A failed query never becomes "zero records": the record becomes inconclusive.
4. Deterministic evaluation of the **final state** (`audit/evaluate.py`). No LLM, no agent text.
5. Aggregation: correct-outcome rate, failures per check, the list of failing records and the observed value as evidence.
6. Summary: a deterministic server text; optionally (`--explain`) a summary written by the Vultr model.

```bash
python -m audit run --plan approved_plan.json --case-ids agent_cases.txt [--explain]
python -m audit run --plan approved_plan.json --since 2026-11-01T00:00:00Z --limit 200
```

`SF_*` credentials (and `VULTR_INFERENCE_*` with `--explain`) come from the environment. The report is saved to `runs/audit-<id>/audit_report.json` (contract `contracts/audit_report.schema.json`). It contains record Ids: do not publish reports from a real org.

## What is and is not verified

| Plan check | In the audit |
|---|---|
| field equals a fixed value (e.g. Status = Closed) | auditable |
| field not empty (e.g. reason) | auditable |
| matching linked Task, exact count | auditable (also counts a Task that existed before the action) |
| field unchanged, no unexpected change | **not auditable** (needs the previous state) |
| reason equals the test plan's reason | **not auditable** (each record has its own reason) |

Non-auditable checks appear in the report as NOT verified and never count as passed. Inconclusive records do **not** count as correct. A proven failure beats inconclusive.

## Privacy and the role of the LLM

The Vultr model does not decide any verdict. In the optional summary it receives only counts, check descriptions and the text of uncovered clauses: never record Ids or values. The output is validated (no numbers that do not exist in the data, nothing that looks like an Id, at most 700 characters); if it fails, the server summary applies. The server summary is always shown next to the model's (`summary.server_text`).

Known limit of the guard: it rejects numbers that do not exist, but a real number used in the wrong context passes. That is why the server text always stays alongside.

## Limits

- Without the "before" state there is no owner-preserved check and no unexpected-change check.
- A window sample suffers from survivorship bias (only Cases that are already closed).
- The rate only measures the rules that were written and approved; partial coverage appears in `coverage_status`.
- No scheduling or alerts in this version.
- Result on the real developer org (synthetic Cases, run through the web UI): three Cases audited, one met every auditable check, one failed with no follow-up Task and one with two. Three plan checks were reported as not auditable. This is a functional check on a handful of records, not a measurement of agent accuracy.
