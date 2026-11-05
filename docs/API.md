# API e interface — operador de testes

Implementada em `web/app/`. Servicos reais: geracao via Vultr; execucao via Agentforce; validacao pelos snapshots. Sem fallback para fixture. Uso interno com um operador e um processo Uvicorn. Nao inclui executor isolado ou autenticacao multiusuario.

## Acesso e configuracao

`/` e `/static/*` servem a interface; `/health` e publico. Todas as rotas `/api/*` exigem `Authorization: Bearer <ACTION_GUARD_API_TOKEN>`. Sem token configurado o backend falha fechado (503); token invalido resulta em 401. O token da aplicacao e digitado na tela e fica somente na memoria da aba, nao no localStorage. SF e Vultr recebem somente credenciais configuradas no servidor, nunca pelo navegador. `approved_by` e uma identificacao declarada pelo operador autenticado pelo token compartilhado, nao identidade verificada por SSO.

Variaveis backend: as `SF_*` e `VULTR_INFERENCE_*` de `.env.example`, `ACTION_GUARD_API_TOKEN`, `SF_METADATA_PATH` e `ACTION_GUARD_DATA_DIR`. O arquivo de metadados deve vir de Salesforce Describe, no formato do planner. Valores de picklist e campos sao validados; a data de coleta e exibida como proveniencia, mas nao ha refresh automatico. Nao publicar este servico sem HTTPS e controle de acesso adequados; para o teste local, use bind em 127.0.0.1 e tunel SSH.

## Rotas

| Rota | Corpo | Resultado |
|---|---|---|
| GET /health | — | 200 status |
| POST /api/plans | rule_text_pt, process=close_case, closure_reason | 201 test_plan em rascunho |
| GET /api/plans/{id} | — | 200 test_plan |
| GET /api/plans/{id}/context | — | origem/modelo/tokens e pendencias |
| GET /api/plans/{id}/runs | — | estados das execucoes registradas para o plano |
| PUT /api/plans/{id} | plan, expected_plan_hash | 200 nova versao sem aprovacao |
| POST /api/plans/{id}/case | case_id, expected_plan_hash | 200 nova versao vinculada, sem aprovacao |
| POST /api/plans/{id}/approve | approved_by, approved_plan_hash, acknowledged_clauses | 200 plano aprovado |
| POST /api/runs | approved_plan_id, expected_plan_hash | 202 run_id |
| GET /api/runs/{id} | — | state queued/running/completed/error/blocked (blocked = nada enviado ao agente, Case liberado); report ou erro seguro |
| GET /api/runs/{id}/report | — | 200 report; 409 se indisponivel |

Erros comuns: 404 inexistente; 409 versao desatualizada, falta de Case/aprovacao ou Case ja reservado; 422 corpo/plano invalido; 502 planner recusou geracao; 503 configuracao backend ausente/invalida. Nunca encaminhar excecao bruta do upstream. Invariantes, precondicoes e acao nao podem ser enfraquecidos pela edicao.

## Fluxo e persistencia

1. Backend gera plano com metadados fornecidos pelo servidor e motivo explicito; usuario revisa escopo/checks.
2. Operador fornece Case sintetico novo criado previamente. Nao ha criacao automatica de Case pela API nesta versao. Vinculo ocorre antes da aprovacao, com novo hash/versao.
3. Aprovar exige o hash atual, Case vinculado e `acknowledged_clauses` igual ao conjunto de `clause_id` de `rule_coverage` (409 se faltar ou sobrar; planos sem cobertura aprovam sem lista). `rule_coverage` nao pode ser editada (422). Editar ou vincular invalida aprovacao.
4. Executar exige o mesmo hash aprovado; uma transacao SQLite reserva o Case por org e congela o plano da execucao. Outro pedido para o mesmo Case e bloqueado, inclusive com outro plano.
5. BackgroundTasks executa o orquestrador e grava relatorio; navegador consulta o estado e mostra evidencias antes/depois, com limites do escopo.

SQLite e evidencias ficam no volume ACTION_GUARD_DATA_DIR. Preservar volume entre reinicios. Operacoes de escrita usam transacoes para evitar dupla reserva concorrente. Nao e uma garantia global de exactly-once: outro volume/servidor/CLI nao compartilha esta reserva. Nao ha retry automatico da acao.

BackgroundTasks nao e fila duravel: se o processo parar com queued/running, o registro permanece nesse estado e nao e retomado automaticamente. Operador deve reconciliar snapshots/logs antes de qualquer nova tentativa. Erro depois da reserva tambem consome o Case e exige revisao. Plano ja reservado fica imutavel na execucao mesmo se uma nova versao for editada para revisao.

## Estado da validacao

API usa planner e executor reais; testes injetam transporte/geracao simulados. Teste real do fluxo CLI foi fornecido pelo operador: seis verificacoes passed em 05/11/2026. Ainda nao e evidencia de teste real desta API ou interface. Nenhuma nova acao Salesforce foi realizada durante desenvolvimento web.
