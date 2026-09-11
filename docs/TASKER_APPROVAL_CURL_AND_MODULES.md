# Teste cURL da aprovação Tasker e execução de módulos

## Preparar o gateway local

Use um segredo somente para desenvolvimento:

```bash
export ATENA_TASKER_HMAC_SECRET="t$(openssl rand -hex 32)"
export ATENA_TASKER_GATEWAY_DB="/tmp/atena-tasker-test.sqlite3"
PYTHONPATH="$PWD" uvicorn api.tasker_command_gateway:app --host 127.0.0.1 --port 8787
```

Em outro terminal, configure a mesma variável `ATENA_TASKER_HMAC_SECRET`. Não use o segredo de produção em um teste compartilhado.

O script reproduzível está em:

```text
scripts/tasker_approval_curl_smoke.sh
```

Execute:

```bash
ATENA_TASKER_TEST_URL="http://127.0.0.1:8787" \
ATENA_TASKER_DEVICE_ID="android-test" \
ATENA_TEST_CHAT_ID="chat-test" \
./scripts/tasker_approval_curl_smoke.sh
```

O teste faz quatro operações e não envia uma mensagem real:

| Etapa | Endpoint | Resultado esperado |
|---|---|---|
| Aprovar | `POST /v1/tasker/approve` | `status: approved` |
| Despachar | `POST /v1/tasker/dispatch` | `status: queued` |
| Retirar | `POST /v1/tasker/next` | Retorna a tarefa com `android_send_message` |
| Concluir | `POST /v1/tasker/result` | `status: completed` |

Cada requisição gera timestamp, nonce e assinatura HMAC sobre o corpo exato. O destinatário usado pelo script é apenas `contato-de-teste`.

## Comandos cURL manuais

Para gerar uma assinatura manual:

```bash
SECRET="$ATENA_TASKER_HMAC_SECRET"
BODY='{"device_id":"android-test"}'
TS="$(date +%s)"
NONCE="$(openssl rand -hex 16)"
SIG="$(printf '%s' "$TS.$NONCE.$BODY" | openssl dgst -sha256 -hmac "$SECRET" -hex | awk '{print $2}')"
```

Depois:

```bash
curl --fail-with-body -X POST http://127.0.0.1:8787/v1/tasker/next \
  -H 'Content-Type: application/json' \
  -H "X-Atena-Timestamp: $TS" \
  -H "X-Atena-Nonce: $NONCE" \
  -H "X-Atena-Signature: $SIG" \
  --data-binary "$BODY"
```

Não reutilize `TS`, `NONCE`, `SIG` ou o corpo de uma chamada anterior. O gateway rejeita nonces repetidos.

## Atena pode executar módulos?

A Atena possui um catálogo estático de capacidades em `core/capability_registry.py`. Ele identifica arquivos dentro das raízes permitidas, verifica sintaxe via AST e só considera executáveis módulos que tenham um ponto de entrada conhecido, como `main`, `run` ou `cli`.

Existe um módulo chamado `hydra_protocol` em `modules/hydra_protocol.py`. O catálogo o identifica como:

```text
hydra_protocol — runnable — main
```

Entretanto, atualmente não existe um comando Telegram universal que permita executar qualquer módulo pelo nome. Isso é intencional: conectar diretamente “Atena, execute Hydra” a `run_capability()` daria a uma mensagem acesso amplo a geração de infraestrutura, arquivos, backups ou restauração.

O Hydra, especificamente, gera Docker, Compose, Terraform, Kubernetes e Ansible, além de criar/restaurar estado e iniciar um monitor de heartbeat ao ser importado. Portanto, ele **não deve ser exposto como comando livre**.

## Política recomendada para módulos

Para permitir um módulo com segurança, crie uma ação explícita e estreita, por exemplo:

```text
hydra_status
hydra_generate_docker_preview
```

Essas ações devem:

1. aceitar somente argumentos tipados e limitados;
2. gravar em um diretório temporário ou de revisão;
3. não executar Docker, Terraform, Ansible, SSH ou `subprocess` automaticamente;
4. exigir confirmação para gerar ou alterar arquivos;
5. enviar o resultado para uma Pull Request, nunca diretamente para `main`;
6. executar testes e inspeção de secrets antes da publicação;
7. registrar quem solicitou, qual commit foi usado e quais arquivos foram produzidos.

A ordem segura é:

```text
pedido Telegram → parser allowlist → confirmação se necessário → sandbox → benchmark/testes → PR → revisão/merge
```

Assim, a Atena pode usar módulos como Hydra como **capacidades controladas**, mas não deve aceitar “execute qualquer módulo” ou importar código arbitrário recebido pela internet.
