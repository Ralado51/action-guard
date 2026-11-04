# Action Guard

Verifica se uma acao executada por um Flow ou agente no Salesforce produziu o resultado de negocio esperado. Uma regra funcional em portugues vira um plano de teste revisavel; a acao roda numa org de testes com dados sinteticos; as verificacoes comparam o estado dos registros monitorados antes e depois e geram um relatorio com evidencias.

MVP (hackathon Vultr Agent Rush): um processo, **encerrar um Case**, com tres regras: motivo de encerramento preenchido, proprietario mantido e Task de acompanhamento criada e vinculada ao Case. Detecta violacoes em testes; nao promete bloqueio preventivo em producao nem rollback.

> Estado: esqueleto. Contratos, exemplos e testes de contrato existem. Planner, conector Salesforce, executor isolado e interface ainda nao foram implementados. Veja `STATUS.md`.

## Como rodar

```bash
git clone https://github.com/Ralado51/action-guard.git && cd action-guard
pip install -r requirements-dev.txt
make test          # 114 testes de contrato, oraculo e API
make run           # API em http://localhost:8000/health
make docker-test   # a mesma suite dentro da imagem (Python 3.12)
```

## Estrutura

| Pasta | Conteudo |
| --- | --- |
| `contracts/` | JSON Schemas, exemplos sinteticos e hash do plano |
| `docs/` | `API.md`, `CONTRACTS.md`, `DECISIONS.md` |
| `web/` | API FastAPI (esqueleto) e interface |
| `planner/`, `engine/`, `connector/`, `sandbox/`, `demo/`, `infra/` | Reservadas; ver `OWNERS.md` |

## Seguranca

Somente dados sinteticos. Nenhuma credencial no repositorio; use `.env` (fora do git, modelo em `.env.example`). O executor isolado verifica dados ja coletados e nunca recebe credenciais.

Licenca: MIT.
