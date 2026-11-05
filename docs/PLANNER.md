# Planner (Vultr Serverless Inference)

Regra em portugues -> `test_plan` em **rascunho**. Nao recebe credenciais Salesforce, nao cria Case, nao executa agente e nao aprova plano. Interface interna (nao e contrato publico): `planner.create_plan`, `planner.bind_case`, `planner.ready_for_approval`.

## Entradas

- `rule`: `contracts/rule.schema.json`, texto ate 4000 caracteres.
- `metadata_context` (fornecido pelo backend; o planner nao consulta a org):
  ```json
  {"source": "salesforce_describe | fixture", "collected_at": "<instante>",
   "objects": {"Case": {"readable": true, "fields": {"Status": {"type": "picklist", "readable": true, "values": ["..."]}}}}}
  ```
  Objeto ou campo ausente, ilegivel ou sem `readable: true` conta como inexistente. Com `source: "fixture"` o resultado traz `metadata_source: "fixture"` e um aviso; nunca e apresentado como metadado real.
- `action_context`: `{"process": "close_case", "closure_reason", "task_subject", "agent_name"?, "case_id"?}`. `closure_reason` deve ser um dos quatro valores conhecidos **e** existir na picklist do contexto; `case_id`, se vier, vem do backend/operador.

Contexto insuficiente, motivo ausente/desconhecido, motivo da regra diferente do solicitado ou Case invalido geram `insufficient_context` **antes de qualquer chamada ao modelo**. Nao ha escolha silenciosa.

## Quem decide o que

O modelo propoe somente `monitored`, `async_window` e `checks` (com descricoes). O servidor atribui `plan_id`, `rule_id`, versao, acao (`agentforce_agent_api`), motivo, Subject da Task, precondicoes, `check_id`, `approval = null` e o hash. Chaves extras da resposta (incluindo `approval`, `plan_hash`, `action`) sao descartadas com aviso.

Invariantes do MVP (a proposta que omitir, duplicar, contradizer ou ampliar e **rejeitada**, nao corrigida em silencio): Status `Closed`; motivo nao vazio; motivo igual ao solicitado; `OwnerId` inalterado; `record_created` em Task por `WhatId` com `expected_count` 1 e `match.Subject` igual ao solicitado; `no_unexpected_change` com `allowed_changes` exatamente `Case.Status`, `Case.Closure_Reason__c`, `Case.ClosedDate`, `Case.IsClosed`. Ate 4 verificacoes extras, so sobre outros campos do Case.

Limites: 10 checks; 25 campos por objeto; objetos somente Case e Task; `max_wait_seconds` <= 120 e no maximo 60 consultas; campos conferidos contra o contexto; valores de picklist conferidos. Depois: JSON Schema de `test_plan` e `validate_plan_semantics`.

## Chamadas ao modelo

`POST {VULTR_INFERENCE_BASE_URL}/chat/completions`, Bearer, `VULTR_INFERENCE_MODEL`, `temperature` 0, `max_tokens` 2000, timeout 60 s. Sem `response_format`: a validacao e local. Usa `choices[0].message.content`; rejeita `finish_reason` diferente de `stop` (inclui `length`), `tool_calls`, conteudo vazio e corpo fora do formato; `reasoning` nao e usado.

Orcamento total de **2 requisicoes HTTP por operacao**, somando geracao, correcao e retry. 401/403: falha sem retry. Timeout: falha sem retry. 429/5xx: um retry (1 s) se houver orcamento. Se a primeira resposta for rejeitada pelo validador, a segunda chamada reenvia os problemas (correcao); se falhar de novo, erro. Nao ha fallback para fixture ou plano pronto.

Erros (`PlannerError.to_public()`): `config`, `auth`, `timeout`, `rate_limit`, `upstream`, `invalid_response`, `schema`, `semantics`, `insufficient_context`, com mensagem segura e `details` produzidos por este codigo. Corpo bruto, cabecalhos e chave nunca saem.

## Vinculo do Case (decisao)

O executor exige `action.input.case_id` dentro do hash aprovado. Fluxo escolhido:

1. `create_plan` -> rascunho sem `case_id` (ou com ele, se o backend ja o tem) e `approval = null`.
2. O **backend confiavel** obtem o Case: provisiona um Case sintetico novo (`orchestrator.run.create_synthetic_case`) ou usa um Case de teste fornecido explicitamente pelo operador, como no teste real validado. O LLM nunca participa.
3. `bind_case(plan, case_id)` grava o ID, incrementa `plan_version`, recalcula o hash e zera a aprovacao.
4. Revisao humana do plano ja vinculado; aprovacao do hash vigente; `execute_run`.

Qualquer alteracao posterior (inclusive trocar o Case ou editar o motivo) muda o hash e invalida a aprovacao. `ready_for_approval(plan)` lista pendencias (por exemplo, falta de `case_id`); mesmo que alguem aprove um rascunho sem Case, `execute_run` bloqueia antes de falar com o agente (teste incluso).

**Pendente de alinhamento com o Gemini (nao alterado aqui):** `docs/API.md` ainda diz que cada execucao cria seu Case e `POST /api/plans` nao recebe `metadata_context`, `action_context` nem Case. Sugestao: `POST /api/plans/{id}/case` (vincula/provisiona e devolve novo plano em rascunho) entre a criacao e a aprovacao, e a interface mostrar o Case no passo de revisao. `web/` nao foi modificado e as rotas continuam 501.

## Teste de fumaca na VM (somente gera plano)

Chave no ambiente (`VULTR_INFERENCE_API_KEY`, `VULTR_INFERENCE_MODEL`; nunca no chat):

```bash
python -m planner --rule contracts/examples/rule.json --fixture-metadata \
  --reason "Resolved - Customer confirmed" --subject "Action Guard - Case closure follow-up"
```
Imprime plano, `plan_hash`, modelo, uso de tokens e origem dos metadados. Com `--fixture-metadata` a origem e `fixture`; para metadados reais, passe `--metadata arquivo.json` gerado pelo backend. Nao ha chamada ao Salesforce nem ao agente.
