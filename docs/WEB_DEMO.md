# Executar a interface na VM

A branch web inclui o fluxo validado no CLI. Nao publicar uma porta aberta para este teste.

1. Fazer checkout da branch e executar `sudo make docker-test` para gerar a imagem.
2. Preparar arquivo `.env.web` no servidor (chmod 600) com as variaveis de `.env.example`: credenciais SF/Vultr, ACTION_GUARD_API_TOKEN forte, SF_METADATA_PATH=/app/metadata.json, ACTION_GUARD_DATA_DIR=/app/runs/web. Nao imprimir, commitar ou enviar esse arquivo.
3. Metadados reais coletados devem existir em `/tmp/action-guard-metadata.json`; confirmar data e org do arquivo.
4. Criar diretorio persistente `runs`, com permissao do usuario que rodara o container.

```bash
sudo docker run --rm --name action-guard-web \
  --user "$(id -u):$(id -g)" \
  --env-file .env.web \
  -p 127.0.0.1:8000:8000 \
  --mount type=bind,src=/tmp/action-guard-metadata.json,dst=/app/metadata.json,readonly \
  --mount "type=bind,src=$PWD/runs,dst=/app/runs" \
  action-guard
```

No computador do operador: abrir tunel SSH para a VM, encaminhando a porta 8000 local para 127.0.0.1:8000 da VM. Abrir http://localhost:8000. Informar apenas o token da aplicacao no botao Conectar. O backend recebe as outras credenciais do arquivo protegido, nao da interface.

Primeiro validar cancelamento/revisao. Para teste real, gerar plano, vincular um Case sintetico novo, revisar campos e motivo, aprovar, e clicar explicitamente em Executar. O botao chama uma acao real com efeitos externos. Nao reutilizar Cases dos testes CLI. Baixar relatorio JSON e preservar o volume runs. Se processo parar ou estado ficar incerto, nao limpar banco nem repetir: reconciliar evidencias.

O teste em browser de desenvolvimento usa rotas simuladas e nao comprova conectividade real da interface. SQLite e BackgroundTasks destinam-se ao MVP com um processo, nao a uma fila distribuida.
