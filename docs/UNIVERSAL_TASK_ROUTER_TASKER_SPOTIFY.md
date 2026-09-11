# Roteador universal da Atena com Android, Tasker e Spotify

## Arquitetura

O fluxo seguro é:

```text
Telegram → Atena → parser determinístico → gateway HTTPS HMAC → fila SQLite → Tasker → Android
                                                                            ↓
                                                                  /v1/tasker/result
```

A Atena não envia texto Android arbitrário. O parser converte somente frases reconhecidas em intenções estruturadas. O gateway valida assinatura, timestamp e nonce e aceita apenas ações da allowlist.

O gateway precisa ficar em um host persistente com HTTPS real. `127.0.0.1` funciona apenas quando Atena e o gateway estão no mesmo computador; um workflow efêmero do GitHub Actions não é adequado para receber polling do Android.

## Variáveis da Atena

No processo que executa o bot Telegram:

```bash
export ATENA_TASKER_DISPATCH_URL="https://atena.exemplo.com"
export ATENA_TASKER_HMAC_SECRET="um-segredo-aleatorio-com-mais-de-32-caracteres"
export ATENA_TASKER_DEVICE_ID="android-principal"
```

No processo do gateway:

```bash
export ATENA_TASKER_HMAC_SECRET="o-mesmo-segredo"
export ATENA_TASKER_GATEWAY_DB="atena_evolution/tasker_gateway.sqlite3"
uvicorn api.tasker_command_gateway:app --host 127.0.0.1 --port 8787
```

Use um proxy HTTPS, firewall e rate limit. Nunca coloque o segredo no repositório ou em um perfil Tasker exportado publicamente.

## Frases reconhecidas

| Frase | Intenção | Confirmação |
|---|---|---|
| `abrir Spotify` | `android_open_app` com pacote `com.spotify.music` | Não, ação reversível |
| `tocar Evidências de um Rapaz de Fresno` | `spotify_search_open` | Não, abre uma busca |
| `pesquise e abra música X de artista Y` | `spotify_search_open` | Não, abre uma busca |
| `pausar mídia` | `android_media_pause` | Não |
| `retomar música` | `android_media_play` | Não |
| `próxima música` | `android_media_next` | Não |
| `música anterior` | `android_media_previous` | Não |
| `status do celular` | `android_status` | Não |
| `enviar mensagem`, `comprar`, `apagar arquivo` | `android_sensitive_action` | Sim; ainda não executa |

Ações sensíveis permanecem bloqueadas mesmo depois de confirmação até existir um executor específico, com escopo e confirmação final adequados.

## Endpoints do gateway

### Despachar uma intenção

`POST /v1/tasker/dispatch`

```json
{
  "command_id": "task-abc123456789",
  "device_id": "android-principal",
  "action": "spotify_search_open",
  "target": "spotify",
  "parameters": {"query": "Evidências de um Rapaz Fresno"}
}
```

O corpo deve ser assinado com:

```text
HMAC-SHA256(secret, timestamp + "." + nonce + "." + body_bytes)
```

Headers:

```text
X-Atena-Timestamp: Unix timestamp em segundos
X-Atena-Nonce: valor aleatório usado uma única vez
X-Atena-Signature: digest hexadecimal
```

### Retirar a próxima tarefa

`POST /v1/tasker/next`

Corpo:

```json
{"device_id":"android-principal"}
```

O Tasker deve assinar também essa requisição. Se não houver trabalho, a resposta será:

```json
{"task":null,"device_id":"android-principal"}
```

Quando houver trabalho, a resposta terá `action`, `target`, `parameters` e `command_id`.

### Confirmar resultado

`POST /v1/tasker/result`

```json
{
  "command_id": "task-abc123456789",
  "device_id": "android-principal",
  "ok": true,
  "result": {"opened": true}
}
```

## Configuração do Tasker

Crie três Profiles/Tasks.

### Perfil `ATENA — buscar tarefa`

Configure uma repetição moderada, por exemplo a cada 15 segundos, somente enquanto o Android estiver conectado à rede autorizada. No Tasker:

1. Use **HTTP Request** com método `POST` para `https://atena.exemplo.com/v1/tasker/next`.
2. Envie `{"device_id":"android-principal"}` como corpo JSON.
3. Gere `timestamp`, `nonce` e o HMAC com o mesmo segredo. O HMAC deve usar o corpo byte a byte exatamente como enviado.
4. Se `task` for nulo, termine a tarefa.
5. Guarde `command_id`, `action`, `target` e `parameters` em variáveis locais.
6. Encaminhe para o perfil de execução somente as ações reconhecidas.

Se a versão do Tasker não oferecer uma ação HMAC direta, use um JavaScriptlet local ou um pequeno helper local instalado no Android. Não use um serviço público de geração de HMAC.

### Perfil `ATENA — executar ação`

Use uma cadeia `If/Else`:

- `android_open_app`: use **Launch App** somente para pacotes permitidos; para Spotify, `com.spotify.music`.
- `spotify_search_open`: abra uma URL segura no formato `spotify:search:<consulta-URL-encoded>` ou use **Browse URL** com `https://open.spotify.com/search/<consulta-URL-encoded>`.
- `android_media_play`: use **Media Control → Play**.
- `android_media_pause`: use **Media Control → Pause**.
- `android_media_next`: use **Media Control → Next**.
- `android_media_previous`: use **Media Control → Previous**.
- `android_status`: leia bateria, rede e aplicativo em primeiro plano, sem coletar conteúdo privado.

Nunca execute o campo `action` como shell, JavaScript ou comando arbitrário. A ação deve coincidir exatamente com uma das seis ações autorizadas pelo gateway.

### Perfil `ATENA — resultado`

Depois de executar, faça `POST /v1/tasker/result` com o `command_id` original. Envie `ok=false` e uma descrição curta se o aplicativo não estiver instalado ou se a permissão falhar. Não inclua tokens, mensagens privadas, senhas ou conteúdo de notificações no campo `result`.

## Testes locais

Testes unitários:

```bash
cd /home/ubuntu/Atena-IA
PYTHONPATH="$PWD" pytest -q \
  tests/unit/test_universal_task_router.py \
  tests/unit/test_tasker_gateway_and_x.py \
  tests/unit/test_workspace_actions.py
```

Resultado esperado atual:

```text
11 passed
```

Teste do parser sem gateway:

```bash
PYTHONPATH="$PWD" python -c 'from core.universal_task_router import parse_task_intent; print(parse_task_intent("tocar Evidências de um Rapaz de Fresno"))'
```

Para testar o gateway, configure um segredo de desenvolvimento de pelo menos 32 caracteres, use um banco SQLite temporário e assine cada requisição. O teste não deve usar o token real do Telegram nem o segredo de produção.

## Spotify e licenciamento

O roteador abre uma busca ou controla a reprodução no aplicativo; ele não contorna autenticação, assinatura, DRM ou limitações do Spotify. Downloads de músicas só devem ser realizados quando o próprio serviço ou o artista oferecerem uma opção autorizada.


## Confirmação de ações sensíveis

Chamadas e mensagens seguem um fluxo de duas etapas:

```text
pedido no Telegram
    ↓
Atena cria task_id e mostra destinatário/texto
    ↓
usuário responde exatamente: CONFIRMAR task_id
    ↓
Atena registra /v1/tasker/approve
    ↓
aprovação fica válida por até 120 segundos
    ↓
Atena despacha /v1/tasker/dispatch com approval_id
    ↓
gateway valida hash, dispositivo, ação e expiração
    ↓
Tasker executa e chama /v1/tasker/result
```

Exemplo de solicitação:

```text
Atena, enviar mensagem para Danilo: Cheguei em casa
```

A Atena deve responder com um resumo equivalente a:

```text
Esta ação no Android exige confirmação: android_send_message.
Detalhes: {'recipient': 'Danilo', 'text': 'Cheguei em casa'}
Responda CONFIRMAR task-... ou CANCELAR task-....
```

A confirmação é vinculada ao chat que solicitou, ao `device_id`, à ação, aos parâmetros e ao hash canônico da intenção. Alterar o destinatário, o texto, o dispositivo ou a ação invalida a aprovação. O gateway também impede reutilização: depois do despacho, o registro passa para `consumed`.

No Tasker, chamadas e mensagens só devem ser executadas quando a tarefa recebida já estiver em estado `claimed` pelo gateway. O Tasker não deve criar sua própria confirmação baseada apenas em uma variável local, pois a aprovação oficial precisa vir do gateway assinado.

Para máxima segurança, configure também:

```bash
export ATENA_TASKER_APPROVAL_TTL_SECONDS=120
```

O intervalo aceito pelo gateway é de 30 a 300 segundos. Em um telefone compartilhado, use um `device_id` separado por aparelho e mantenha o chat permitido em uma lista restrita.
