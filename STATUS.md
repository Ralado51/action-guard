# STATUS

Atualizado em 05/11/2026. Cada ferramenta le este arquivo no inicio de uma sessao e o atualiza ao entregar algo.

Repositorio: https://github.com/Ralado51/action-guard (publico, criado pelo Airton).

## Decisoes

- Produto: **Action Guard**, focado em Salesforce e Agentforce. O risco tecnico da integracao foi aceito; nao trocar automaticamente para Migration Guard diante de dificuldades.
- MVP: encerrar um Case. Regras: motivo de encerramento preenchido, proprietario mantido, Task de acompanhamento criada e vinculada ao Case (WhatId).
- A acao deve ser executada pelo Agentforce. Chamar o Flow direto ajuda a desenvolver o nucleo, mas nao comprova integracao com Agentforce e e identificado como `flow_direct`.
- Fluxo em duas etapas: `create_plan(rule)` e `execute_plan(approved_plan_id)`. Editar o plano invalida a aprovacao.
- Trilha do hackathon: **nao confirmada.** O plano original marcou Blast Radius Zero; a revisao recomendou Powering the Future of Work. Elegibilidade nao validada com os organizadores.
- Licenca MIT, somente dados sinteticos, nenhum segredo no repositorio.

## Verificado (com evidencia)

Revisao de 04/11: o oraculo foi corrigido e os contratos reforcados (ver `docs/DECISIONS.md`, itens 8 a 13).

- **Suite: 114 testes passando**, executados em duas versoes de Python: 3.13 e **3.12.3** (venv novo com `requirements-dev.txt`, Python do sistema). Cobrem schemas, consistencia dos 7 cenarios, oraculo, casos de borda, requisitos condicionais por `kind`, aprovacao do plano, API e varredura de segredos.
- Defeitos reproduzidos antes da correcao: `OwnerId` ausente nos dois snapshots resultava em `passed`; Case que sumia do snapshot final passava em `no_unexpected_change` e quebrava as verificacoes de campo com `KeyError`.
- Os testes novos foram validados reintroduzindo os defeitos no oraculo: com `None == None` voltando, 6 testes falham; ignorando registros que sumiram, 5 falham. Oraculo restaurado em seguida.
- API: `GET /health` responde 200; demais rotas validam o corpo (422) e respondem 501.

## Integracao Salesforce (branch `feat/salesforce-integration-claude`, ainda nao integrada)

- Implementados `connector/` e `orchestrator/` (ver `docs/SALESFORCE_INTEGRATION.md`) e ajustado o contrato (`record_created` com `expected_count`/`match`, `docs/DECISIONS.md` 14 a 17).
- **159 testes passando** em Python 3.12.3 e 3.13, com Salesforce **simulado**. Os testes novos falham quando se remove o portao de aprovacao ou se introduz retry da mensagem de acao (mutacoes verificadas).
- **Nada foi executado contra a org real.** Nao e prova de que o conector funciona com a API real.
- Avisos para Codex: `connector/` agora tem codigo; o motor (`engine/`) deve ser plugado como `evaluator` de `execute_run`.

## Nao verificado

- Codigo do conector/orquestrador ainda nao executado contra a org real; testes de integracao usam Salesforce simulado. Docker foi validado pelo operador na VM (ver registro abaixo).
- Planner, executor isolado e interface publicada continuam pendentes. A integracao Salesforce por scripts separados foi validada pelo operador; isso nao substitui o teste real do conector deste PR.

## Infraestrutura confirmada pelo Airton (nao reverificada aqui)

VM `action-guard-dev` na Vultr (Ubuntu 22.04.5, Docker 29.1.3, UFW ativo), Serverless Inference ativo com chamada VM para a inferencia funcionando. Pendente: confirmar que o Firewall Group esta associado a VM e o tamanho final do disco; remover a regra duplicada de SSH no UFW.

## Contratos liberados

Os contratos `1.0` estao liberados para trabalho em paralelo. Mudanca de contrato: so em `contracts/`, com aprovacao do Airton e aviso aqui.

### Codex

1. `connector/`: autenticacao Salesforce, criar dados sinteticos proprios por execucao, disparar a acao (`flow_direct` primeiro; ponto de extensao para `agentforce_agent_api`), coletar `snapshot.json` antes e depois respeitando `monitored` e `async_window`, preenchendo `primary_record`, todos os campos monitorados, `collection_errors` quando algo falhar e `confirmed_absent` (com `basis`) para exclusoes confirmadas. Modo simulado lendo `contracts/examples/`.
2. `engine/`: implementar os cinco `kind` de forma deterministica; a saida deve coincidir com `tests/oracle.py` nos sete cenarios de `contracts/examples/`, chamar `validate_plan_semantics` e `validate_snapshot_pair` e registrar os problemas em `limitations`.
3. `sandbox/`: executor Docker sem rede, usuario nao root, somente leitura, limites, cleanup e testes de contencao. Entrada: `checks`, `before`, `after`. Saida: `check_result[]`.

### Gemini

`web/`: interface contra `docs/API.md`, usando `contracts/examples/` como dados de teste. Etapas: regra, plano revisavel e aprovavel, execucao, relatorio com antes/depois, mudancas inesperadas e eventos de contencao.

### Claude Code

`planner/`: regra em portugues para `test_plan` via Vultr Serverless Inference, com validacao por schema, tentativas limitadas e erro recuperavel; o plano deve usar metadados reais da org e exigir aprovacao.

## Pendencias reais

- Executar o conector/orquestrador contra Case sintetico novo com plano aprovado; confirmar Subject e motivo completos por dados estruturados.
- Org, External Client App, OAuth, Agentforce API e Flow ja foram validados pelo operador com scripts separados. Campo real: `Closure_Reason__c`.
- Executor isolado e aplicacao publica.
- Confirmar a trilha do hackathon.

Nao confundir infraestrutura pronta com produto funcionando.


## Revisao dos portoes Salesforce — 2026-11-05

- Case ID obrigatorio no plano aprovado; ausencia ou divergencia bloqueia antes da sessao.
- Snapshot anterior com campos monitorados ausentes ou Case principal ausente bloqueia a execucao.
- REST exige `done` booleano; resposta malformada gera falha de coleta.
- 171 testes locais passaram em Python 3.12; nenhuma chamada a org real. Docker e avaliador de producao continuam pendentes.

## Motor deterministico — 2026-11-05

- `engine.evaluate` implementado e ligado como padrao de `execute_run`; integracao simulada agora usa o motor real.
- 197 testes locais passaram em Python 3.12.14, com comparacao ao oraculo independente e validacao de schema dos resultados.
- Nao houve chamada ao Salesforce. Docker nao instalado neste ambiente; validacao Docker segue pendente na VM.
- Isto nao implementa o executor isolado de sandbox nem o planner Vultr.

## Validacao Docker na VM — 2026-11-05

- Operador executou `sudo make docker-test` na branch `fix/salesforce-execution-gates` e informou `197 passed, 1 warning in 0.74s`.
- Evidencia fornecida pelo operador; nao reexecutada pelo assistente. Salesforce simulado; nenhuma acao real realizada pelo teste Docker.
- Repeticao sem sudo falhou por permissao no socket; nao invalida a execucao anterior aprovada.
- Suite local: 197 testes em Python 3.12.14; motor real ligado ao orquestrador. Registros anteriores de 114/159/171 testes representam etapas historicas.
