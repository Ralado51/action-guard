# Hackathon submission text

Text as entered on lablab.build for **Vultr: Agent Rush**, track
**C2 - Powering the Future of Work**. Kept here so the repository and the
submission say the same thing. No secrets belong in this file.

## Title

Action Guard: Did the AI agent really do the job?

## Short description

Action Guard checks the Salesforce record, not the agent's word. It verifies each condition of an approved rule, tracks every divergence to a fix with a new audit, and keeps a hash-verifiable evidence dossier.

## Long description

AI agents report "done" in confident language. Action Guard checks whether the business result actually exists in the system of record.

A business rule (for example: close the Case, record a closure reason, create exactly one follow-up Task) is turned into a plan of checkable conditions with Vultr Serverless Inference. A person approves the plan, and its hash is bound to every audit. Audits are read-only: they compare the final Salesforce state with the plan, and anything that cannot be confirmed stays "not confirmed" instead of counting as correct. Conditions that cannot be observed from the final state are listed, never hidden.

A divergence becomes a finding with an owner. It closes only after a new audit with the same plan passes, or when someone accepts the risk in writing; the original failure is never rewritten. Each finding exports a SHA-256 evidence dossier that anyone can verify in the browser or the CLI.

What we ran: 20 real Cases handled by two executors, a Vultr-hosted agent and a Salesforce Agentforce agent, all audited by the same verifier (all passed every auditable check). To test the verifier itself, we injected 4 known faults plus 3 correct controls in a developer org: it flagged 4 of 4 faults and 0 of 3 controls. The guided live demo lets a visitor open a synthetic Case, see the result checked, and walk a controlled fault through detection, fix and re-audit.

Honest limits: the faults were injected by us, we have not yet seen a spontaneous agent failure, names are declared on a shared token (prototype), and hashes show integrity, not authorship. The backend runs on a Vultr VM.

## Form fields

- Participation mode: Online
- Categories: Customer Support, Productivity, Security
- Event track: C2 - Powering the Future of Work
- Technologies selected on lablab.build: Vultr, rest api

## Technologies actually used

The lablab.build list has no entry for most of these, so they are named here
and in the long description instead.

- Vultr Cloud Compute (backend VM) and Vultr Serverless Inference (plan drafting) with the DeepSeek model `deepseek-v4.1-flash-1017`, selected by `VULTR_INFERENCE_MODEL`
- Salesforce (developer org, REST API, read-only audits)
- Salesforce Agentforce (second executor agent)
- Python and FastAPI (backend and web app)
- Docker Compose (deployment on the Vultr VM)

## Links

- Live demo: https://guard.jjnetwork.com.br
- Repository: https://github.com/Ralado51/action-guard
