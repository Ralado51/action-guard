# Action Guard

**Did the AI agent's action actually produce the business result it was supposed to?**

Action Guard verifies the outcome of an Agentforce agent's action in Salesforce using before/after evidence, deterministic checks and a plan that a human approves by hash. The LLM helps to *write* the verification plan. It never decides a verdict.

Built for the Vultr Agent Rush hackathon (lablab.ai). Single process in this MVP: **closing a Case**.

## See it without credentials

The home screen is a results view: *"Your agent reported 20 Cases closed. 13 met the business rule."* It shows each Case as one cell, which checks failed, and per record what the agent said against what the data shows (expected × found). The default population is **synthetic** (20 invented Cases, labeled as such, no Salesforce connection) but is evaluated by the same deterministic audit engine as real Cases. A real read-only audit can be opened in the same view. Creating the rule and approving the plan live under *Verification setup*.

## The problem

An agent says "Case closed, follow-up task created". The conversation looks fine, so the team ships it. Nobody checks the records. Agent trust is hard to earn precisely because the agent's own answer is narrative, not evidence.

## How it works

```
business rule (plain English)
        │  Vultr Serverless Inference proposes a test plan
        ▼
reviewable plan ──► clause-by-clause rule coverage (what is NOT verified is stated)
        │  human approves the plan hash (any edit invalidates the approval)
        ▼
Agentforce Agent API runs the action once (never retried)
        │
        ▼
before/after snapshots ──► deterministic engine ──► evidence report
```

1. **Plan.** A rule such as *"When closing a Case, record the given reason, preserve the owner and create exactly one linked follow-up task."* becomes six checks (status closed, reason filled, exact reason, owner unchanged, exactly one linked Task, no unexpected change). The server enforces mandatory invariants; the model cannot weaken them.
2. **Coverage.** The server splits the rule into clauses and marks each one `covered`, `not_verifiable` or `conflicts_with_policy`. The model's mapping is only a proposal: the server downgrades anything it cannot support, and the approver must confirm every clause. A green report means *the listed checks passed*, not *the whole rule was met*.
3. **Approval.** The plan, the Case and the version are bound by a SHA-256 hash. Editing the plan invalidates the approval.
4. **Execution.** One call to the Agentforce Agent API. A timeout is treated as *uncertain* and needs human reconciliation; there is no automatic retry.
5. **Verification.** A deterministic engine compares the before and after snapshots. Missing evidence is `inconclusive`, never `passed`.
6. **Audit mode (read-only).** After the agent has been running, point the approved plan at the Cases the agent reported as closed and measure how many actually satisfy the auditable checks. Checks that need the previous state (owner preserved, no unexpected change) are reported as **not verified**, not as passed. See [`docs/AUDIT.md`](docs/AUDIT.md).

## What is proven, and what is not

Verified:

- 400 automated tests pass (Python 3.12 and 3.13) with Salesforce and Vultr **simulated**. Several safety guards were mutation-checked.
- Against a real Salesforce developer org (synthetic data only), the operator reported running the full CLI flow once: plan from real Describe metadata, Case binding, hash approval, Agentforce execution, six checks `passed`.
- Plan generation with the real Vultr model and real Describe metadata works end to end in the web UI. The server correctly downgraded the clause *"Verify the changes using the before and after data"* to **not verified**.
- Audit mode run on synthetic Cases in the real org (three audited): it reported 1 of 3 records meeting every auditable check, flagged the Case with no follow-up Task (0 found, 1 expected) and the Case with two (2 found, 1 expected), and listed three checks as not auditable.

Not proven:

- The public demo URL runs in **demo mode**: real execution is blocked on the server. Generation, review, approval and the read-only audit work.
- There is no isolated sandbox for model-generated code, and this project does not claim one.
- The coverage heuristics use a finite vocabulary (English and Portuguese). Wording outside it is downgraded (safe), but a clause about something unmonitored phrased with a monitored check's own words can be marked covered. Two such gaps are documented in the labeled set. The per-clause human confirmation is the last barrier.
- Only the Case and its linked Tasks are observed. Polling stops at the first snapshot where everything passes, so late effects are not captured.
- Market demand is a hypothesis. It has not been validated with customer interviews.

## Run it

```bash
git clone https://github.com/Ralado51/action-guard.git && cd action-guard
pip install -r requirements-dev.txt
python -m pytest -q                       # full suite, no network
uvicorn web.app.main:app --port 8000      # local API + UI (see .env.example)
```

Configuration is read from the environment (see `.env.example`; never commit real values):

| Variable | Purpose |
| --- | --- |
| `VULTR_INFERENCE_BASE_URL`, `VULTR_INFERENCE_API_KEY`, `VULTR_INFERENCE_MODEL` | plan generation |
| `VULTR_INFERENCE_MAX_TOKENS`, `VULTR_INFERENCE_TIMEOUT_SECONDS` | optional; reasoning models need a larger budget than the default |
| `SF_LOGIN_URL`, `SF_API_VERSION`, `SF_CLIENT_ID`, `SF_CLIENT_SECRET`, `SF_AGENT_ID` | Salesforce (External Client App, client credentials) and the agent |
| `ACTION_GUARD_API_TOKEN` | access token for the web API (at least 32 random characters) |
| `ACTION_GUARD_DEMO_MODE` | `true` blocks real execution on the server |
| `SF_METADATA_PATH` | Describe metadata JSON used by the planner |

**Deployment (demo mode on a VM):** see [`infra/README.md`](infra/README.md). The container runs as an unprivileged user with a read-only filesystem, binds to loopback only and keeps state in a named volume; put a TLS terminator in front of it.

**CLI:**

```bash
python -m planner --rule contracts/examples/rule.json --fixture-metadata --reason "Resolved - Customer confirmed"
python -m orchestrator prepare ...        # draft a plan from real Describe metadata
python -m orchestrator run ...            # approve the hash and run one attempt (needs real credentials)
python -m audit run --plan approved_plan.json --case-ids ids.txt --explain
```

## Layout

| Folder | Content |
| --- | --- |
| `planner/` | rule → plan (Vultr), server-side invariants, clause coverage |
| `engine/` | deterministic checks over before/after snapshots |
| `connector/`, `orchestrator/` | Salesforce REST and Agent API, one-shot execution, evidence |
| `audit/` | read-only outcome audit of already-closed Cases |
| `web/` | FastAPI API and the review/approval/audit UI |
| `infra/` | hardened container and Compose files |
| `contracts/` | JSON Schemas, synthetic examples, plan hashing |
| `docs/` | API, contracts, planner, audit, decisions |

## Security notes

Synthetic data only. No credentials in the repository. The LLM never sees Salesforce credentials, never approves a plan and never produces a verdict; the audit summary it may write receives counts only (no record Ids or values) and is validated against the numbers, with the server-generated text always shown next to it. A single shared access token identifies the operator: this is not multi-user authentication.

License: MIT.
