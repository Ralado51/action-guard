# Acceptance layer

Turns a detected divergence into a tracked finding that closes only with evidence.

- **Policy**: each plan condition has a severity (`critical` or `operational`), shown beside the result. There is no single trust score; a critical condition the audit cannot observe stays listed.
- **Findings**: `opened → assigned → fix recorded → revalidated → closed`, or `risk accepted` with a written justification (kept as unresolved). Revalidation needs a NEW audit with the same plan hash, run after the fix. History is append-only (`events.jsonl`).
- **Dossier**: bundle of the finding, its reports and a SHA-256 manifest. `python -m acceptance verify --bundle X.json`, or the Acceptance tab in the browser. This proves integrity, not authorship.
- **Calibration**: `python -m calibration seed|score|remediate` injects known faults and controls (synthetic Cases, `--confirm-write` required) and scores the verifier against the ground truth.

Limits: names are declared on a shared token (prototype, not authenticated identities); injected faults say how the verifier behaves, not how often real agents fail; owner-preserved and unexpected-change checks still need a before-state and stay declared gaps.
