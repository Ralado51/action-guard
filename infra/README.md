# Implantacao de um operador

Arquivos preparados; nao equivalem a deploy validado. Execute na VM como operador autorizado.
O proxy HTTPS existente deve encaminhar ao loopback da VM. A porta 8000 nao deve ser
publicada na interface externa. Nao mudar proxy, firewall ou DNS automaticamente.

## Configuracao privada (fora do checkout)

Crie um arquivo de ambiente legivel somente pelo operador (`chmod 600`), fora do
repositorio. Gere o token com `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`
e guarde-o nesse arquivo sem colocar seu valor no historico de comandos.
Inclua estas variaveis, com os valores do seu ambiente:

- `ACTION_GUARD_DEMO_MODE=true` (obrigatorio na URL publica de demonstracao).
- `ACTION_GUARD_API_TOKEN` (token aleatorio; startup exige pelo menos 32 caracteres).
- `SF_LOGIN_URL`, `SF_API_VERSION`, `SF_AGENT_ID`, `SF_CLIENT_ID`, `SF_CLIENT_SECRET`.
- `VULTR_INFERENCE_API_KEY`, `VULTR_INFERENCE_BASE_URL`, `VULTR_INFERENCE_MODEL`.

Nao cole valores, metadados reais ou dados de execucao em commits, PRs ou logs compartilhados.
O token compartilhado identifica um operador; nao e login multiusuario nem permite
isolar dados entre visitantes. Nunca embuta esse token no frontend publico.
Planejamento e auditoria continuam autenticados e podem consumir APIs e gerar custos.
O modo demonstracao bloqueia execucao pelo backend web, inclusive tarefas enfileiradas;
nao altera comandos CLI independentes. Nao rode CLI de execucao no ambiente publico.

## Subir e verificar

Exporte `ACTION_GUARD_ENV_FILE` com o caminho absoluto do arquivo privado e
`ACTION_GUARD_METADATA_FILE` com o caminho absoluto do JSON Describe ja coletado.
O usuario 10001 do container precisa conseguir ler o JSON (sem permissao de escrita).

```bash
docker compose -f infra/compose.yaml build
docker compose -f infra/compose.yaml up -d
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/api/capabilities
docker compose -f infra/compose.yaml ps
```

A segunda consulta deve retornar `demo_mode: true` e `execution_enabled: false`.
Teste POST `/api/runs` com token valido: deve retornar 403 sem reservar Case nem
chamar o agente. Gerar/revisar/aprovar/auditar continuam liberados para o operador.
Auditoria e somente leitura, mas usa conexao real se configurada: testar com dados
sinteticos e autorizacao do operador.

Configure o Docker para iniciar no boot da VM (operador: `sudo systemctl enable --now docker`).
A politica `unless-stopped` reinicia o processo/container; healthcheck nao e reiniciador.
Use so uma replica e um worker, com volume persistente. `BackgroundTasks` nao e fila
duravel: execucoes interrompidas exigem conciliacao, nunca reenvio automatico.

## Persistencia, backup e atualizacao

SQLite, planos, auditorias e evidencias ficam no volume nomeado `workflow` do projeto
Compose `action-guard`. O servico inicializador ajusta apenas a raiz do volume para
UID 10001; nao importa dados de instalacoes antigas. Nao copie um SQLite ativo:
pare o app e faca backup protegido do volume antes de atualizar/migrar, preservando
as reservas antigas. Planeje a importacao do diretorio antigo antes de permitir
execucao: iniciar banco vazio nao preserva reservas anteriores.

`docker compose -f infra/compose.yaml down` preserva o volume. **Nao use `down -v`**:
isso apaga reservas e evidencias. Restauracao e reinicio precisam ser testados na VM.
Para atualizar o modo, altere o arquivo privado e recrie o servico com `up -d --force-recreate web`.
Nao habilite execucao em uma URL de demonstracao publica. Nao ha socket Docker no app.

## Verificacoes locais

```bash
python -m pytest -q web/tests
```

Build, Compose em runtime, reboot da VM, persistencia apos recriacao, HTTPS e proxy
so podem ser declarados validados depois de executados pelo operador.

## Entrega desta branch

Base: `feat/outcome-audit`. Alteracoes somente em `web/` e `infra/`.
Verificado localmente: 395 testes em Python 3.12 (servicos externos simulados),
sintaxe JavaScript, YAML parseado e verificacoes estaticas da politica de deploy.
Nao verificado: build Docker, Compose em runtime, reinicio/persistencia, navegador,
HTTPS, modelo real e org real. Nenhuma acao no Salesforce, deploy ou merge executado.

Divergencia de historico encontrada nos documentos de entrada: houve evidencia
apresentada pelo operador de uma execucao web anterior bem-sucedida. Isso nao valida
a interface atual com cobertura por clausula e auditoria. Os documentos de outras
pastas nao foram alterados nesta entrega.
