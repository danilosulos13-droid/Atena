# Tasker, Google Sheets e notícias do X

## Gateway HTTPS do Tasker

O endpoint está em `api/tasker_command_gateway.py`. Execute atrás de HTTPS, por exemplo com um proxy reverso ou uma plataforma que forneça TLS:

```bash
export ATENA_TASKER_HMAC_SECRET="gere-um-segredo-com-pelo-menos-32-caracteres"
export ATENA_TASKER_GATEWAY_DB="atena_evolution/tasker_gateway.sqlite3"
uvicorn api.tasker_command_gateway:app --host 127.0.0.1 --port 8787
```

A assinatura usa o corpo exato da requisição:

```text
HMAC-SHA256(secret, timestamp + "." + nonce + "." + body_bytes)
```

Headers obrigatórios:

```text
X-Atena-Timestamp
X-Atena-Nonce
X-Atena-Signature
```

Payload aceito:

```json
{"command":"agenda","device_id":"android-principal"}
```

O gateway rejeita timestamp antigo, assinatura inválida, nonce repetido e comandos fora da whitelist. O endpoint não executa texto arbitrário.

## Registrar comandos no Google Sheets

Crie uma planilha chamada `Atena — Auditoria`, com uma aba `Comandos`. Na primeira linha, use:

```text
Timestamp UTC | Device ID | Command | Status | Source | Intent | Details | Commit
```

Descubra o ID no URL da planilha:

```text
https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit
```

Configure o ambiente:

```bash
export ATENA_AUDIT_SHEETS_ENABLED=1
export ATENA_AUDIT_SHEET_ID="SPREADSHEET_ID"
export ATENA_AUDIT_SHEET_RANGE="Comandos!A:H"
export ATENA_GOOGLE_CREDENTIALS="$PWD/secrets/google/credentials.json"
export ATENA_GOOGLE_SHEETS_TOKEN="$PWD/secrets/google/sheets-token.json"
```

Na primeira gravação, o OAuth solicitará o escopo:

```text
https://www.googleapis.com/auth/spreadsheets
```

O método `spreadsheets.values.append` acrescenta uma linha depois da última linha da tabela. A auditoria é executada como tarefa de background: se o Sheets estiver temporariamente indisponível, o comando autorizado não é perdido por causa da planilha; em produção, recomenda-se adicionar uma fila local de retry.

O gateway registra comandos aceitos com timestamp, dispositivo, comando, origem, intenção e commit. Não registre tokens, senhas, conteúdo de e-mail ou dados financeiros na planilha.

## Consultar notícias do X

A Atena possui o módulo `core/x_news_research.py` e o comando:

```text
/x últimas notícias sobre inteligência artificial
```

O comando consulta o endpoint oficial de posts recentes do X, filtra retweets e português e devolve URLs de evidência. Configure o Bearer Token apenas como variável protegida:

```bash
export ATENA_X_BEARER_TOKEN="..."
```

No GitHub Actions:

```bash
gh secret set ATENA_X_BEARER_TOKEN
```

A API oficial do X exige conta de desenvolvedor, aplicativo e credenciais; o acesso e a cobrança dependem do produto/plano atual [1] [2] [3]. Não assuma que a busca é gratuita ou ilimitada. Sem token, Atena deve responder que o conector não está configurado.

Posts do X são **evidência de que alguém publicou algo**, não confirmação automática de que o conteúdo é verdadeiro. Para notícias importantes, a Atena deve comparar com fontes oficiais ou veículos independentes antes de promover uma afirmação para a memória.

## Segurança operacional

Use HTTPS real, não exponha a porta diretamente, mantenha o segredo HMAC fora do Git, limite o endpoint por rate limit e registre tentativas rejeitadas sem incluir o valor da assinatura. Para tarefas com efeitos externos, a Atena deve pedir confirmação separada.

### Referências

[1]: https://docs.x.com/x-api/introduction "X API — Introdução"
[2]: https://docs.x.com/x-api/posts/search-recent-posts "X API — Busca de posts recentes"
[3]: https://docs.x.com/x-api/getting-started/pricing "X API — Preços e créditos"
[4]: https://developers.google.com/workspace/sheets/api/scopes "Google Sheets API — Escopos"
[5]: https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/append "Google Sheets API — values.append"
