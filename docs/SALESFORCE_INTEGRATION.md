# Integracao Salesforce: estado e evidencias

Base: dossie do operador de 04/11/2026 (nao versionado: contem identificadores da org). Marcacao: **[confirmado]** relatado como funcionando pelo operador; **[inferencia]** deduzido por nos; **[pendente]** nao verificado.

## Codigo (este repositorio)

- `connector/`: configuracao por ambiente (`SF_LOGIN_URL`, `SF_API_VERSION`, `SF_AGENT_ID`, `SF_CLIENT_ID`, `SF_CLIENT_SECRET`), OAuth Client Credentials, consultas REST com paginacao e `queryAll`, coletor de snapshots, cliente do Agent API. Somente biblioteca padrao; transporte injetavel.
- `orchestrator/`: `execute_run` (portoes de aprovacao, snapshot, acao unica, janela assincrona, avaliacao, relatorio) e `EvidenceStore` (um JSON atomico por etapa em `runs/<run_id>/`, ignorado pelo git).
- `engine.evaluate` e o avaliador padrao de `execute_run`; a injecao de outro avaliador continua disponivel. Os testes de integracao usam o motor real e os testes de paridade o comparam com `tests/oracle.py`, sem dependencia do oraculo em producao.
- `tests/sim.py` e `tests/test_salesforce_integration.py`: Salesforce simulado, sem rede.

## Estado

| Item | Estado |
|---|---|
| Flow `Action_Guard_Close_Case` (motivo, fechamento, mensagens) e acao do agente | [confirmado] funcionando |
| `Closure_Reason__c` picklist; Status `New/Working/Escalated/Closed` | [confirmado] |
| Client Credentials; Agent API (sessao, mensagem sincrona, encerramento) | [confirmado] numa execucao real |
| Execucao real: Case `Closed`, motivo preenchido, dono preservado, 1 Task vinculada | [confirmado] por consulta; motivo e Subject completos so por screenshot truncado |
| Subject exato da Task criada pelo Flow | [pendente] confirmar por leitura estruturada; o plano usa `Action Guard - Case closure follow-up` como **valor esperado ilustrativo** |
| Texto de `closure_reason` aprovado vs. gravado | [pendente] comparar por JSON; nao usar a prosa do agente |
| Idempotencia do Flow / caminhos de falha | [inferencia] ausentes: ja houve 4 Tasks em um Case de desenvolvimento |
| Codigo contra a org real | [pendente] nunca executado; so respostas simuladas |
| Formato de erros reais do Agent API, limites de taxa | [pendente] |

## Primeira execucao real (somente apos revisao)

1. Revisar este codigo e os testes.
2. Operador exporta as variaveis no ambiente (nunca no chat ou no git).
3. Criar um Case sintetico **novo** (`create_synthetic_case`) e inserir seu ID em `action.input.case_id` e o motivo em `action.input.closure_reason` **antes** de calcular o hash e aprovar. Exemplos sem Case vinculado nao sao executaveis.
4. Uma unica execucao. Nao reexecutar em Case ja encerrado; o Case de evidencia do dossie nao deve ser reutilizado.
5. Se der timeout, reconciliar pelos snapshots e revisao humana; nao repetir automaticamente.


## Bloqueios reforcados

O executor exige Case ID no plano aprovado e igualdade com o Case da execucao. Campos monitorados ausentes no snapshot anterior e Case principal nao encontrado bloqueiam antes de abrir sessao. Null explicito continua sendo evidencia coletada. Respostas REST sem `done` booleano sao falha de coleta, nunca lista completa.

## Avaliador deterministico

`engine.evaluate(plan, before, after)` retorna `(check_results, unexpected_changes)`. Implementa field_equals, field_not_empty, field_unchanged, record_created e no_unexpected_change. Resultados incluem IDs, campos e valores observados. Exclusao confirmada difere de desaparecimento sem prova; null difere de campo ausente. Contagem usa IDs novos vinculados e filtros match. Candidato sem campos necessarios impede sucesso; duplicata comprovada falha. Mudanca inesperada comprovada prevalece sobre evidencia insuficiente em outro campo. Identidades/fases incompativeis ou observacoes duplicadas nao estabelecem sucesso. O escopo continua limitado aos registros e campos monitorados.

Validacao local: 197 testes em Python 3.12.14, incluindo comparacao independente com oraculo. Docker nao disponivel no ambiente desta entrega; executar `make docker-test` na VM Vultr apos checkout desta branch. Nenhuma chamada real ao Salesforce nesta entrega.

## Docker validado pelo operador — 2026-11-05

Na VM Vultr, `sudo make docker-test` concluiu com `197 passed, 1 warning in 0.74s`, conforme saida fornecida pelo operador. A suite usa Salesforce simulado; isso valida build e testes no container, nao o conector contra a org real. O comando sem sudo falha por permissao no socket nesse usuario.
