# Acceptance layer

Turns a detected divergence into a tracked finding that closes only with evidence.

- **Policy**: each plan condition has a severity (`critical` or `operational`), shown beside the result. There is no single trust score; a critical condition the audit cannot observe stays listed.
- **Findings**: `opened → assigned → fix recorded → revalidated → closed`, or `risk accepted` with a written justification (kept as unresolved). Revalidation needs a NEW audit with the same plan hash, run after the fix. History is append-only (`events.jsonl`).
- **Dossier**: bundle of the finding, its reports and a SHA-256 manifest. `python -m acceptance verify --bundle X.json`, or the Acceptance tab in the browser. This proves integrity, not authorship.
- **Calibration**: `python -m calibration seed|score|remediate` injects known faults and controls (synthetic Cases, `--confirm-write` required) and scores the verifier against the ground truth.

Limits: names are declared on a shared token (prototype, not authenticated identities); injected faults say how the verifier behaves, not how often real agents fail; owner-preserved and unexpected-change checks still need a before-state and stay declared gaps.

Guards added after review: a report row is trusted only if its status follows from its own per-check results (applies when opening and when revalidating); a dossier is exported only from reports whose hash matches the one recorded in the finding's events, and a masked dossier's masking record must match those events.

Completeness: when a finding opens, the checks the policy observes are recorded in the event (`expected_checks`); a revalidation report must carry exactly that set for the Case, with no missing, duplicated or unknown check. Findings opened before this guard cannot be revalidated. The report totals and per-check summary are not cross-checked, and the plan itself is not re-evaluated here: this layer trusts a report that carries the right plan hash and internally consistent rows.

Delivery limits: findings are managed through the CLI (the web tab shows the recorded flow; there is no API to assign, fix or close). The recorded cycle proves the Case was regularised, not that the agent's behaviour was corrected in a new run.

## Guided walkthrough
The landing view ("Understand in 60 seconds") tells the story of one Case from the recorded data: agreement, claim, check, decision, fix and new audit. It keeps two origins apart: the real agent run (the agent's own report) and the controlled detection test (a fault injected by us, no agent involved). It uses `recorded_flow.json` and `recorded_run.json`; nothing runs live.
