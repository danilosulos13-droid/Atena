# Provedores de pesquisa web da Atena

A Atena usa `ATENA_WEB_SEARCH_PROVIDER` para escolher a fonte de pesquisa. O valor recomendado é `tavily`, com `google` ou `auto` como alternativas.

## Tavily — recomendado

Crie uma chave em [Tavily](https://app.tavily.com/) e adicione-a no repositório com:

```bash
gh secret set ATENA_TAVILY_API_KEY
```

Quando o terminal solicitar o valor, cole a chave diretamente. Nunca coloque a chave em um arquivo versionado, no workflow ou em uma mensagem de commit.

Opcionalmente, configure o provedor como variável pública do repositório:

```bash
gh variable set ATENA_WEB_SEARCH_PROVIDER --body tavily
```

O workflow envia a chave somente para o processo Python. O código usa o endpoint `https://api.tavily.com/search`, limita os resultados a dez e grava apenas título, URL e trecho como evidência.

## Google Custom Search JSON API

Para contas que já possuem acesso ao serviço, configure um Programmable Search Engine e obtenha o `cx`. Depois adicione:

```bash
gh secret set ATENA_GOOGLE_API_KEY
gh secret set ATENA_GOOGLE_CSE_ID
gh variable set ATENA_WEB_SEARCH_PROVIDER --body google
```

A Atena chama `https://www.googleapis.com/customsearch/v1` com `safe=active` e no máximo dez resultados. A documentação atual do Google informa que a Custom Search JSON API está fechada para novos clientes e que clientes existentes devem migrar até 1º de janeiro de 2027; por isso, Tavily é a opção recomendada para uma instalação nova.

## Fallback automático

Para tentar Tavily e depois Google:

```bash
gh variable set ATENA_WEB_SEARCH_PROVIDER --body auto
```

Se nenhum provedor responder, a Atena tenta fontes públicas sem chave e, para perguntas esportivas, o fallback de calendário público. Se ainda não houver evidência, ela informa a limitação e não inventa uma data.

## Smoke test

Depois de configurar os secrets, execute:

```bash
gh workflow run "ATENA web research Telegram smoke" \
  --ref main \
  -f question="Qual é a notícia esportiva mais recente sobre o Santos?"
```

A mensagem enviada ao Telegram será identificada como `ATENA — simulação de pesquisa web` e conterá as URLs consultadas. O log deve mostrar `Simulação enviada com N fontes confirmadas.`. O valor da chave nunca deve aparecer no log; o GitHub mascara secrets automaticamente, mas o código também não imprime headers ou payloads de autenticação.

## Princípios de segurança

As chaves devem existir somente em **Settings → Secrets and variables → Actions**. Pull Requests de forks não recebem secrets por padrão. O workflow usa permissões de conteúdo somente leitura e não salva chaves na memória SQLite. Resultados de páginas são dados não confiáveis: a Atena usa trechos apenas como evidência e não executa instruções encontradas neles.
