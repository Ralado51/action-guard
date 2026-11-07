# API and interface — test operator

Implemented in `web/app/`. Real services: generation through Vultr; execution through Agentforce; validation through snapshots. No fixture fallback. Internal use with one operator and one Uvicorn process. It does not include an isolated executor or multi-user authentication.

## Access and configuration

`/` and `/static/*` serve the interface; `/health` and `/api/capabilities` are public. All other `/api/*` routes require `Authorization: Bearer <ACTION_GUARD_API_TOKEN>`. Without a configured token the backend fails closed (503); an invalid token returns 401. The application token is typed into the page and kept only in the tab's memory, not in localStorage. Salesforce and Vultr receive only credentials configured on the server, never from the browser. `approved_by` is an identification declared by the operator authenticated through the shared token, not an identity verified by SSO.

Backend variables: the `SF_*` and `VULTR_INFERENCE_*` ones from `.env.example` (including the optional `VULTR_INFERENCE_MAX_TOKENS` and `VULTR_INFERENCE_TIMEOUT_SECONDS`), `ACTION_GUARD_API_TOKEN`, `ACTION_GUARD_DEMO_MODE`, `SF_METADATA_PATH` and `ACTION_GUARD_DATA_DIR`. The metadata file must come from Salesforce Describe, in the planner format. Picklist values and fields are validated; the collection date is shown as provenance, but there is no automatic refresh. Do not publish this service without HTTPS and proper access control; for local tests, bind to 127.0.0.1 and use an SSH tunnel.

**Demo mode** (`ACTION_GUARD_DEMO_MODE=true`): `POST /api/runs` returns 403, the execution path also refuses inside the service (including queued tasks), and the UI hides the Run button. `GET /api/capabilities` returns `{"demo_mode": ..., "execution_enabled": ...}`. Generate, review, approve and audit stay available.

## Routes

| Route | Body | Result |
|---|---|---|
| GET /health | — | 200 status |
| GET /api/capabilities | — | 200 `demo_mode`, `execution_enabled` (public) |
| POST /api/plans | rule_text_pt (the field name is historical; English or Portuguese text is accepted), process=close_case, closure_reason | 201 draft test_plan |
| GET /api/plans/{id} | — | 200 test_plan |
| GET /api/plans/{id}/context | — | source/model/tokens and pending items |
| GET /api/plans/{id}/runs | — | states of the runs recorded for the plan |
| PUT /api/plans/{id} | plan, expected_plan_hash | 200 new version without approval |
| POST /api/plans/{id}/case | case_id, expected_plan_hash | 200 new bound version, without approval |
| POST /api/plans/{id}/approve | approved_by, approved_plan_hash, acknowledged_clauses | 200 approved plan |
| POST /api/audits | approved_plan_id, case_ids (up to 500) or since [+ modified_by, limit], explain | 200 audit_report (READ-ONLY; see docs/AUDIT.md) |
| POST /api/runs | approved_plan_id, expected_plan_hash | 202 run_id (403 in demo mode) |
| GET /api/runs/{id} | — | state queued/running/completed/error/blocked (blocked = nothing was sent to the agent, Case released); report or a safe error |
| GET /api/runs/{id}/report | — | 200 report; 409 if unavailable |

Common errors: 404 not found; 409 outdated version, missing Case/approval or Case already reserved; 422 invalid body/plan; 502 planner refused generation; 503 backend configuration missing/invalid. A raw upstream exception is never forwarded. Invariants, preconditions and the action cannot be weakened by editing.

## Flow and persistence

1. The backend generates a plan with server-provided metadata and an explicit reason; the user reviews scope and checks.
2. The operator provides a new synthetic Case created beforehand. This version has no automatic Case creation through the API. Binding happens before approval, with a new hash/version.
3. Approving requires the current hash, a bound Case and `acknowledged_clauses` equal to the set of `clause_id` in `rule_coverage` (409 if one is missing or extra; plans without coverage approve without the list). `rule_coverage` cannot be edited (422). Editing or binding invalidates the approval.
4. Running requires the same approved hash; one SQLite transaction reserves the Case per org and freezes the plan for the run. Another request for the same Case is blocked, even with a different plan.
5. BackgroundTasks runs the orchestrator and stores the report; the browser polls the state and shows before/after evidence together with the scope limits.

SQLite and evidence live in the `ACTION_GUARD_DATA_DIR` volume. Keep the volume across restarts. Write operations use transactions to avoid concurrent double reservation. This is not a global exactly-once guarantee: another volume, server or CLI does not share this reservation. There is no automatic retry of the action.

BackgroundTasks is not a durable queue: if the process stops while a run is queued/running, the record stays in that state and is not resumed automatically. The operator must reconcile snapshots and logs before any new attempt. An error after the reservation also consumes the Case and requires review. A plan that is already reserved stays immutable in the run even if a new version is edited for review.

## Validation status

The API uses the real planner and executor; tests inject simulated transport and generation. The operator reported a real run of the CLI flow on 05/11/2026 (six checks passed). On 06/11/2026 the web UI was exercised against the real developer org with the real Vultr model: plan generation, clause coverage, Case binding, approval and a read-only audit of synthetic Cases. Real execution through this API/UI has not been run: the public deployment runs in demo mode.

## Operators

The shared `ACTION_GUARD_API_TOKEN` is the administrator credential. With it, `POST /api/operators` registers a named operator and returns a personal key (`agk_…`) once; only its sha256 hash is stored. `DELETE /api/operators/{id}` revokes it. `GET /api/operators` is public and lists names, roles and dates only. Every endpoint that accepts the shared token also accepts an operator key, and on plan approval the approver name is taken from the key, not from the request body. Operators are stored in `ACTION_GUARD_DATA_DIR/operators`. Roles are recorded for accountability; permissions are the same for every operator in this prototype.
