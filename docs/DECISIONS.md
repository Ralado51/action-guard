# Decisoes e pendencias de contrato

## Decisoes

1. Adicionado `field_not_empty` aos tipos iniciais. "Motivo de encerramento preenchido" nao pode ser expresso por `field_equals`, porque o valor varia.
2. `no_unexpected_change` cobre so campos monitorados (ver `docs/CONTRACTS.md`). O produto nao promete diff completo da org.
3. A aprovacao vale para um `plan_hash` (SHA-256 do JSON canonico sem `plan_hash` e `approval`). Editar muda o hash e invalida a aprovacao.
4. `action.executed_via` e obrigatorio e vai ate o relatorio: `flow_direct` ou `agentforce_agent_api`.
5. Janela de espera assincrona declarada no plano (`async_window`); ausencia antes do prazo nao e falha definitiva.
6. A imagem da aplicacao usa Python 3.12 (`Dockerfile`). Nao presumir Python 3.12 no host Ubuntu 22.04.
7. As rotas de plano e execucao existem como stubs 501 para Codex e Gemini trabalharem contra um contrato estavel.

8. (Revisao de 04/11) O oraculo tinha tres defeitos, corrigidos: campo ausente nos dois snapshots virava `passed` (`None == None`); Case que sumia do snapshot final passava despercebido em `no_unexpected_change`; e as verificacoes de campo quebravam com `KeyError` nesse mesmo caso. O motor nao deve herdar nenhum deles.
9. Chave ausente e diferente de valor nulo; registro ausente so e exclusao se estiver em `confirmed_absent`. Ver `docs/CONTRACTS.md`.
10. Falha comprovada vence evidencia insuficiente em `no_unexpected_change`.
11. O schema do plano exige, por `kind`, os campos especificos e proibe os alheios; `record_created` define o vinculo por `link_field` == `primary_record.id`.
12. `primary_record` obrigatorio nos snapshots e `confirmed_absent` (so em `after`) foram acrescentados. Os contratos ainda nao tinham sido distribuidos, entao `schema_version` continua `1.0`.
13. `validate_snapshot_pair` e `validate_plan_semantics` fazem parte do contrato; o motor as chama e registra os problemas em `limitations`.

## Pendencias

- **API name do motivo de encerramento na org.** Os exemplos usam `Closure_Reason__c` como nome ilustrativo. Nao assumir `Case.Reason`. Confirmar na org e atualizar `contracts/tools/build_examples.py`, regenerar os exemplos e o Flow.
- Como a Task de acompanhamento e criada (sincrona no Flow ou assincrona) define o valor de `async_window`.
- Trilha do hackathon (Blast Radius Zero ou Powering the Future of Work) ainda nao confirmada pelo Airton nem validada com os organizadores.
- Formato exato das chamadas da Agent API e dos escopos do External Client App: nao verificado.
