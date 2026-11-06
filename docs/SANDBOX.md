# Avaliador offline isolado

O sandbox avalia evidencia ja coletada. Nao executa a acao do Agentforce, nao recebe credenciais e nao impede alteracoes externas no Salesforce. Esta etapa e separada do backend e nao monta Docker socket dentro da aplicacao. Nao chamar de rollback, simulacao de org ou contencao da escrita Salesforce.

## Imagem e restricoes

`sandbox/Dockerfile` copia apenas contracts/, engine/, worker.py e probe.py. Usuario 65532:65532; entrada JSON fixa (plan, before, after); nenhuma execucao de codigo gerado pelo modelo. Valida schemas de entrada e CheckResult localmente.

Runner no host usa Docker sem rede, rootfs somente leitura, todas capabilities removidas, no-new-privileges, memoria/swap 128 MiB, CPU 0.5, 32 PIDs, limite de arquivos e tmpfs /tmp 8 MiB com noexec/nosuid. Nao monta diretorios, socket ou credenciais; zera variaveis proxy que configuracoes locais do Docker podem injetar. Evidencia chega por stdin, resultado sai por stdout. Entrada limitada a 2 MiB. Deadline de 15s e cleanup forcado por nome unico em finally; falha de limpeza invalida o resultado. Sem fallback para avaliacao no host.

O parser rejeita saida invalida e erro do worker. Timeout/cleanup produzem eventos somente quando observados pelo runner; flags configuradas nao sao prova de bloqueio real. Exit 137 nao e tratado como prova automatica de OOM. Probe verifica conectividade negada, escrita negada em /app, UID sem root, ausencia de variaveis de integracao e ausencia de Docker socket. Isso nao prova isolamento absoluto contra vulnerabilidades do kernel/Docker.

## Validar na VM Vultr

Executar a partir da raiz do projeto; nao e necessario usar credenciais. Python do host roda apenas o runner (biblioteca padrao); avaliacao e validacao de schema usam Python da imagem.

```bash
sudo docker build -f sandbox/Dockerfile -t action-guard-evaluator .
sudo python3 -m sandbox --probe
sudo python3 -m sandbox \
  --plan contracts/examples/test_plan.json \
  --before contracts/examples/success/before.json \
  --after contracts/examples/success/after.json
```

Esperado: probe com cinco valores true, cleanup confirmado; avaliacao com seis resultados passed. Sao fixtures e probes locais, nenhuma chamada ao Salesforce ou a Vultr.

Depois testar falha comprovada:

```bash
sudo python3 -m sandbox \
  --plan contracts/examples/test_plan.json \
  --before contracts/examples/duplicate_tasks/before.json \
  --after contracts/examples/duplicate_tasks/after.json
```

Esperado: chk_followup_task failed. ok=true do runner significa execucao/saida validas, nao que todos os checks passaram. Nao apagar ou substituir evidencias reais; usar fixtures publicas neste teste inicial.

## Estado

295 testes locais passaram em Python 3.12.14; worker comparado ao motor nos oito cenarios, restricoes de comando verificadas e erros/cleanup simulados. Nao foi construido nem executado Docker pelo assistente, pois Docker esta ausente neste ambiente. Runtime na VM ainda pendente.

Esta entrega disponibiliza avaliacao isolada independente. O backend/interface continuam usando avaliador em processo e containment_events vazio ate uma integracao explicitamente validada. Nao montar Docker socket no container web para contornar essa separacao. Uma integracao futura deve usar worker/servico confiavel separado com protocolo restrito e preservar os eventos observados como evidencias, sem alegar que a acao Salesforce ocorreu dentro do sandbox.
