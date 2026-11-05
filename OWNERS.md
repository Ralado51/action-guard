# Donos por pasta

Uma pasta, um dono. Ninguem edita a pasta de outro; mudanca de contrato passa por `contracts/`.

| Pasta | Dono | Observacao |
| --- | --- | --- |
| `contracts/` | Claude Code | Muda so com aprovacao do Airton; avisar Codex e Gemini |
| `planner/` | Claude Code | Regra em portugues para plano de teste (Vultr Serverless Inference) |
| `engine/` | Codex | Verificacoes deterministicas; comparar com `tests/oracle.py` |
| `connector/` | Codex | Salesforce e Agentforce; snapshots antes e depois |
| `sandbox/` | Codex | Executor Docker isolado e testes de contencao |
| `web/` | Codex | API e interface assumidas por instrucao explicita do Airton em 05/11/2026; contrato em `docs/API.md` |
| `demo/` | Airton | Dados sinteticos, Flow, configuracao do agente |
| `infra/` | Airton e Codex | Scripts e imagens da Vultr |
| `docs/`, `README.md` | ChatGPT (revisao) | `docs/API.md`, `docs/CONTRACTS.md` e `docs/DECISIONS.md` sao do Claude Code |
| `STATUS.md` | quem mudou algo | Atualizar a cada entrega |
| `tests/` | dono do modulo testado | `tests/oracle.py` e `tests/test_contracts.py` sao do Claude Code |

