# STATUS

Atualizado em 08/11/2026, dia do prazo (envio ate 20:00, horario de Brasilia). Cada ferramenta le este arquivo no inicio de uma sessao e o atualiza ao entregar algo.

Repositorio: https://github.com/Ralado51/action-guard (publico). Dados sinteticos apenas; nenhum segredo, codigo de acesso, chave de operador, dominio de org, Agent ID ou IP no repositorio. Segredos ficam no arquivo de ambiente privado da VM.

## Estado atual

- **Produto:** Action Guard verifica se a acao de um agente (Agentforce ou agente hospedado na Vultr) produziu o resultado esperado no Salesforce, com auditoria somente leitura do estado final, plano aprovado por hash e achados com dono. Processo unico: encerrar Case. Nao ampliar.
- **Na main (tudo mergeado, PRs ate #44):** planner Vultr com cobertura por clausula; motor deterministico; execucao unica sem retry; auditoria somente leitura; achados com historico (aberto, atribuido, correcao, revalidacao, fechado ou risco aceito) e dossie com manifesto SHA-256; demo ao vivo com sessoes isoladas e Case sintetico por sessao; replay das acoes do agente; Dashboard; cadastro de operadores com chave pessoal (so o hash e guardado); pagina de Setup em leitura quando deslogado; logo e favicon.
- **Demo publica:** https://guard.jjnetwork.com.br em modo demonstracao (execucao real bloqueada; a demo ao vivo e habilitada a parte, com codigo de acesso, limites por hora e por dia, Cases `[SYNTHETIC]`).
- **Trilha do hackathon:** a confirmar com o regulamento. Comercializacao e hipotese, sem entrevistas feitas.
- **PR #5 (sandbox offline):** aberto, fora da entrega. Nao sustenta "Blast Radius Zero".

## Verificado (com evidencia)

- **473 testes passando** (Python 3.12), com Salesforce e Vultr simulados. Os dois bugs de contagem da demo ao vivo achados na revisao (teste inconclusivo contado como falha detectada; revalidacao falhada contada como corrigida) estao corrigidos e cobertos por testes.
- **20 Cases sinteticos auditados na org real:** 10 por agente Vultr e 10 por Agentforce, todos atendem as verificacoes auditaveis. Amostras pequenas, instrucoes diferentes: nao e comparacao nem taxa de falha.
- **Calibracao:** 4 de 4 falhas injetadas detectadas, 0 de 3 alarmes falsos. Falhas injetadas por nos; mostra o comportamento do verificador, nao a frequencia de falha de agentes reais.
- **Ciclo de achado gravado:** um fechado com evidencia (F-034e472f) e um com risco aceito (F-4ad0fe1f).
- Fluxo completo pelo CLI na org real com Case sintetico, seis verificacoes `passed` (informado pelo operador, nao reexecutado).

## Nao verificado / limites conhecidos

- Apenas 3 das 6 condicoes do plano sao auditaveis no estado final. As outras 3 sao lacunas declaradas: "motivo igual ao esperado" precisa do motivo esperado por Case; "dono inalterado" e "nenhuma mudanca inesperada" precisam do estado anterior. Aprovado significa que as verificacoes listadas passaram, nao que a regra inteira foi cumprida nem que o problema do cliente foi resolvido.
- Nenhuma falha espontanea de agente real foi observada.
- Nao ha sandbox para codigo gerado por modelo; o projeto nao afirma isso.
- So o Case e as Tasks vinculadas sao observados; efeitos tardios depois do primeiro estado aprovado nao sao capturados.
- Cobertura por vocabulario finito; a confirmacao humana por clausula e a ultima barreira.
- Operadores sao responsabilizacao por nome, nao autenticacao multiusuario nem controle de papeis.
- O Flow nao e idempotente; `uncertain` exige revisao humana. CI no GitHub (`.github/workflows/tests.yml`, Python 3.12 e 3.13) roda a suite a cada push e PR; o primeiro resultado so existe depois do merge deste PR.

## Pendencias (envio ate 20:00)

- Airton: cadastrar o operador "Judge", pôr chave e codigo de acesso nas notas da submissao (nunca no repositorio); testar a demo ao vivo; conferir o deploy na VM (`git log -1` igual ao da main).
- Submissao: video (ate 5 min), slides em PDF, capa 16:9, texto e tecnologias do formulario (tirar AgentOps e Aiml; incluir Vultr, Salesforce, Agentforce, Python, FastAPI, Docker).
- Depois do julgamento: trocar token e codigo, revogar operadores de teste, baixar limites ou desligar a demo ao vivo, limpar Cases `[SYNTHETIC]`.
