# Serviço systemd do bot Telegram da Atena

A unidade `deploy/atena-telegram.service` mantém o processo `scripts/atena_telegram_chat.py` ativo no Ubuntu, reinicia falhas e envia logs para o journal do systemd.

## Instalação

Confirme que o repositório está em `/home/ubuntu/Atena-IA` e que o serviço será executado pelo usuário `ubuntu`. Se usar outro usuário ou caminho, ajuste `User`, `Group`, `WorkingDirectory`, `PYTHONPATH` e `ExecStart` na unidade.

```bash
sudo install -d -m 0750 /etc/atena
sudo install -o root -g ubuntu -m 0640 deploy/atena-telegram.env.example /etc/atena/telegram.env
sudoedit /etc/atena/telegram.env
```

Preencha pelo menos:

```text
ATENA_TELEGRAM_BOT_TOKEN=token-real-do-bot
ATENA_TELEGRAM_CHAT_ID=chat-id-autorizado
```

Se o bot usar pesquisa atual, o Ollama deve estar acessível em `ATENA_OLLAMA_CHAT_URL`. Se usar Tasker, configure também `ATENA_TASKER_DISPATCH_URL`, `ATENA_TASKER_HMAC_SECRET` e `ATENA_TASKER_DEVICE_ID`.

Proteja o arquivo:

```bash
sudo chown root:ubuntu /etc/atena/telegram.env
sudo chmod 0640 /etc/atena/telegram.env
```

Instale a unidade:

```bash
sudo install -o root -g root -m 0644 deploy/atena-telegram.service /etc/systemd/system/atena-telegram.service
sudo systemctl daemon-reload
sudo systemctl enable atena-telegram.service
sudo systemctl start atena-telegram.service
```

## Verificação

```bash
systemctl status atena-telegram.service --no-pager
systemctl is-enabled atena-telegram.service
systemctl is-active atena-telegram.service
```

O estado esperado é `active (running)`. Os logs ficam no journal:

```bash
journalctl -u atena-telegram.service -n 100 --no-pager
journalctl -u atena-telegram.service -f
```

Uma inicialização correta deve registrar algo semelhante a:

```text
ponte Telegram iniciada; modelo=qwen2.5:3b-instruct
```

## Teste do Telegram

Não imprima o token. Verifique a API:

```bash
set -a
. /etc/atena/telegram.env
set +a
curl --fail-with-body --silent --show-error \
  "https://api.telegram.org/bot${ATENA_TELEGRAM_BOT_TOKEN}/getMe"
```

Teste o envio:

```bash
curl --fail-with-body --silent --show-error -X POST \
  "https://api.telegram.org/bot${ATENA_TELEGRAM_BOT_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${ATENA_TELEGRAM_CHAT_ID}" \
  --data-urlencode "text=Teste do serviço systemd da Atena — $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
```

## Atualização do código

Depois de atualizar o repositório:

```bash
cd /home/ubuntu/Atena-IA
git pull --ff-only
sudo systemctl restart atena-telegram.service
sudo systemctl status atena-telegram.service --no-pager
```

O arquivo `telegram.env` fica fora do Git e não é sobrescrito pelo `git pull`.

## Evitar dois processos de polling

O Telegram permite apenas um consumidor de long polling para o mesmo bot. Antes de iniciar manualmente, verifique:

```bash
pgrep -af 'scripts/atena_telegram_chat.py'
```

Se o serviço systemd estiver ativo, não execute uma segunda cópia manual. Um conflito pode aparecer como:

```text
Conflict: terminated by other getUpdates request
```

Para parar temporariamente:

```bash
sudo systemctl stop atena-telegram.service
```

Depois de concluir o teste manual, reative-o:

```bash
sudo systemctl start atena-telegram.service
```

## Diagnóstico rápido

| Sintoma | Verificação |
|---|---|
| Serviço para imediatamente | `journalctl -u atena-telegram.service -n 100` |
| `status=217/USER` | Confirme que o usuário `ubuntu` existe e que os caminhos pertencem a ele |
| `variável ausente` | Verifique `/etc/atena/telegram.env` e permissões |
| `Unauthorized` | Token inválido ou revogado; gere um token novo no BotFather |
| `chat not found` | Chat ID incorreto ou conversa ainda não iniciada com o bot |
| `Conflict` | Existe outro processo usando `getUpdates` |
| Pesquisa web falha | Verifique a conectividade e o Ollama em `127.0.0.1:11434` |
| Serviço ativo, mas não responde | Verifique allowlist de `ATENA_TELEGRAM_CHAT_ID` e `journalctl` |

A unidade reinicia o processo quando ele termina, mas não concede ao bot permissão para executar comandos arbitrários. As políticas de allowlist, confirmação Tasker e aprovação de ações sensíveis continuam valendo.
