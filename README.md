# Atena Especialista

[![CI principal](https://github.com/danilosulos13-droid/Atena/actions/workflows/atena-ci-and-update.yml/badge.svg)](https://github.com/danilosulos13-droid/Atena/actions/workflows/atena-ci-and-update.yml)
[![Licença MIT](https://img.shields.io/badge/licença-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10--3.12-blue.svg)](https://www.python.org/downloads/)

> **Atena Especialista** é uma assistente experimental com texto, voz, memória persistente e ciclos controlados de aprendizagem. Ela pode pesquisar um tema, registrar evidências, resumir o que foi confirmado e responder pelo Telegram com fontes quando o fluxo de pesquisa estiver habilitado.

O projeto é desenvolvido em Python e integra modelos locais via Ollama, provedores remotos opcionais, SQLite, pesquisa web, Telegram, Piper TTS e workflows do GitHub Actions.

## Status real

Atena é um **protótipo avançado**, não um sistema AGI comprovado. Os ciclos autônomos geram observações, propostas e memória auditável; eles não transformam automaticamente qualquer texto recebido em conhecimento verdadeiro nem fazem autoalterações irrestritas no código.

As capacidades atualmente verificadas no repositório são:

- conversa local pelo terminal e pelo Telegram;
- modelo local `qwen2.5:3b-instruct` via Ollama no workflow principal;
- memória episódica e base de conhecimento em SQLite;
- pesquisas com fontes públicas e relatórios auditáveis;
- geração de propostas de aprendizagem;
- gates de qualidade, testes e sandbox para reduzir regressões;
- respostas de texto e mensagens de voz em português pelo Piper;
- ciclos periódicos no GitHub Actions;
- allowlist de chats do Telegram e registro de auditoria para ferramentas.

Atena ainda **não** oferece, por padrão, atendimento Telegram 24 horas em um servidor permanente, isolamento completo por cliente, ingestão de gigabytes em produção, garantia de precisão profissional ou aprendizagem autônoma sem supervisão.

## O que ela pode fazer

### Assistente especialista

O usuário pode enviar um tema ou uma pergunta. A Atena pode pesquisar, organizar o material, separar evidências de hipóteses e registrar uma proposta para os próximos ciclos. A especialização deve ser tratada como uma combinação de **memória recuperável, fontes e instruções**, não como alteração automática dos pesos do modelo.

Um uso recomendado é:

```text
Quero que você estude manutenção de painéis solares para me ajudar a interpretar manuais e responder dúvidas técnicas.
```

Para uso empresarial, a memória deve ser separada por usuário ou organização antes de receber dados confidenciais. Essa separação multi-tenant ainda é um item de produção, não uma promessa do protótipo atual.

### Telegram

A ponte `scripts/atena_telegram_chat.py` usa long polling e responde apenas a chats presentes em `ATENA_TELEGRAM_CHAT_ID`. Mensagens de outros chats são ignoradas.

Comandos principais:

| Comando | Função |
|---|---|
| `/start` | Inicia ou apresenta a conversa |
| `/help` | Mostra ajuda |
| `/status` | Informa o estado resumido da memória e do modelo |
| `/aprendizagens` | Mostra a última aprendizagem em texto |
| `/aprendizagens audio` | Gera e envia a última aprendizagem como voz |
| `/modelo` | Mostra o backend e o modelo local |
| `/capabilities` | Lista capacidades catalogadas |
| `/reset` | Remove o histórico curto daquele chat |
| `/pesquisar <tema>` | Enfileira uma pesquisa para o próximo ciclo |

O listener local é um processo contínuo. O workflow do GitHub Actions mantém uma janela temporária de polling durante o ciclo; isso **não** equivale a um bot 24/7.

### Voz

A voz usa Piper e a configuração `pt_BR-faber-medium` no workflow de aprendizagem. O resumo textual é enviado primeiro e o áudio é enviado em seguida quando `ATENA_TELEGRAM_SEND_VOICE=1`.

Para usar localmente:

```bash
export ATENA_PIPER_BIN=piper
export ATENA_PIPER_MODEL=/caminho/para/pt_BR-faber-medium.onnx
export ATENA_PIPER_CONFIG=/caminho/para/pt_BR-faber-medium.onnx.json
```

A geração ocorre localmente, o arquivo de áudio é enviado ao chat autorizado e removido depois do envio. Consulte [`docs/LEARNING_AUDIO.md`](docs/LEARNING_AUDIO.md) para detalhes.

## Como a aprendizagem funciona

O ciclo autônomo, em linhas gerais, executa estas etapas:

1. restaura o runtime de memória e os módulos permitidos;
2. inicia o modelo local e os serviços necessários;
3. pesquisa ou processa sinais conforme a configuração do ciclo;
4. gera observações, riscos, evidências e propostas;
5. valida memória, testes, compilação e gates de qualidade;
6. publica apenas o estado permitido na branch de autoevolução;
7. envia um resumo textual e, quando habilitado, áudio pelo Telegram;
8. arquiva relatórios e logs para auditoria.

Uma proposta autônoma pode ser rejeitada por falta de evidência, alteração perigosa, ausência de testes, regressão ou falha de infraestrutura. O workflow de promoção não deve ser interpretado como prova de que toda conclusão da Atena está correta.

## Arquitetura resumida

```text
Telegram / Terminal
        |
        v
Roteador de tarefas e allowlists
        |
        +--> Ollama local: qwen2.5:3b-instruct
        +--> Provedores remotos opcionais
        +--> Pesquisa web e fontes públicas
        |
        v
Memória SQLite + relatórios + histórico curto
        |
        v
Ciclo de aprendizagem e gates determinísticos
        |
        +--> Texto Telegram
        +--> Piper TTS -> áudio Telegram
        +--> Proposta / artefato / PR
```

Os pesos do modelo não ficam versionados no repositório. O workflow principal instala Ollama e executa `ollama pull qwen2.5:3b-instruct` no runner. A memória persistida e os pesos do modelo são componentes diferentes: documentos e fatos devem ser armazenados em uma camada RAG escalável, não incorporados indiscriminadamente aos pesos.

## Instalação local

### Requisitos

- Python `>=3.10,<3.13`;
- Git;
- Ollama para conversa local;
- Piper e uma voz ONNX para áudio local;
- dependências do arquivo de requisitos adequado ao uso;
- Playwright somente para recursos de navegador;
- hardware suficiente para o modelo escolhido.

### Linux/macOS

```bash
git clone https://github.com/danilosulos13-droid/Atena.git
cd Atena
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r setup/requirements-pinned.txt
python -m pip install -r setup/requirements-dev.txt
```

Para instalar todos os extras conhecidos:

```bash
python -m pip install -r setup/requirements-all.txt
```

Para conferir o ambiente:

```bash
bash atena --doctor
python -m pytest -q
```

O bootstrap portátil também está disponível:

```bash
python3 setup/bootstrap_portable.py --full-auto
bash atena assistant
```

Use `--skip-system` quando não houver permissão para instalar pacotes do sistema. Recursos opcionais podem exigir os arquivos `setup/requirements-browser.txt`, `setup/requirements-voice.txt`, `setup/requirements-video.txt` ou `setup/requirements-math.txt`.

### Ollama

Instale o Ollama conforme a documentação oficial e prepare o modelo usado pela configuração atual:

```bash
ollama serve
ollama pull qwen2.5:3b-instruct
```

A configuração padrão do chat local é:

```bash
export ATENA_LOCAL_MODEL=qwen2.5:3b-instruct
export ATENA_OLLAMA_CHAT_URL=http://127.0.0.1:11434/api/chat
```

Não troque o modelo padrão em produção apenas por download. Compare factualidade, português, código, memória, segurança, latência e consumo de RAM; depois faça a mudança por Pull Request.

## Configuração do Telegram

Nunca coloque token ou chat ID no código, no Git, em issues ou em mensagens públicas.

```bash
export ATENA_ROOT="$PWD"
export ATENA_TELEGRAM_BOT_TOKEN='token-do-bot'
export ATENA_TELEGRAM_CHAT_ID='id-do-chat-autorizado'
export ATENA_LOCAL_MODEL='qwen2.5:3b-instruct'
```

O `ATENA_TELEGRAM_CHAT_ID` é uma allowlist. Ele deve ser o ID do usuário, grupo ou canal que receberá as mensagens, não o ID do próprio bot. O usuário precisa iniciar a conversa com o bot antes de receber mensagens privadas.

Execução local:

```bash
python3 scripts/atena_telegram_chat.py
```

Para uma única leitura de updates:

```bash
python3 scripts/atena_telegram_chat.py --once
```

Para atendimento contínuo, mantenha esse processo em um serviço persistente com reinício automático, logs, health check, limites de recursos e backup da sessão. Não use GitHub Actions como substituto de um serviço 24/7.

## Comandos do launcher

```bash
bash atena --help
bash atena --doctor
bash atena assistant
bash atena research "pergunta com fontes"
bash atena --auto
bash atena self-test
bash atena release-gate
bash atena metrics
bash atena model-download
```

O launcher também expõe comandos experimentais de benchmark, treinamento em background, varredura GitHub e evolução. Comandos experimentais devem ser executados primeiro em branch e ambiente isolados.

## Pesquisa com fontes

O fluxo de pesquisa pode consultar fontes públicas e gravar relatórios em `analysis_reports/research/`. Para síntese remota, configure o provedor correspondente; sem chave, a pesquisa pode retornar resultados e trechos sem inventar uma conclusão.

```bash
bash atena research "quais são os avanços recentes em agentes de IA"
```

Provedores opcionais incluem variáveis como `OPENAI_API_KEY`, `ATENA_TAVILY_API_KEY`, `ATENA_GOOGLE_API_KEY`, `ATENA_GOOGLE_CSE_ID` e `ATENA_BRAVE_SEARCH_API_KEY`. Segredos devem permanecer fora do repositório.

## Memória e ingestão de documentos

Hoje o projeto usa SQLite e módulos de memória locais. Isso é suficiente para prototipagem, testes e coleções pequenas, mas não deve ser descrito como armazenamento empresarial de gigabytes.

Para uma edição oficial, a evolução recomendada é:

- armazenamento dos documentos originais em objeto persistente;
- divisão em chunks com hash e deduplicação;
- embeddings gerados em lotes;
- índice vetorial persistente;
- filtros por usuário, organização, fonte e versão;
- citações e rastreabilidade por trecho;
- exclusão e backup por tenant;
- processamento em streaming, sem carregar arquivos inteiros na RAM.

Atena pode ser especializada por assunto usando RAG sem alterar os pesos do modelo a cada mensagem. Fine-tuning/QLoRA deve ser reservado para dados estáveis, curados e avaliados, com rollback.

## Workflows e operação

Os workflows principais incluem:

- `atena-ci-and-update.yml`: testes, ciclo de aprendizagem e notificações;
- `atena-telegram-listener.yml`: janela temporária de polling do Telegram;
- `atena-memory-health.yml`: saúde e rotação da memória;
- `rotating-regression.yml`: regressão rotativa;
- `selfmod-sandbox.yml`: validação isolada de auto-modificação;
- `atena-qlora-1.5b.yml`: pipeline experimental de treinamento;
- `sync-memory-supabase.yml`: sincronização opcional da memória aprovada;
- `daily-news-digest.yml`: digest periódico de notícias;
- `auto-promote-main.yml`: promoção controlada quando os gates permitem.

Os workflows usam secrets do GitHub para Telegram e provedores externos. O diagnóstico e os logs devem mascarar tokens e nunca imprimir valores secretos.

## Segurança e limites

Atena foi desenhada para preferir ações controladas, mas não deve ser tratada como autoridade autônoma em decisões médicas, jurídicas, financeiras, governamentais ou de segurança física.

Antes de produção, implemente ou confirme:

- isolamento de memória por usuário/empresa;
- autorização por ação, não apenas por chat;
- aprovação humana para operações sensíveis;
- limites de custo, tempo e requisições;
- proteção contra prompt injection e conteúdo malicioso;
- auditoria e retenção de logs;
- backups testados e restauração;
- atualização e rollback de modelos;
- política de privacidade e tratamento de dados conforme a LGPD;
- monitoramento 24/7 em infraestrutura persistente.

O sistema pode pesquisar e propor uma evolução; isso não significa que uma proposta deva ser aplicada sem revisão. Ações externas, alterações de código, deploys e comandos destrutivos precisam continuar atrás de allowlists e confirmação apropriada.

## Testes

Execute a suíte completa no ambiente virtual:

```bash
python -m pytest -q
```

Validações úteis:

```bash
python -m compileall -q api core modules scripts
bash atena --doctor
bash atena self-test
git diff --check
```

Mudanças em workflows devem ser validadas com um parser YAML e, quando possível, por uma execução real em branch. Nunca use um workflow de produção como único teste de um novo modelo ou integração.

## Roadmap para uma Atena oficial

### Próximo ciclo

- serviço Telegram persistente, separado dos runners de CI;
- memória vetorial persistente e ingestão em streaming;
- isolamento por usuário/empresa;
- painel de saúde, custos, fontes e aprovações;
- testes de voz e pesquisa no CI;
- documentação de instalação reproduzível.

### Depois da validação com usuários

- planos e limites por organização;
- backup e restauração self-service;
- observabilidade e alertas;
- processo de incidentes e suporte;
- revisão jurídica, marca, termos e política de privacidade;
- fine-tuning somente com dataset curado e benchmark de regressão.

## Licença

Este projeto é distribuído sob a licença MIT. Consulte [`LICENSE`](LICENSE). A licença do código não substitui as licenças dos modelos, vozes, fontes, APIs ou documentos processados.

## Documentação complementar

- [`docs/telegram-chat-bridge.md`](docs/telegram-chat-bridge.md): ponte Telegram e operação contínua;
- [`docs/LEARNING_AUDIO.md`](docs/LEARNING_AUDIO.md): geração e envio de voz;
- [`docs/LLM_ROUTING_AND_OLLAMA.md`](docs/LLM_ROUTING_AND_OLLAMA.md): roteamento e modelos locais;
- [`docs/MASS_INGESTION_REPORT.md`](docs/MASS_INGESTION_REPORT.md): relatório histórico de ingestão, não garantia de capacidade de produção;
- [`docs/production_essentials_recommendations.md`](docs/production_essentials_recommendations.md): recomendações de produção.

## Contribuição

Abra uma issue descrevendo o problema e incluindo passos reproduzíveis. Para alterações de código, use uma branch, adicione testes, execute a suíte local e abra um Pull Request. Não inclua tokens, bases privadas, sessões do Telegram, documentos confidenciais ou pesos de modelos no commit.

O repositório oficial desta documentação é:

<https://github.com/danilosulos13-droid/Atena>
