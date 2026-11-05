# STATUS

Atualizado em 05/11/2026 (branch `fix/review-hardening-coverage`). Cada ferramenta le este arquivo no inicio de uma sessao e o atualiza ao entregar algo.

Repositorio: https://github.com/Ralado51/action-guard (publico). Dados sinteticos apenas; nenhum segredo, dominio de org, Agent ID ou IP no repositorio.

## Estado atual

- **Produto:** Action Guard verifica se uma acao executada por um agente Agentforce produziu o resultado de negocio esperado, com evidencia antes/depois, verificacoes deterministicas e plano aprovado por hash. Processo do MVP: somente `close_case`. Nao ampliar para outros processos agora.
- **Nucleo (manter):** `engine/` (verificacoes deterministicas), `connector/` + `orchestrator/` (execucao unica, sem retry), evidencias e aprovacao por hash.
- **Planner Vultr:** traduz a regra em plano; o servidor impoe invariantes. Agora tambem declara **cobertura da regra por clausula** (ver `docs/PLANNER.md`): o relatorio diz quais partes da regra NAO sao verificadas. Verde significa "as verificacoes listadas passaram", nao "a regra inteira foi cumprida".
- **Interface/API (`web/`):** gerar, vincular Case, revisar, confirmar cobertura por clausula, aprovar hash, executar, ver relatorio. Estados de execucao: queued/running/completed/error/**blocked** (nada enviado ao agente).
- **Sandbox (PR #5, fora desta base):** material de demonstracao/reavaliacao offline opcional. Isola um avaliador fixo sobre dados produzidos pelo backend; nao isola codigo gerado por LLM e nao sustenta "Blast Radius Zero". Integracao automatica adiada.
- **Trilha do hackathon:** nao confirmada; conferir o regulamento. Comercializacao e hipotese.

## Verificado (com evidencia)

- **344 testes passando** em Python 3.12.3 e 3.13, com Salesforce e Vultr **simulados**. Mutacoes verificadas nas travas novas (normalizacao de Id, reserva por 15 caracteres, Task extra, travas de cobertura).
- Operador, com org real e CLI (registros anteriores a esta branch): plano Vultr com Describe, vinculo de Case, aprovacao por hash, execucao Agentforce, seis verificacoes `passed`; `make docker-test` na VM (197 testes na epoca); fumaca real do planner (deepseek-v4.1-flash-1017, 1 chamada, ~1,4-1,7 mil tokens). Evidencia informada pelo operador, nao reexecutada por mim.
- Conjunto rotulado de cobertura (`tests/data/rule_coverage_labeled.json`, 20 regras, 33 clausulas): modelo-oraculo simulado acerta 33/33; modelo "otimista" simulado (declara tudo coberto) so produz 2 falsas coberturas, ambas lacunas conhecidas e marcadas `known_gap`.

## Nao verificado / limites conhecidos

- **Nenhuma chamada real a Vultr para cobertura.** A qualidade do modelo real nessa tarefa so existe depois de rodar `python -m planner.coverage_eval tests/data/rule_coverage_labeled.json --fixture-metadata` (ou `--metadata`) na VM. Os testes usam modelo simulado.
- `make docker-test` desta versao nao foi executado. API/UI atuais nao foram testadas contra a org real nem em navegador real.
- A cobertura por vocabulario e finita: clausulas com redacao fora do vocabulario conhecido sao rebaixadas (seguro), mas uma clausula sobre algo nao monitorado, redigida com palavras de um check existente, pode ser marcada coberta (lacunas `known_gap`). A confirmacao humana por clausula e a ultima barreira.
- Escopo monitorado: nada fora do Case e das Tasks vinculadas e observado. Task extra vinculada ao Case que nao case com o esperado gera aviso; Tasks nao vinculadas ao Case nao sao vistas.
- O polling para no primeiro snapshot em que tudo passa; efeitos tardios depois disso nao sao capturados.
- O Flow nao e idempotente; `uncertain` exige revisao humana. Reserva so protege o mesmo banco/volume. BackgroundTasks nao e fila duravel.
- `containment_events` do relatorio ficam vazios sem sandbox.

## Pendencias reais

- Rodar a avaliacao de cobertura com o modelo real e registrar resultados (falsa cobertura deve ser 0).
- Demo: mostrar primeiro a falha real do motivo vazio (exige versao defeituosa do Flow ou flag, e aprovacao explicita para execucao real), depois o fluxo corrigido.
- Decidir trilha; decidir estrategia de merge (sugestao: consolidar #2-#4 e esta branch, deixar #5 fora).
- Licenca/titularidade (LICENSE) e questao contratual do Airton.

## Historico resumido

- Revisao dos portoes Salesforce: Case ID obrigatorio, snapshot anterior completo, `done` booleano no REST.
- Motor deterministico ligado ao orquestrador; validacao Docker na VM (197 testes, informado pelo operador).
- Integracao real validada pelo operador (seis checks passed em Case sintetico; nao reexecutar esse Case).
- Planner Vultr, fumaca real, Describe real, CLI integrado `prepare/run`.
- API/UI assumidas pelo Codex (SQLite, reserva por org/Case).
- Revisao critica: normalizacao de Ids 15/18, header nao ASCII, erros genericos, aviso de Task extra, estado `blocked`, cobertura da regra (esta branch).
