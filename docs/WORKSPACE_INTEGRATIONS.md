# Integrações de planilhas e calendários da Atena

A Atena agora possui um núcleo de intenções para separar leitura, criação e alteração de planilhas e calendários. O bot Telegram reconhece comandos explícitos e não encaminha essas ações diretamente ao Ollama.

## Comandos previstos

| Comando | Ação | Confirmação |
|---|---|---|
| `/agenda` | Consultar agenda | Não, somente leitura |
| `/agendar reunião 25/08/2026 às 14:30` | Criar evento | Sim |
| `/cancelar evento ...` | Cancelar evento | Sim |
| `/criar planilha Ganhos 2026` | Criar planilha | Sim |
| `/preencher planilha ...` | Alterar células ou tabela | Sim |
| `/analisar planilha ...` | Ler e analisar dados | Não, somente leitura |

As confirmações usam o formato `CONFIRMAR workspace-...` ou `CANCELAR workspace-...`. Sem a confirmação correta, nenhuma ação de escrita deve ser executada.

## Google Workspace

Para ler e analisar planilhas, o escopo preferencial é `https://www.googleapis.com/auth/spreadsheets.readonly`. Para criar ou editar planilhas, a documentação do Sheets recomenda considerar `https://www.googleapis.com/auth/drive.file`, que limita o acesso aos arquivos específicos utilizados pelo aplicativo, ou `https://www.googleapis.com/auth/spreadsheets` quando a operação realmente exigir acesso amplo [1].

Para ler eventos, use `https://www.googleapis.com/auth/calendar.events.readonly`. Para criar ou editar eventos, use `https://www.googleapis.com/auth/calendar.events`. O escopo amplo `https://www.googleapis.com/auth/calendar` deve ser evitado, porque também permite compartilhar calendários e excluir calendários acessíveis [2].

## Microsoft 365

Para Excel, o Microsoft Graph usa arquivos em OneDrive for Business, SharePoint ou drives de grupos. A documentação indica `Files.Read` para leitura e `Files.ReadWrite` para alterações [3]. A Atena deve começar com `Files.Read` e solicitar escrita somente quando o usuário ativar explicitamente a criação ou edição de planilhas.

Para consultar eventos, use `Calendars.Read`. Para criar, editar ou cancelar eventos, o Graph requer `Calendars.ReadWrite` para o calendário do usuário [4]. Cada operação de escrita deve ser precedida por uma confirmação no Telegram e registrada com o identificador do evento ou arquivo.

## Política de segurança

Atena deve usar OAuth 2.0, armazenar tokens fora do Git e nunca solicitar senhas por Telegram. A conta deve começar em modo somente leitura. As ações de escrita precisam registrar usuário, chat, intenção, parâmetros, horário, provedor e resultado. Antes de criar um evento, a Atena deve mostrar título, data, hora, fuso, participantes e local. Antes de editar uma planilha, deve mostrar o arquivo, aba, intervalo e valores que serão alterados.

A implementação atual prepara e valida intenções, mas não executa chamadas externas até que os adaptadores OAuth de Google e Microsoft sejam configurados. Isso evita que uma mensagem malformada ou um modelo local altere contas reais.

## Referências

[1]: https://developers.google.com/workspace/sheets/api/scopes "Google Sheets API — Escolha dos escopos"
[2]: https://developers.google.com/workspace/calendar/api/auth "Google Calendar API — Escolha dos escopos"
[3]: https://learn.microsoft.com/en-us/graph/api/resources/excel?view=graph-rest-1.0 "Microsoft Graph — Excel"
[4]: https://learn.microsoft.com/en-us/graph/api/calendar-post-events?view=graph-rest-1.0 "Microsoft Graph — Criar evento"
