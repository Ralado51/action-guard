# Auditoria de resultados (somente leitura)

**Pergunta:** de todas as vezes que o agente disse ter feito a acao, em quantas os dados confirmam o resultado esperado pela regra de negocio?

O fluxo "plano -> aprovacao -> execucao -> verificacao" continua sendo o **teste de aceite** (antes do go-live). A auditoria e o uso em producao: reaproveita o plano aprovado e o motor de verificacoes, mas **nao executa nada e nao escreve no Salesforce**.

## Como funciona

1. Um plano aprovado (hash vigente) define as verificacoes. O `case_id` do plano de teste e ignorado: o plano e usado como modelo da regra.
2. Selecao dos registros:
   - `--case-ids arquivo`: os Cases que o agente **informou** ter encerrado. Pega o caso "disse que fechou e nao fechou".
   - `--since 2026-11-01T00:00:00Z [--modified-by <IdDoUsuarioDoAgente>] [--limit N]`: Cases ja encerrados na janela. **Nao ve** um Case que o agente alegou encerrar e continua aberto.
3. Leitura via REST (GET): Cases e Tasks vinculadas, em lotes. Falha de consulta nunca vira "zero registros": o registro fica inconclusivo.
4. Avaliacao deterministica do **estado final** (`audit/evaluate.py`). Sem LLM, sem texto do agente.
5. Agregacao: taxa de resultados corretos, falhas por verificacao, lista de registros com falha e a evidencia do valor observado.
6. Resumo: texto deterministico do servidor; opcionalmente (`--explain`) um resumo do modelo da Vultr.

```bash
python -m audit run --plan approved_plan.json --case-ids cases_do_agente.txt [--explain]
python -m audit run --plan approved_plan.json --since 2026-11-01T00:00:00Z --limit 200
```
Credenciais `SF_*` (e `VULTR_INFERENCE_*` com `--explain`) vem do ambiente. O relatorio e salvo em `runs/audit-<id>/audit_report.json` (contrato `contracts/audit_report.schema.json`). Contem IDs de registros: nao publique relatorios de uma org real.

## O que e e o que nao e verificado

| Verificacao do plano | Na auditoria |
|---|---|
| campo igual a valor fixo (ex.: Status = Closed) | auditavel |
| campo preenchido (ex.: motivo) | auditavel |
| Task vinculada correspondente, contagem exata | auditavel (conta tambem Task anterior a acao) |
| campo inalterado, nenhuma mudanca inesperada | **nao auditavel** (exige o estado anterior) |
| motivo igual ao do plano de teste | **nao auditavel** (cada registro tem o seu motivo) |

Verificacoes nao auditaveis aparecem no relatorio como NAO verificadas; nunca contam como aprovadas. Registros inconclusivos **nao** contam como corretos. Falha comprovada vence inconclusivo.

## Privacidade e o papel do LLM

O modelo da Vultr nao decide veredito. No resumo opcional ele recebe somente contagens, descricoes de verificacoes e textos de clausulas nao cobertas: nunca IDs nem valores de registros. A saida e validada (sem numeros que nao existam nos dados, sem aparencia de Id, ate 700 caracteres); se falhar, vale o resumo do servidor, que acompanha o do modelo (`summary.server_text`).

Limite conhecido do guarda: ele barra numeros inexistentes, mas um numero real usado no contexto errado passa. Por isso o texto do servidor sempre fica ao lado.

## Limites

- Sem o antes, nao ha proprietario preservado nem mudancas inesperadas.
- Uma amostra por janela sofre de vies de sobrevivencia (so Cases ja encerrados).
- A taxa so mede as regras escritas e aprovadas; cobertura parcial aparece em `coverage_status`.
- Nao ha agendamento nem alertas nesta versao.
- Validado apenas com Salesforce e Vultr simulados; nenhuma auditoria foi feita na org real.
