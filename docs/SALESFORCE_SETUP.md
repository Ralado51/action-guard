# Preparacao da org Salesforce

Roteiro para deixar a org de testes pronta para o conector e o planner. **Nada abaixo foi executado em uma org real.** Cada passo diz de onde veio: *(doc)* conferido na documentacao oficial em 04/11/2026; *(a verificar)* sugestao nossa, sem confirmacao em documentacao. Registre o que de fato funcionar em `docs/DECISIONS.md`.

Variaveis (nomes iguais aos de `.env.example`; os valores ficam no `.env`, fora do git):

```bash
export SF_LOGIN_URL="https://<seu-dominio>.my.salesforce.com"   # My Domain
export SF_CLIENT_ID="..."        # Consumer Key da External Client App
export SF_CLIENT_SECRET="..."    # Consumer Secret (nunca em chat nem no git)
```

## 1. External Client App (doc)

Setup, Quick Find "External Client App", gerenciador de External Client Apps, criar uma nova ("Action Guard"). A pagina de Connected Apps de outros guias esta desatualizada para orgs novas: use o gerenciador de External Client Apps.

- Habilitar OAuth. A URL de callback e exigida pelo formulario; o exemplo da documentacao usa `https://login.salesforce.com/services/oauth2/success`.
- Escopos: `api`, `refresh_token` / `offline_access`, `chatbot_api`, `sfap_api`.
- Habilitar **Client Credentials Flow** e **Issue JWT-based access tokens for named users**.
- Desmarcar: Require secret for Web Server Flow, Require secret for Refresh Token Flow e PKCE.
- Nas politicas, **Run As**: um usuario dedicado ("Action Guard Integration") com acesso **API Only**. Nome exato do perfil pode variar (a verificar). Conceda por permission set: Case e Task (criar, ler, editar), os objetos e campos customizados abaixo e acesso ao Flow.
- Consumer Key e Secret: nas configuracoes OAuth da propria app (normalmente pede um codigo de verificacao por e-mail) (a verificar).

## 2. Teste do token (doc)

```bash
TOKEN=$(curl -sS -X POST "$SF_LOGIN_URL/services/oauth2/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode grant_type=client_credentials \
  --data-urlencode client_id="$SF_CLIENT_ID" \
  --data-urlencode client_secret="$SF_CLIENT_SECRET" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('access_token') or d, end='')")
echo "${#TOKEN} caracteres"   # nunca imprima o token
```

Esperado: um numero grande de caracteres. Se vier um JSON de erro, cole **o erro** (sem segredos) no chat. A resposta tambem traz `instance_url` e `api_instance_url`.

## 3. Versao da API e campo do motivo de encerramento

```bash
curl -sS -H "Authorization: Bearer $TOKEN" "$SF_LOGIN_URL/services/data/" \
  | python3 -c "import sys,json; v=json.load(sys.stdin)[-1]; print(v['version'], v['url'])"
export SF_API="v<versao impressa>"

curl -sS -H "Authorization: Bearer $TOKEN" "$SF_LOGIN_URL/services/data/$SF_API/sobjects/Case/describe" \
  | python3 -c "
import sys,json
for f in json.load(sys.stdin)['fields']:
    if any(k in (f['name']+f['label']).lower() for k in ('reason','motivo','closure')):
        print(f['name'], '|', f['label'], '|', f['type'], '| criavel:', f['createable'])"
```

Decisao sua: usar um campo existente ou criar `Closure_Reason__c` (picklist). **Nao assumir `Case.Reason`.** Anote o API name final; os exemplos em `contracts/` usam `Closure_Reason__c` apenas como ilustracao.

## 4. Defeito controlado: objeto de flag (a verificar)

Objeto customizado `Action_Guard_Flag__c` com um unico registro e dois checkboxes: `Break_Owner__c` e `Skip_Task__c`. O conector altera esses campos por API para alternar entre a execucao com defeito e a corrigida. (Alternativa: configuracao personalizada hierarquica lida com `$Setup` no Flow; nao confirmado.)

## 5. Flow `Close_Case_Flow` (a verificar)

Flow autolaunched. Variaveis:

| Variavel | Tipo | Disponivel para |
| --- | --- | --- |
| `caseId` | Text | entrada |
| `closureReason` | Text | entrada |
| `resultMessage` | Text | saida |

Logica: buscar o registro de `Action_Guard_Flag__c`; atualizar o Case (`Status = Closed`, campo do motivo = `closureReason`); se `Break_Owner__c`, alterar tambem `OwnerId` para outro usuario sintetico; se `Skip_Task__c` for falso, criar uma Task (`Subject` = "Follow-up: " + assunto do Case, `WhatId = caseId`, `OwnerId` = proprietario do Case, `Status = Not Started`). A Task e criada de forma sincrona, entao `async_window` pode ser curta.

Teste o Flow primeiro pela interface (Debug) antes de chamar por API.

## 6. Teste do Flow por API (a verificar)

```bash
# Case sintetico novo a cada execucao
CASE_ID=$(curl -sS -X POST "$SF_LOGIN_URL/services/data/$SF_API/sobjects/Case" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"Subject":"Caso sintetico AG-001","Status":"In Progress","Priority":"Medium"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# Acao invocavel (caminho a verificar na primeira chamada)
curl -sS -X POST "$SF_LOGIN_URL/services/data/$SF_API/actions/custom/flow/Close_Case_Flow" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"inputs\":[{\"caseId\":\"$CASE_ID\",\"closureReason\":\"Resolved - Customer confirmed\"}]}"

# Efeitos
curl -sS -G -H "Authorization: Bearer $TOKEN" "$SF_LOGIN_URL/services/data/$SF_API/query" \
  --data-urlencode "q=SELECT Id,Status,OwnerId,ClosedDate,IsClosed FROM Case WHERE Id='$CASE_ID'"
curl -sS -G -H "Authorization: Bearer $TOKEN" "$SF_LOGIN_URL/services/data/$SF_API/query" \
  --data-urlencode "q=SELECT Id,Subject,WhatId,OwnerId,CreatedDate FROM Task WHERE WhatId='$CASE_ID'"
```

Esperado com as flags desligadas: Case `Closed`, mesmo `OwnerId` de antes, uma Task vinculada. Depois ligue `Break_Owner__c`, repita com um Case novo e confirme que o proprietario mudou. Desligue de novo ao final.

## 7. Agente Agentforce

- O Agent API **nao e suportado** para agentes do tipo "Agentforce (Default)" (doc). Crie um agente proprio e **ative-o**. Qual tipo de agente funciona melhor com o Agent API: a verificar.
- Garanta que o usuario atribuido ao agente tenha acesso a Case, Task, aos campos customizados e ao Flow. Com `bypassUser: true` a acao roda como esse usuario (doc).
- Crie um topico/subagente "Encerrar atendimento" e adicione o Flow `Close_Case_Flow` como acao (a verificar no builder: o Flow precisa estar ativo e com as variaveis marcadas como entrada/saida). Descreva cada entrada para o modelo, por exemplo: `caseId` = Id do Case de 18 caracteres informado pelo usuario; `closureReason` = motivo informado pelo usuario.
- Teste no preview do builder com algo como: "Encerre o Case <id> com o motivo Resolved - Customer confirmed e crie o acompanhamento." O agente e um LLM: confira nos registros, nao so na resposta.
- Agent ID (doc): builder classico, os 18 caracteres no fim da URL da pagina do agente; novo builder, `SELECT Id, DeveloperName FROM BotDefinition WHERE DeveloperName = '<nome>'`.

## 8. Teste do Agent API (doc)

Base: `https://api.salesforce.com/einstein/ai-agent/v1`. Use o mesmo token da External Client App.

```bash
export SF_AGENT_ID="..."
SESSION=$(curl -sS -X POST "https://api.salesforce.com/einstein/ai-agent/v1/agents/$SF_AGENT_ID/sessions" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"externalSessionKey\":\"$(python3 -c 'import uuid;print(uuid.uuid4())')\",
       \"instanceConfig\":{\"endpoint\":\"$SF_LOGIN_URL\"},
       \"streamingCapabilities\":{\"chunkTypes\":[\"Text\"]},
       \"bypassUser\":true}" | python3 -c "import sys,json; print(json.load(sys.stdin)['sessionId'])")

curl -sS -X POST "https://api.salesforce.com/einstein/ai-agent/v1/sessions/$SESSION/messages" \
  -H "Authorization: Bearer $TOKEN" -H "Accept: application/json" -H "Content-Type: application/json" \
  -d "{\"message\":{\"sequenceId\":1,\"type\":\"Text\",\"text\":\"Encerre o Case $CASE_ID com o motivo Resolved - Customer confirmed e crie o acompanhamento.\"}}"

curl -sS -X DELETE "https://api.salesforce.com/einstein/ai-agent/v1/sessions/$SESSION" \
  -H "Authorization: Bearer $TOKEN" -H "x-session-end-reason: UserRequest"
```

`sequenceId` cresce a cada mensagem da sessao. A resposta sincrona traz `messages`; o texto do agente esta no item de tipo `Inform`. Depois, repita as duas consultas do passo 6 para ver o que a acao realmente fez.

## 9. O que entregar ao conector (sem segredos)

API name do campo do motivo; nome e variaveis do Flow; objeto e campos da flag; versao da API; Agent ID; usuario Run As e usuario do agente. Segredos nunca vao ao repositorio nem ao chat.

## Limites e riscos (a verificar)

- A saida de LLM da org de desenvolvimento pode ser limitada por hora e a org pode expirar por inatividade. Use a org todos os dias e evite laco de testes com o agente.
- Cada execucao cria um Case novo; nunca reutilize um Case ja encerrado.

## Fontes

- [Agent API: Get Started](https://developer.salesforce.com/docs/ai/agentforce/guide/agent-api-get-started.html)
- [Agent API: Examples](https://developer.salesforce.com/docs/ai/agentforce/guide/agent-api-examples.html)
- [Agent API: obter o Agent ID](https://developer.salesforce.com/docs/ai/agentforce/guide/agent-api-agent-id.html)
- [Criar uma app para o Client Credentials Flow (guia de Loyalty)](https://developer.salesforce.com/docs/industries/loyalty/guide/authorization.html)
