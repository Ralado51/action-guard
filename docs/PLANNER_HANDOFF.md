# Planner Vultr — handoff para Claude

Data: 2026-11-05. Base de trabalho: branch fix/salesforce-execution-gates, com integracao Salesforce, portoes e motor deterministico. PR #1 aberto; main ainda nao contem essa integracao. Inspecionar remoto antes de iniciar e criar branch propria a partir da base atualizada. Nao substituir trabalho concorrente.

## Estado confirmado

197 testes locais aprovados; operador informou 197 testes aprovados em Docker na VM. Operador tambem executou o conector/orquestrador/motor contra Case sintetico novo, com APROVAR e resultado passed nas seis verificacoes. Evidencias arquivadas na VM; arquivo nao inspecionado pelo assistente. Motivo e Subject completos foram confirmados por exports JSON: Resolved - Customer confirmed e Action Guard - Case closure follow-up. Nao repetir o Case usado. Nao copiar IDs, dominio, IP ou credenciais para fixtures publicas.

## Entrega solicitada

Implementar em planner/ um cliente Vultr e geracao de test_plan em rascunho a partir de Rule em portugues e contexto de metadados fornecido explicitamente pelo backend. O planner nao recebe credenciais Salesforce, nao cria Case, nao executa agente e nao aprova plano. Preservar os contratos existentes; propor separadamente qualquer mudanca de contrato. Nao editar web/ do Gemini.

Configuracao existente: VULTR_INFERENCE_BASE_URL, VULTR_INFERENCE_API_KEY, VULTR_INFERENCE_MODEL. Base padrao https://api.vultrinference.com/v1; POST /chat/completions com Bearer e modelo configurado. Modelo anteriormente testado pelo operador: deepseek-v4.1-flash-1017; manter selecionavel por ambiente. Documentacao consultada: https://api.vultrinference.com/docs/reference/create-chat-completion e https://api.vultrinference.com/docs/get-started/quickstart . Usar choices[0].message.content; nao confundir reasoning com plano. Conferir finish_reason e rejeitar resposta truncada, tool_calls, vazia ou fora do formato esperado. Nao presumir suporte universal a JSON Schema nativo no modelo: validar localmente.

## Interface sugerida (interna, nao novo contrato publico)

create_plan(rule, metadata_context, action_context, transport) -> draft test_plan

- rule segue contracts/rule.schema.json.
- metadata_context lista somente objetos/campos autorizados e tipos, valores de picklist, capacidade de leitura e instante/origem da coleta. Nao declarar metadados reais quando vierem de fixtures. Sem contexto suficiente, devolver erro recuperavel; nao inventar campos.
- action_context informa a unica acao suportada neste MVP, processo close_case, motivo solicitado e Subject da Task esperado. Case ID, quando conhecido, deve vir do backend/operador e nunca ser inventado pelo LLM.
- O modelo propoe checks e descricoes; identificadores, rule_id, versao e hash sao atribuidos/recalculados pelo servidor. Remover qualquer approval gerado pelo modelo. Plano novo sempre sem aprovacao.
- JSON Schema de test_plan mais validate_plan_semantics antes de devolver. Validar objetos e campos contra metadata_context, limites de tamanho, quantidade de checks e janela de polling. Campo inventado, objeto fora do escopo ou allowed_changes ampliado para OwnerId deve ser rejeitado.
- Nao aceitar aprovacao, executar ferramentas ou enfraquecer invariantes por instrucao na regra em linguagem natural. Para este MVP manter requisitos de Status Closed, motivo exato e nao vazio, OwnerId preservado, exatamente uma Task nova com WhatId/Subject corretos e verificacao de mudancas inesperadas.
- Motivo deve pertencer aos quatro valores conhecidos e confirmar presenca no metadata_context; ausencia ou ambiguidade deve gerar solicitacao de correcao, nunca escolha silenciosa.
- Tentativas limitadas: no maximo duas chamadas de geracao/correcao por operacao, timeout e limite de tokens. Nao usar loop aberto. Erros 401/403 falham sem retry; tratar 429/5xx com politica limitada e explicita sem ultrapassar o orcamento. Nao enviar resposta bruta de erro ou chave ao frontend.
- Erro recuperavel com categoria e mensagem segura: configuracao, timeout, rate_limit, resposta invalida, schema, semantica ou contexto insuficiente. Sem fallback silencioso para fixture ou plano predefinido apresentado como IA.

## Vinculo do Case: decisao obrigatoria antes da aprovacao

O executor exige action.input.case_id no hash aprovado e igualdade com o argumento case_id. Hoje docs/API.md afirma que cada execucao cria seu Case, mas POST /api/plans recebe somente texto/processo e nao define como vincular o ID antes da aprovacao. Nao contornar o portao nem inserir ID depois de aprovar.

Propor fluxo: geracao inicial em rascunho -> provisionamento explicito do Case sintetico pelo backend confiavel -> vinculo do ID e motivo -> novo hash/versao -> revisao humana -> aprovacao -> execute_run. O provisionamento nao e responsabilidade do LLM. Outra opcao e Case de teste fornecido explicitamente, como no teste real validado. Documentar a escolha e alinhar docs/API.md com Gemini antes de integrar a interface. A alteracao de qualquer dado apos aprovacao deve invalida-la.

## Testes e criterios de aceite

- Cliente com transporte simulado: requisicao/configuracao, erro de autenticacao, 429/5xx, timeout, corpo inesperado, choices vazio, content vazio, JSON invalido e finish_reason length.
- Geracao: regra valida em portugues produz rascunho valido sem approval; mesmo se modelo tentar autoaprovar. Hash recalculado localmente.
- Validacao: campo inventado, picklist invalida, motivo faltando, enfraquecimento de OwnerId/contagem de Tasks, excesso de checks e janela desproporcional sao rejeitados.
- No maximo duas chamadas; falha final nao devolve fixture como se tivesse sido gerada. Sem segredos em logs/erros.
- Edicao/vinculo do Case muda hash e exige nova aprovacao; plano sem ID nunca chega ao agente.
- Testes locais e make docker-test; explicitar quais foram efetivamente executados.
- Validacao real do planner na VM deve gerar apenas plano, sem escrever no Salesforce ou executar agente. Operador fornece chave por ambiente, nunca pelo chat. Registrar modelo, hash do plano, uso de tokens se retornado e resultado da validacao. Nao alegar teste real se apenas simulado.

## Entrega ao revisor

Publicar branch/PR com arquivos, testes e STATUS.md atualizado. Informar SHA base, teste simulado vs real, custo/uso observado quando disponivel, limites e pendencias. Nao mergear nem executar nova acao Salesforce automaticamente. Planner, interface e sandbox sao frentes distintas; o sucesso desta entrega nao comprova contencao do executor isolado.
