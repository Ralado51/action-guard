# Contrato da API

Estado: `GET /health` implementado. Todas as outras rotas existem em `web/app/main.py`, validam o corpo da requisicao e respondem `501 {"detail":"not implemented"}` ate o motor, o planner e o conector existirem.

Os formatos de plano, snapshot, resultado e relatorio estao em `contracts/*.schema.json`; exemplos em `contracts/examples/`.

## Rotas

| Rota | Corpo | Sucesso | Erros |
| --- | --- | --- | --- |
| `GET /health` | | `200 {"status":"ok","service":"action-guard"}` | |
| `POST /api/plans` (create_plan) | `{"rule_text_pt": str, "process": "close_case"}` | `201` plano em rascunho (`test_plan`), sem aprovacao | `422` corpo invalido; `502` planner falhou |
| `GET /api/plans/{plan_id}` | | `200` `test_plan` | `404` |
| `PUT /api/plans/{plan_id}` | `{"plan": test_plan}` | `200` plano com `plan_version` + 1, novo `plan_hash`, `approval` nulo | `404`; `422` plano fora do schema |
| `POST /api/plans/{plan_id}/approve` | `{"approved_by": str, "approved_plan_hash": "sha256:..."}` | `200` plano com `approval` preenchido | `404`; `409` se o hash aprovado nao for o hash atual |
| `POST /api/runs` (execute_plan) | `{"approved_plan_id": str}` | `202 {"run_id": str}` | `404`; `409` se o plano nao estiver aprovado ou a aprovacao nao valer para o hash atual |
| `GET /api/runs/{run_id}` | | `200 {"run_id", "state": "queued\|running\|completed\|error", "report"?}` | `404` |
| `GET /api/runs/{run_id}/report` | | `200` `report` | `404`; `409` se a execucao nao terminou |

## Regras

1. `execute_plan` executa exatamente a versao aprovada: o servidor compara o `plan_hash` atual com `approval.approved_plan_hash` (ver `contracts/plan_hash.py`).
2. Editar um plano aprovado nunca preserva a aprovacao.
3. Cada execucao cria os proprios dados sinteticos; nunca reutiliza um Case ja encerrado.
4. O relatorio sempre informa `executed_via`. `flow_direct` nao comprova integracao com Agentforce.
5. Erro de consulta ou evidencia insuficiente resulta em `inconclusive`, nunca em `passed`.
