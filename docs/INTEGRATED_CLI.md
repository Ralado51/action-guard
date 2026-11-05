# Plano gerado e execucao aprovada — CLI

Base: planner Vultr + conector/orquestrador/motor. Nao modifica web/ ou contratos publicos.

## Preparar

Com variaveis VULTR_INFERENCE_API_KEY, VULTR_INFERENCE_BASE_URL e VULTR_INFERENCE_MODEL no ambiente, Case sintetico novo criado explicitamente pelo operador e metadados reais coletados:

```bash
PYTHONPATH=. python3 -m orchestrator prepare \
  --rule contracts/examples/rule.json \
  --metadata /tmp/action-guard-metadata.json \
  --case-id <NOVO_CASE_ID> \
  --reason "Resolved - Customer confirmed" \
  --subject "Action Guard - Case closure follow-up" \
  --output runs/generated-draft.json
```

Somente chama Vultr, vincula o Case antes da aprovacao e salva rascunho sem sobrescrever arquivos. Origem fixture e rejeitada por este fluxo integrado. Registra origem/instante dos metadados, modelo e tokens; nao armazena chave. O escopo monitored deve ser revisado explicitamente.

## Revisar e executar

Configurar SF_LOGIN_URL (My Domain), SF_API_VERSION=68.0 e SF_AGENT_ID no ambiente. Consumer Key/Secret sao solicitados de forma oculta se SF_CLIENT_ID/SF_CLIENT_SECRET nao estiverem exportados.

```bash
PYTHONPATH=. python3 -m orchestrator run \
  --plan runs/generated-draft.json --approved-by airton
```

Exibe o plano e exige `APROVAR sha256:<hash completo>`; declinar nao faz chamada Salesforce. Verifica hash e valida plano antes de confirmar. Aprovacao fica apenas na copia gravada nas evidencias; o arquivo original continua rascunho. O caminho das evidencias e exibido antes da autenticacao.

Reserva local por My Domain/Case impede nova tentativa usando o mesmo diretorio runs, inclusive com outro hash/plano. Reserva permanece em caso de falha ou interrupcao: nao remover para tentar novamente sem reconciliar evidencias. Nao e uma garantia distribuida de exatamente uma execucao, nem protege outra maquina ou diretorio. Nenhum Case e criado automaticamente pelo CLI.

## Validacao

272 testes locais passaram em Python 3.12.14. Novos testes usam transporte simulado: geracao/vinculo/rascunho, rejeicao de fixture, nao sobrescrita, aprovacao do hash, cancelamento sem rede, plano adulterado, replay com novo hash, falha de autenticacao e avaliacao real do resultado simulado. Docker e ciclo completo deste CLI contra servicos reais ainda nao executados. Planner real com Describe e executor real foram validados separadamente pelo operador.
