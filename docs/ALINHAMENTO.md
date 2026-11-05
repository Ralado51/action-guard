# Alinhamento do time (ChatGPT, Codex, Claude Code, Gemini, Airton)

Atualizado em 05/11/2026. Fonte unica para quem entra agora: leia este arquivo, depois `STATUS.md` e `docs/DECISIONS.md`. Se algo aqui contradiz o codigo ou o `STATUS.md`, vale o codigo e avise o Airton.

## Norte (frase do projeto)
Action Guard transforma a intencao de uma acao de IA em um plano verificavel e confere seus efeitos nos dados do negocio, **no escopo monitorado**. A pessoa aprova antes e recebe evidencias depois.

Pergunta central: "O agente disse que fez. Os dados comprovam que fez corretamente, sem efeitos indesejados no escopo observado?"

Regra de escopo: cada funcionalidade nova precisa ajudar esse fluxo ou espera. Processo unico: `close_case`. Trilha do hackathon: **Powering the Future of Work** (decisao pendente de confirmacao do Airton; o regulamento diz "choose one path").

## O que existe, por camada (e quao verificado)

| Camada | O que faz | Dono (OWNERS.md) | Verificacao |
|---|---|---|---|
| `contracts/` | schemas, hash do plano, semantica | Claude Code | testes; mudancas aditivas registradas em `docs/DECISIONS.md` |
| `engine/` | verificacoes deterministicas antes/depois | Codex | testes + oraculo independente |
| `connector/` + `orchestrator/` | Salesforce/Agentforce, execucao unica sem retry, CLI `prepare/run` | Codex / Claude Code | **real** (operador, CLI, seis checks passed) + testes simulados |
| `planner/` | regra em portugues -> plano via Vultr; cobertura por clausula | Claude Code | real so a geracao do plano (informado pelo operador); cobertura so simulada |
| `audit/` | auditoria somente leitura do estado final, taxa por regra | Claude Code | **so simulado** |
| `web/` | API + interface (gerar, vincular, aprovar, executar, auditar) | Codex | **so simulado**; nunca testada na org real |
| `sandbox/` (PR #5, fora da base) | avaliador offline isolado em Docker | Codex | complementar; nao sustenta "Blast Radius Zero" |
| Implantacao | VM Vultr + HTTPS no dominio do Airton | Airton | `/health` responde por HTTPS (conferido de fora) |

Suite: 377 testes (Python 3.12.3 e 3.13), todos com Salesforce e Vultr simulados. Quantidade de testes e evidencia de qualidade, nao proposta de valor.

## Pilha de PRs (nenhum mergeado alem do #1/#2 abertos; sem merge ate o Airton decidir)
#1 gates -> main; #2 planner; #3 CLI aprovado; #4 web; #5 sandbox offline; #6 correcoes + cobertura; #7 auditoria (base do #6). Sugestao: consolidar #2-#4, #6 e #7 e deixar #5 de fora.

## Regras que todos seguem
- Dados sinteticos. Nenhum segredo, dominio do org, Agent ID, ID de usuario ou IP da VM no repositorio, em commit ou em PR.
- Nenhuma acao real no Salesforce sem aprovacao explicita do Airton. Auditoria e somente leitura.
- LLM nao decide veredito: ele propoe planos e resume contagens. O veredito e do motor deterministico.
- Nao afirmar ineditismo nem inexistencia de concorrencia sem pesquisa. Concorrentes vistos (nos textos, nao testados): Testing Center (decisao e resposta do agente), testes de Flow (resultado no nivel do Flow), Copado, Panaya, Provar, Gearset.
- Uma pasta, um dono (`OWNERS.md`). Mudanca de contrato so em `contracts/`, com aviso aqui.

## Divisao do que falta (build ate 8/11)

| Item | Quem | Observacao |
|---|---|---|
| Modo somente demonstracao na URL publica (bloqueia execucao real; gerar, revisar e auditar liberados) | Codex (`web/`) | com testes; variavel de ambiente |
| Subir o app com reinicio automatico (systemd/compose), volume persistente, token forte | Codex (`infra/`) + Airton | sem expor porta 8000 |
| Roteiro de teste na org real: gerar -> vincular -> aprovar -> executar -> auditar, com Cases sinteticos novos | Claude Code (roteiro) + Airton (executa) | Cases novos; nao reutilizar os do CLI |
| Versao defeituosa do Flow (motivo vazio) para capturar a falha real | Airton | exige aprovacao explicita para execucao real |
| Narrativa, descricao curta/longa da submissao, slides, roteiro do video (<5 min), capa 16:9 | ChatGPT (`README.md`, texto) | usar a frase do norte; sem afirmar o que nao foi verificado |
| Entrevistas (3 a 5 pessoas) | Airton | roteiro de 7 perguntas na conversa do Claude; ChatGPT revisa |
| Avaliar a cobertura com o modelo real (`python -m planner.coverage_eval ...`) | Airton executa, Claude le o resultado | meta: zero falsa cobertura |

## Demo sugerida (ordem)
1. Intencao em portugues. 2. Plano da Vultr com a cobertura (uma clausula nao verificada, visivel). 3. Aprovacao humana. 4. Execucao real pelo Agentforce. 5. Relatorio antes/depois. 6. Auditoria de um lote com a taxa e as falhas. Se houver Flow defeituoso: o relatorio marcando falha onde o agente disse que concluiu e o ponto alto.

## Nao dizer (ainda)
"Primeiros do mercado", "ja funciona em producao", "resolve a confianca em agentes", "Blast Radius Zero". Dizer: protótipo validado na org de desenvolvimento, com evidencias; auditoria testada apenas em simulacao ate rodarmos na org real.
