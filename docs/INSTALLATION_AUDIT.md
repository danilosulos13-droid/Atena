# Auditoria de instalação da Atena

## Resultado executivo

O caminho principal da Atena importa e passa pelo healthcheck após a instalação do conjunto pinado e de desenvolvimento. O núcleo de memória, identidade, sensemaking, recuperação e grafo está operacional no ambiente Python 3.12.

A Atena não é um único pacote monolítico. O repositório contém perfis opcionais para voz, ML/embeddings, dashboards, integrações Google, Redis, Android e serviços externos. Instalar literalmente todos os módulos seria desnecessário e poderia introduzir dependências pesadas ou específicas de sistema.

## Instalação recomendada

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r setup/requirements-pinned.txt
python -m pip install -r setup/requirements-dev.txt
```

O `setup/requirements-pinned.txt` agora inclui, além do núcleo anterior, `pydantic-settings`, `jsonschema`, `redis`, `openai`, `anthropic` e as bibliotecas de autenticação/API do Google usadas por Calendar e Sheets.

## Componentes opcionais

| Componente | Instalação/condição | Estado no sandbox |
|---|---|---|
| Ollama | Binário + modelos locais | Instalado; modelos Qwen e Llama disponíveis anteriormente |
| Playwright | Pacote Python + `playwright install chromium` | Chromium instalado; usar somente quando o agente de navegador for necessário |
| Voz | `setup/requirements-voice.txt`, Piper e modelos de voz | FFmpeg disponível; Piper ainda não instalado |
| ML/embeddings | `setup/requirements-ultimate.txt` ou extras ML | Torch, FAISS e sentence-transformers não são necessários para o núcleo |
| Google Workspace | Pacotes agora declarados; OAuth e `credentials.json` continuam necessários | Bibliotecas instaladas; credenciais não são armazenadas no Git |
| Telegram | A integração atual usa HTTP com `requests`/`aiohttp` | Não precisa de `python-telegram-bot`; requer secrets e chat autorizado |
| Tasker/Android | Aplicativo Tasker, dispositivo Android e endpoint HTTPS | Não pode ser instalado no sandbox; ações reais exigem confirmação |
| Redis | Pacote Python instalado; servidor Redis é externo | Nenhum servidor Redis local foi iniciado |

## Dependências ausentes que não devem ser instaladas automaticamente

O inventário estático encontra imports de módulos opcionais, experimentais, específicos de Windows/macOS ou módulos internos históricos. Exemplos: `torch`, `transformers`, `faiss`, `faster_whisper`, `openwakeword`, `silero_vad`, `sounddevice`, `pyautogui`, `pycaw`, `win10toast`, `comtypes`, `Xlib`, `celery`, `streamlit` e `hnswlib`.

Esses módulos não são necessários para executar o núcleo testado. Devem ser instalados somente quando o recurso correspondente for ativado, preferencialmente em perfil separado para não aumentar o risco de incompatibilidade ou OOM.

## Conflitos preexistentes

`pip check` ainda identifica conflitos no ambiente global:

```text
pyhanko requer cryptography>=48.0.0, mas cryptography 42.0.8 está instalada
pyhanko-certvalidator requer cryptography>=48.0.0, mas cryptography 42.0.8 está instalada
svglib requer lxml>=6.0.0, mas lxml 5.4.0 está instalada
```

Esses conflitos pertencem a pacotes globais de documentos e não foram alterados automaticamente, pois atualizar `cryptography` ou `lxml` pode afetar outros componentes do sandbox. Em uma instalação limpa, use o `.venv` recomendado.

## Verificação

```bash
PYTHONPATH="$PWD" python scripts/memory_identity_healthcheck.py
PYTHONPATH="$PWD" pytest -q --disable-warnings
python -m pip check
```

A auditoria não executa Telegram, Tasker, chamadas, mensagens, GitHub push, exclusões nem credenciais externas. Segredos devem permanecer em variáveis de ambiente ou GitHub Secrets.
