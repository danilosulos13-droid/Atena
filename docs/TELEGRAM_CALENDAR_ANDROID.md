# Telegram, Google Calendar e Android

## Comandos

```text
/agenda
/agendar reunião comercial em 25/08/2026 às 14:30 no Google Calendar
```

`/agenda` usa o escopo `calendar.events.readonly` e lista os próximos eventos. `/agendar` cria uma intenção e mostra os parâmetros identificados. A Atena exige `CONFIRMAR workspace-...` antes de chamar o método de inserção do Google Calendar.

O cliente está em `core/google_calendar_client.py`. O bot chama as operações em thread para não bloquear o long polling do Telegram. O token é armazenado em `secrets/google/calendar-token.json`, excluído pelo `.gitignore`, e as credenciais ficam em `secrets/google/credentials.json`.

## Configuração local

```bash
python3 -m pip install -r requirements.txt
mkdir -p secrets/google
cp /caminho/baixado/credentials.json secrets/google/credentials.json
python3 examples/google_calendar_list_events.py \
  --credentials secrets/google/credentials.json \
  --token secrets/google/calendar-token.json
```

A primeira execução abre o consentimento OAuth. Depois, inicie o bot Telegram normalmente. Se a conta não estiver autorizada, `/agenda` retornará uma mensagem de configuração; não haverá tentativa silenciosa de usar uma conta diferente.

## Android semelhante ao Gemini

Atena pode oferecer uma experiência parecida em tarefas práticas, mas Android não concede controle total automaticamente. Para abrir aplicativos e executar rotinas, use Tasker/AutoNotification ou um agente Android próprio. O agente deve aceitar somente mensagens estruturadas, por exemplo `ATENA_CMD: abrir spotify`, verificar o chat autorizado e rejeitar texto arbitrário.

A arquitetura recomendada é:

```text
Telegram → Atena → intenção autorizada → Tasker/agente Android → aplicativo
```

Ações como abrir um aplicativo, consultar bateria ou pausar mídia podem ser liberadas. Enviar mensagens, apagar arquivos, instalar aplicativos, fazer compras ou alterar configurações de segurança devem exigir confirmação adicional. O Telegram não deve ser usado como canal para enviar senha, token OAuth ou código de execução.

## Limitações

A implementação atual ativa o Google Calendar; Outlook Calendar e Google Sheets continuam com o núcleo de intenções pronto, mas exigem adaptadores OAuth próprios. A Atena não deve ser descrita como uma cópia completa do Gemini: as capacidades dependem das APIs, permissões e serviços instalados no dispositivo.
