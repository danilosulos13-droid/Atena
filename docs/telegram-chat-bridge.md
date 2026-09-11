# Ponte de conversa Telegram da Atena

O script `scripts/atena_telegram_chat.py` mantém uma conversa autorizada entre o Telegram e o modelo local da Atena via Ollama. Ele usa long polling, mantém um histórico curto por chat, oferece comandos operacionais e não executa shell, código recebido ou ações destrutivas a partir de mensagens.

> Esta versão conecta o Telegram ao **Ollama local da Atena**. Ela não conecta diretamente esta sessão do agente Manus ao Telegram. Uma conexão direta com o agente Manus exigiria uma integração adicional com a API Manus e uma chave própria, além de um serviço persistente.

## Configuração

Defina as variáveis no ambiente do processo, nunca no código:

```bash
export ATENA_ROOT=/caminho/para/Atena-IA
export ATENA_TELEGRAM_BOT_TOKEN='token-do-bot'
export ATENA_TELEGRAM_CHAT_ID='id-do-chat'
export ATENA_LOCAL_MODEL='qwen2.5:3b-instruct'
export ATENA_OLLAMA_CHAT_URL='http://127.0.0.1:11434/api/chat'
```

O chat ID funciona como uma allowlist. Mensagens de outros chats são ignoradas. O token não deve ser publicado no Git, em issues ou em mensagens do Telegram.

## Execução local

Com o Ollama ativo e o modelo instalado, execute:

```bash
cd /caminho/para/Atena-IA
python3 scripts/atena_telegram_chat.py
```

Para fazer somente uma leitura de updates e encerrar, use:

```bash
python3 scripts/atena_telegram_chat.py --once
```

O processo precisa permanecer ativo para responder rapidamente. O GitHub Actions continua adequado para os ciclos periódicos e notificações. O workflow da Atena agora também inicia esta ponte durante a janela de cinco minutos do ciclo, atende mensagens autorizadas nesse intervalo e encerra o listener ao terminar. Fora dessa janela, o runner é temporário e não mantém polling 24 horas; para atendimento contínuo, é necessário um processo persistente separado.

## Comandos disponíveis

| Comando | Função |
|---|---|
| `/start` | Inicializa a conversa |
| `/help` | Exibe a ajuda |
| `/status` | Mostra estado da memória, última proposta e modelo |
| `/aprendizagens` | Resume a última proposta de aprendizagem |
| `/capabilities` | Mostra o total de capacidades catalogadas e executáveis |
| `/modelo` | Informa o backend e modelo local |
| `/reset` | Remove o histórico curto daquela conversa |

Mensagens comuns são encaminhadas ao modelo local. A sessão mantém apenas uma janela curta de contexto em `data/telegram_sessions.json`; esse arquivo deve permanecer privado e fora de commits.

## Operação contínua

Para uso contínuo, execute o script em uma máquina que permaneça ligada, com reinício automático e variáveis de ambiente protegidas. Em produção, prefira um serviço persistente com logs, health check, limitação de recursos e backup do arquivo de sessão. Não use o workflow de CI como substituto de um serviço 24/7.

A ponte foi desenhada para responder somente ao chat autorizado, redigir e limitar mensagens, usar timeout nas chamadas ao Ollama, tentar novamente falhas transitórias do Telegram e recusar a inicialização quando o token ou o chat ID estiverem ausentes.
