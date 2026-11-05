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
14. (Integracao Salesforce, 04/11) `record_created` ganhou `expected_count` e `match`: o dossie exige exatamente uma Task nova com o Subject esperado, e o contrato antigo aceitava uma ou mais. Duplicata comprovada vence candidato nao observado. Exemplos regenerados (`agentforce_agent_api`, Status inicial `New`, `chk_reason_matches`, cenario `duplicate_tasks`).
15. A aprovacao vincula o hash do plano, que inclui acao, motivo (`action.input.closure_reason`) e, se informado, `action.input.case_id`. Sem `case_id` no plano, o Case sintetico e criado em tempo de execucao e a precondicao (Case aberto, motivo vazio) impede reutilizar Case ja encerrado.
16. A mensagem que executa a acao e enviada uma unica vez. Timeout ou 5xx apos o envio = resultado `uncertain`: nao ha retry; o resultado vem dos snapshots e a limitacao exige revisao humana antes de nova tentativa. Nao se promete exactly-once.
17. A resposta do agente e guardada como registro, nunca entra no calculo do status. Falha ao encerrar a sessao vira limitacao e nao altera o resultado.
18. (Revisao critica, 05/11) Ids Salesforce: a identidade e o prefixo de 15 caracteres; a API devolve 18. Comparacoes usam `connector.ids.same_record`, reservas usam `key15`, e o Case do plano e normalizado para 18 caracteres. Ids de 16/17 caracteres sao invalidos.
19. Mudanca **aditiva** de contrato (`schema_version` continua `1.0`): `rule_coverage` opcional no plano (dentro do hash), `approval.coverage_acknowledged` opcional (fora do hash), `coverage_status` e `rule_coverage` opcionais no relatorio. Planos e relatorios antigos continuam validos e aparecem como `not_assessed`.
20. A cobertura da regra e uma declaracao do modelo **conferida pelo servidor**: o servidor segmenta a regra, rebaixa `covered` sem `check_id` valido ou sem vocabulario compativel, forca `not_verifiable` para temas fora do escopo e detecta conflitos com os invariantes. O modelo nunca promove um veredito do servidor. `status` do relatorio continua refletindo apenas as verificacoes; a cobertura aparece em `coverage_status` e nas limitacoes.
21. A aprovacao exige confirmacao humana de cada clausula (API: `acknowledged_clauses`; CLI: segunda confirmacao "ACEITAR COBERTURA PARCIAL"). A cobertura nao e editavel na API; editar o plano muda o hash.
22. Estado de execucao `blocked`: falha antes de qualquer envio ao agente libera a reserva do Case. Erro apos possivel envio continua `error` e consome o Case. Um 4xx apos o envio nao prova que nada foi executado.
23. O sandbox e opcional/offline (reavaliacao de evidencias); nao e requisito do fluxo e nao sustenta a alegacao de Blast Radius Zero.
24. (Auditoria) Segundo modo de uso do mesmo motor: auditoria somente leitura do estado final, com o plano aprovado como modelo da regra (`docs/AUDIT.md`). Nao executa acao nem reserva Case. Contrato aditivo novo: `audit_report.schema.json`.
25. Na auditoria, verificacoes que exigem o estado anterior (campo inalterado, nenhuma mudanca inesperada) ou um valor por registro (motivo exato do plano de teste) sao `not_auditable` e aparecem como NAO verificadas; inconclusivo nunca conta como correto; falha comprovada vence inconclusivo.
26. O LLM nao decide veredito na auditoria. O resumo opcional recebe so contagens e descricoes, e e validado (numeros inexistentes ou aparencia de Id derrubam o texto; vale o do servidor). Limite conhecido: um numero real usado no contexto errado passa; por isso o texto do servidor acompanha o do modelo.

## Pendencias

- API name do motivo: `Closure_Reason__c` (confirmado no dossie de 04/11; picklist, nao usar `Case.Reason`).
- Como a Task de acompanhamento e criada (sincrona no Flow ou assincrona) define o valor de `async_window`.
- Trilha do hackathon (Blast Radius Zero ou Powering the Future of Work) ainda nao confirmada pelo Airton nem validada com os organizadores.
- Formato exato das chamadas da Agent API e dos escopos do External Client App: nao verificado.
