# Planner (Vultr Serverless Inference)

Rule (English or Portuguese) → **draft** `test_plan`. It receives no Salesforce credentials, creates no Case, runs no agent and approves no plan. Internal interface (not a public contract): `planner.create_plan`, `planner.bind_case`, `planner.ready_for_approval`.

## Inputs

- `rule`: `contracts/rule.schema.json`, text up to 4000 characters (the field is named `text_pt` for historical reasons; it accepts English).
- `metadata_context` (provided by the backend; the planner does not query the org):
  ```json
  {"source": "salesforce_describe | fixture", "collected_at": "<instant>",
   "objects": {"Case": {"readable": true, "fields": {"Status": {"type": "picklist", "readable": true, "values": ["..."]}}}}}
  ```
  A missing or unreadable object or field, or one without `readable: true`, counts as nonexistent. With `source: "fixture"` the result carries `metadata_source: "fixture"` and a warning; it is never presented as real metadata.
- `action_context`: `{"process": "close_case", "closure_reason", "task_subject", "agent_name"?, "case_id"?}`. `closure_reason` must be one of the four known values **and** exist in the picklist of the context; `case_id`, if present, comes from the backend/operator.

Insufficient context, a missing or unknown reason, a rule that mentions a different reason from the requested one, or an invalid Case raise `insufficient_context` **before any model call**. There is no silent choice.

## Who decides what

The model proposes only `monitored`, `async_window` and `checks` (with descriptions, written in English). The server assigns `plan_id`, `rule_id`, version, action (`agentforce_agent_api`), reason, Task Subject, preconditions, `check_id`, `approval = null` and the hash. Extra keys in the response (including `approval`, `plan_hash`, `action`) are dropped with a warning.

MVP invariants (a proposal that omits, duplicates, contradicts or widens them is **rejected**, not silently fixed): Status `Closed`; non-empty reason; reason equal to the requested one; `OwnerId` unchanged; `record_created` on Task by `WhatId` with `expected_count` 1 and `match.Subject` equal to the requested one; `no_unexpected_change` with `allowed_changes` exactly `Case.Status`, `Case.Closure_Reason__c`, `Case.ClosedDate`, `Case.IsClosed`. Up to 4 extra checks, only on other Case fields.

Limits: 10 checks; 25 fields per object; only the Case and Task objects; `max_wait_seconds` <= 120 and at most 60 queries; fields checked against the context; picklist values checked. After that: the `test_plan` JSON Schema and `validate_plan_semantics`.

## Model calls

`POST {VULTR_INFERENCE_BASE_URL}/chat/completions`, Bearer, `VULTR_INFERENCE_MODEL`, `temperature` 0, `max_tokens` 2000 by default, timeout 60 s by default. Both limits can be changed with `VULTR_INFERENCE_MAX_TOKENS` (256–32000) and `VULTR_INFERENCE_TIMEOUT_SECONDS` (5–600): reasoning models spend tokens before answering, and with the default budget a plan can be cut off (`finish_reason=length`). No `response_format`: validation is local. It uses `choices[0].message.content`; it rejects a `finish_reason` other than `stop` (including `length`), `tool_calls`, empty content and a malformed body; `reasoning` is not used.

Total budget of **2 HTTP requests per operation**, counting generation, correction and retry. 401/403: failure without retry. Timeout: failure without retry. 429/5xx: one retry (1 s) if budget remains. If the first response is rejected by the validator, the second call resends the problems (correction); if it fails again, an error is raised. There is no fallback to a fixture or a ready-made plan.

Errors (`PlannerError.to_public()`): `config`, `auth`, `timeout`, `rate_limit`, `upstream`, `invalid_response`, `schema`, `semantics`, `insufficient_context`, with a safe message and `details` produced by this code. The raw body, headers and the key never leave.

## Case binding (decision)

The executor requires `action.input.case_id` inside the approved hash. Chosen flow:

1. `create_plan` → a draft without `case_id` (or with it, if the backend already has it) and `approval = null`.
2. The **trusted backend** obtains the Case: it provisions a new synthetic Case (`orchestrator.run.create_synthetic_case`) or uses a test Case explicitly provided by the operator. The LLM never takes part.
3. `bind_case(plan, case_id)` writes the Id, increments `plan_version`, recomputes the hash and clears the approval.
4. Human review of the already-bound plan; approval of the current hash; `execute_run`.

Any later change (including swapping the Case or editing the reason) changes the hash and invalidates the approval. `ready_for_approval(plan)` lists pending items (for example a missing `case_id`); even if someone approves a draft without a Case, `execute_run` blocks before talking to the agent (covered by a test).

## Smoke test on the VM (only generates a plan)

Key in the environment (`VULTR_INFERENCE_API_KEY`, `VULTR_INFERENCE_MODEL`; never in chat):

```bash
python -m planner --rule contracts/examples/rule.json --fixture-metadata \
  --reason "Resolved - Customer confirmed" --subject "Action Guard - Case closure follow-up"
```

It prints the plan, `plan_hash`, model, token usage and metadata source. With `--fixture-metadata` the source is `fixture`; for real metadata pass `--metadata file.json` generated by the backend. There is no call to Salesforce or to the agent.

## Rule coverage per clause

Problem: a user can write a requirement that no check covers and still receive a green report. The plan now carries `rule_coverage`.

- The **server** splits the rule into clauses `cl_01..cl_12` (the excess becomes the last clause, `not_verifiable`). The model receives the clauses and returns `coverage` (clause_id, status, check_ids, reason) in the same call: no extra calls.
- Statuses: `covered`, `not_verifiable`, `conflicts_with_policy`. Server guards (`planner/coverage.py`): `covered` requires existing check_ids and a clause vocabulary compatible with the topic of at least one cited check, otherwise it is downgraded; topics outside the scope (email, notification, SLA, other objects) become `not_verifiable`; patterns such as "do not create a task", "the reason is optional", "the owner may change" become `conflicts_with_policy`. The model never promotes. The vocabulary is bilingual (English and Portuguese).
- An existing `check_id` does **not** prove coverage; that is why the labeled set and the evaluator exist: `python -m planner.coverage_eval tests/data/rule_coverage_labeled.json --fixture-metadata` measures `false_covered` (dangerous, must be 0 outside the documented gaps), `false_uncovered` and `conflict_missed`. Known gaps are marked `known_gap` in the set. The set has 20 Portuguese and 12 English rules.
- Coverage is part of the hash; approval requires a per-clause confirmation; the report carries `coverage_status` (`complete`/`partial`/`not_assessed`) and, when partial, the first limitation says which clauses were left out.
- Limit: coverage by vocabulary is a finite heuristic, not semantic proof. Human confirmation is the final barrier.
