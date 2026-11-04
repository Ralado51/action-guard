# Contratos de dados (schema_version 1.0)

Cinco JSON Schemas em `contracts/`: `rule`, `test_plan`, `snapshot`, `check_result`, `report`. Todos usam `additionalProperties: false`; campo desconhecido e erro. Regras entre campos que o schema nao expressa ficam em `contracts/semantics.py`.

## Tipos de verificacao e campos exigidos

O schema exige, por `kind`, os campos abaixo e **proibe** os demais.

| `kind` | O que verifica | Exige | Proibe | `object` |
| --- | --- | --- | --- | --- |
| `field_equals` | Campo do registro principal igual ao esperado depois da acao | `field`, `expected` (pode ser `null`) | `link_field`, `allowed_changes` | objeto monitorado |
| `field_not_empty` | Campo preenchido depois da acao (`null` e `""` contam como vazio) | `field` | `expected`, `link_field`, `allowed_changes` | objeto monitorado |
| `field_unchanged` | Campo igual antes e depois | `field` | `expected`, `link_field`, `allowed_changes` | objeto monitorado |
| `record_created` | Existe registro novo (id ausente do snapshot anterior) cujo `link_field` aponta para o registro principal | `link_field` | `field`, `expected`, `allowed_changes` | objeto monitorado |
| `no_unexpected_change` | Nenhum campo monitorado mudou fora de `allowed_changes` | `allowed_changes` (pode ser `[]`) | `field`, `expected`, `link_field` | `"*"` |

Verificacoes de campo (`field_*`) sempre miram o **registro principal** (`snapshot.primary_record`, o Case sintetico da execucao). O vinculo de `record_created` e: `link_field` do registro novo == `primary_record.id`.

## Validacao semantica

`validate_plan_semantics(plan)`: `check_id` unico; no maximo um `no_unexpected_change`; todo objeto, campo e `link_field` usado por uma verificacao, precondicao ou `allowed_changes` precisa estar em `monitored`.

`validate_snapshot_pair(plan, before, after)`: valida o contrato do coletor (mesmo `run_id` e `primary_record`; fases corretas; todo campo monitorado coletado quando nao ha erro de coleta; todo registro do snapshot anterior aparece em `records` ou em `confirmed_absent`). O motor deve registrar os problemas em `report.limitations`.

## Falha comprovada versus evidencia insuficiente

- **Chave ausente nao e valor nulo.** `null` com a chave presente foi observado; chave ausente nao foi coletada. Dois campos ausentes nunca sao "iguais".
- **Registro que some do snapshot final** nao e exclusao. So `snapshot.confirmed_absent` (com `basis`, ex.: `queryAll` com `IsDeleted = true`) confirma exclusao. Sem isso, e evidencia insuficiente.
- `failed`: a condicao foi observada e nao atendida, ou a exclusao foi confirmada. Registro excluido de forma confirmada falha as verificacoes de campo e conta como mudanca inesperada (`field: "__record__"`, `before: "present"`, `after: "deleted"`).
- `inconclusive`: objeto ou campo nao coletado, registro sumiu sem confirmacao, coleta incompleta, `primary_record` divergente, registro novo sem o campo de vinculo. Nunca vira `passed`.
- `no_unexpected_change`: mudanca comprovada vence evidencia insuficiente (`failed`); sem mudanca comprovada, qualquer coisa nao observada (objeto, campo, registro, snapshot incompleto) resulta em `inconclusive`; so e `passed` quando tudo foi observado e nada mudou. Campos em `allowed_changes` nao precisam ter sido coletados.
- Status do relatorio: `failed` se alguma verificacao falhou; senao `inconclusive` se alguma ficou inconclusiva; senao `passed`.

## Snapshot

- `complete: false` exige `collection_errors` nao vazio; `complete: true` exige lista vazia ou ausente e todos os campos monitorados presentes.
- `confirmed_absent` so existe na fase `after`.
- `primary_record` e obrigatorio nos dois snapshots.

## O que `no_unexpected_change` cobre

Somente registros e campos monitorados pelo plano, comparando registros do snapshot anterior com o posterior. Registros novos sao tratados por `record_created`. Nao e um diff da org.

## Exemplos (`contracts/examples/`)

`rule.json`, `test_plan_draft.json`, `test_plan.json` (aprovado) e sete cenarios (`before.json`, `after.json`, `report.json`), todos sinteticos:

| Cenario | Status | O que demonstra |
| --- | --- | --- |
| `success` | passed | Tudo atendido |
| `owner_changed` | failed | Proprietario mudou; mudanca inesperada comprovada |
| `task_missing` | failed | Nenhuma Task nova vinculada |
| `inconclusive` | inconclusive | Falha de coleta em Task |
| `evidence_missing` | inconclusive | `OwnerId` ausente dos dois snapshots (coletor violou o contrato) |
| `case_deleted` | failed | Exclusao do Case confirmada por `confirmed_absent` |
| `case_unconfirmed` | inconclusive | Case nao retornou e a ausencia nao foi confirmada |

Regenere com `python contracts/tools/build_examples.py`; `tests/oracle.py` recalcula os resultados de forma independente. O motor deve coincidir com o oraculo nesses sete cenarios.
