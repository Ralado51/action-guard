# Alinhamento do time (ChatGPT, Codex, Claude Code, Gemini, Airton)

Atualizado em 08/11/2026. Fonte unica para quem entra agora: leia este arquivo, depois `STATUS.md` e `docs/DECISIONS.md`. Se algo aqui contradiz o codigo ou o `STATUS.md`, vale o codigo e avise o Airton.

## Norte (frase do projeto)
Action Guard transforma a intencao de uma acao de IA em um plano verificavel e confere seus efeitos nos dados do negocio, **no escopo monitorado**. A pessoa aprova antes e recebe evidencias depois.

Pergunta central: "O agente disse que fez. Os dados comprovam que fez corretamente, sem efeitos indesejados no escopo observado?"

Regra de escopo: cada funcionalidade nova precisa ajudar esse fluxo ou espera. Processo unico: `close_case`. Trilha do hackathon: a confirmar com o regulamento (o regulamento diz "choose one path").

## O que existe, por camada (e quao verificado)

| Camada | O que faz | Dono (OWNERS.md) | Verificacao |
|---|---|---|---|
| `contracts/` | schemas, hash do plano, semantica | Claude Code | testes; mudancas aditivas registradas em `docs/DECISIONS.md` |
| `engine/` | verificacoes deterministicas antes/depois | Codex | testes + oraculo independente |
| `connector/` + `orchestrator/` | Salesforce/Agentforce, execucao unica sem retry, CLI `prepare/run` | Codex / Claude Code | **real** (operador, CLI, seis checks passed) + testes simulados |
| `planner/` | regra em portugues -> plano via Vultr; cobertura por clausula | Claude Code | real so a geracao do plano (informado pelo operador); cobertura so simulada |
| `audit/` | auditoria somente leitura do estado final, taxa por regra | Claude Code | simulado + **20 Cases sinteticos auditados na org real** |
| `web/` | API + interface (gerar, aprovar, auditar, achados, Dashboard, demo ao vivo, operadores) | Codex / Claude Code | simulado + demo ao vivo na org de desenvolvimento |
| `sandbox/` (PR #5, fora da base) | avaliador offline isolado em Docker | Codex | complementar; nao sustenta "Blast Radius Zero" |
| Implantacao | VM Vultr + HTTPS no dominio do Airton | Airton | `/health` responde por HTTPS (conferido de fora) |

Suite: 473 testes (Python 3.12), todos com Salesforce e Vultr simulados. Quantidade de testes e evidencia de qualidade, nao proposta de valor.

## Estado do repositorio
Tudo mergeado na main (PRs ate #44): planner, CLI, web, auditoria, achados e dossie, demo ao vivo, Dashboard, operadores. O PR #5 (sandbox offline) segue aberto e fora da entrega. Veja `STATUS.md` para o que foi verificado.

## Regras que todos seguem
- Dados sinteticos. Nenhum segredo, dominio do org, Agent ID, ID de usuario ou IP da VM no repositorio, em commit ou em PR.
- Nenhuma acao real no Salesforce sem aprovacao explicita do Airton. Auditoria e somente leitura.
- LLM nao decide veredito: ele propoe planos e resume contagens. O veredito e do motor deterministico.
- Nao afirmar ineditismo nem inexistencia de concorrencia sem pesquisa. Concorrentes vistos (nos textos, nao testados): Testing Center (decisao e resposta do agente), testes de Flow (resultado no nivel do Flow), Copado, Panaya, Provar, Gearset.
- Uma pasta, um dono (`OWNERS.md`). Mudanca de contrato so em `contracts/`, com aviso aqui.

## O que falta (prazo 8/11, 20:00)
Veja "Pendencias" em `STATUS.md`: chave do operador e codigo de acesso nas notas da submissao, video, slides, capa e texto do formulario.

## Demo sugerida (ordem)
1. Intencao em portugues. 2. Plano da Vultr com a cobertura (uma clausula nao verificada, visivel). 3. Aprovacao humana. 4. Execucao real pelo Agentforce. 5. Relatorio antes/depois. 6. Auditoria de um lote com a taxa e as falhas. Se houver Flow defeituoso: o relatorio marcando falha onde o agente disse que concluiu e o ponto alto.

## Nao dizer (ainda)
"Primeiros do mercado", "ja funciona em producao", "resolve a confianca em agentes", "Blast Radius Zero". Dizer: protótipo validado na org de desenvolvimento, com evidencias; auditoria rodada em 20 Cases sinteticos da org de desenvolvimento, com as limitacoes do STATUS.
