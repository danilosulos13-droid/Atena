# Atena: Google OAuth + fluxo seguro do `exe.atena`

## Slide 1 — Título
### Google Cloud, Calendar, Sheets e evolução segura no GitHub

Como conectar a Atena às ferramentas do Workspace e pesquisar melhorias sem executar código não confiável.

**Atena-IA · Guia prático**

---

## Slide 2 — O que será construído

Atena poderá consultar o Google Calendar e o Google Sheets com OAuth desktop, responder a comandos autorizados no Telegram, gerar planilhas e propor melhorias no GitHub.

**Princípio:** leitura por padrão; qualquer escrita exige confirmação explícita.

Fluxo:

`Telegram → Atena → intenção estruturada → confirmação → API autorizada`

---

## Slide 3 — Criar o projeto no Google Cloud

1. Abra o [Google Cloud Console](https://console.cloud.google.com/).
2. Crie ou selecione um projeto.
3. Ative **Google Calendar API**.
4. Ative **Google Sheets API**.
5. Ative **Google Drive API** apenas se a Atena precisar criar ou localizar arquivos.

Use um projeto separado para a Atena e mantenha credenciais fora do Git.

---

## Slide 4 — Configurar o consentimento OAuth

Em **Google Auth Platform → Branding**:

- defina o nome do aplicativo;
- informe e-mail de suporte;
- selecione **Internal** para uma organização Workspace ou **External** para uma conta Gmail/usuários externos;
- adicione a conta como test user quando a aplicação estiver em teste;
- revise a política de dados do Google.

O consentimento deve explicar claramente que a Atena acessará Calendar e Sheets.

---

## Slide 5 — Escolher o menor escopo

### Leitura inicial

```text
https://www.googleapis.com/auth/calendar.events.readonly
https://www.googleapis.com/auth/spreadsheets.readonly
```

### Escrita somente quando ativada

```text
https://www.googleapis.com/auth/calendar.events
https://www.googleapis.com/auth/drive.file
```

Evite `calendar` e `drive` amplos. Quanto menor o escopo, menor o impacto de um token comprometido.

---

## Slide 6 — Criar o OAuth Client ID desktop

1. Acesse **Google Auth Platform → Clients**.
2. Clique em **Create client**.
3. Escolha **Desktop app**.
4. Baixe o JSON.
5. Salve como `credentials.json` no ambiente local da Atena.

Nunca publique `credentials.json` ou `token.json`. Adicione ambos ao `.gitignore`.

---

## Slide 7 — Exemplo Python: autenticação

```python
SCOPES = [
    "https://www.googleapis.com/auth/calendar.events.readonly"
]

creds = None
if Path("token.json").exists():
    creds = Credentials.from_authorized_user_file(
        "token.json", SCOPES
    )

if not creds or not creds.valid:
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(
            "credentials.json", SCOPES
        )
        creds = flow.run_local_server(port=0)
```

A primeira execução abre o navegador; as seguintes usam o token renovável local.

---

## Slide 8 — Listar próximos eventos

```python
now = datetime.now(timezone.utc).isoformat()
events = service.events().list(
    calendarId="primary",
    timeMin=now,
    maxResults=10,
    singleEvents=True,
    orderBy="startTime",
).execute().get("items", [])

for event in events:
    start = event["start"].get(
        "dateTime", event["start"].get("date")
    )
    print(start, event.get("summary", "(sem título)"))
```

O exemplo completo está em `examples/google_calendar_list_events.py`.

---

## Slide 9 — Comandos da Atena para Workspace

```text
/agenda
/agendar reunião comercial em 25/08/2026 às 14:30
/criar planilha Ganhos 2026
/analisar planilha Ganhos 2026
```

Leituras podem ser executadas com OAuth de leitura. Criações, edições e cancelamentos exibem um resumo e aguardam:

```text
CONFIRMAR workspace-...
```

---

## Slide 10 — O que significa `exe.atena`

O comando inicia uma **investigação controlada** no GitHub:

```text
exe.atena pesquise projetos de IA para memória de agentes
```

A Atena coleta metadados, estrelas, atividade, licença, documentação, testes e riscos. Estrelas são apenas um sinal de interesse, não uma prova de qualidade.

---

## Slide 11 — Fluxo seguro no GitHub

```text
Pesquisar repositórios
        ↓
Fixar commit analisado
        ↓
Verificar licença, secrets e dependências
        ↓
Ler código como dado não confiável
        ↓
Testar em sandbox isolada
        ↓
Comparar benchmarks da Atena
        ↓
Gerar proposta com evidências
        ↓
Abrir Pull Request
        ↓
Revisão humana + CI
```

Atena nunca deve copiar e executar automaticamente um projeto externo.

---

## Slide 12 — Resultado e limites

O objetivo é melhorar a Atena do repositório por meio de propostas verificáveis, não alterar magicamente o modelo desta conversa.

**Garantias mínimas:**

- nenhum token no Git;
- leitura antes de escrita;
- confirmação antes de Calendar/Sheets;
- licença e commit registrados;
- testes em sandbox;
- Pull Request para toda alteração;
- merge somente após CI e revisão.

**Referências:**

[1] https://developers.google.com/workspace/calendar/api/quickstart/python
[2] https://developers.google.com/workspace/guides/create-credentials
[3] https://developers.google.com/workspace/calendar/api/v3/reference/events/list
[4] https://developers.google.com/workspace/calendar/api/auth
[5] https://developers.google.com/workspace/sheets/api/scopes
[6] https://docs.github.com/en/rest/search/search
