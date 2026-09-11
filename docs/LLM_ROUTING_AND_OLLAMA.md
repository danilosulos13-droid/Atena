# Roteamento dinâmico de LLMs e teste seguro do Ollama

## Roteamento por tarefa

O módulo `core/task_routing.py` define uma preferência por categoria:

| Tipo | Preferência | Fallback |
|---|---|---|
| `simple`, `telegram` | `local` | Gemini, Anthropic |
| `private`, `local` | `local` | nenhum por padrão |
| `research`, `web_research`, `multimodal` | `gemini` | Anthropic, local |
| `code`, `github_evolution`, `architecture` | `anthropic` | Gemini, local |
| `voice` | `gemini` | local, Anthropic |
| `auto` | provider saudável | local, Gemini, Anthropic |

A chamada do roteador pode informar a categoria:

```python
response = await router.generate(
    prompt,
    context=context,
    task_type="research",
)
```

`prefer_provider` continua disponível para uma escolha explícita e tem prioridade sobre a matriz. A seleção não autoriza ações: chamadas, envio de mensagens, GitHub, Tasker e deploy continuam sujeitos às confirmações e allowlists existentes.

Os nomes remotos podem ser substituídos sem editar o código:

```bash
export GEMINI_API_KEY="..."
export ANTHROPIC_API_KEY="..."
export ATENA_GEMINI_MODEL="gemini-3.7-flash"
export ATENA_ANTHROPIC_MODEL="claude-fable-5"
```

Sobrescritas por categoria:

```bash
export ATENA_ROUTE_RESEARCH=gemini
export ATENA_ROUTE_CODE=anthropic
export ATENA_ROUTE_PRIVATE=local
```

Valores permitidos: `local`, `gemini`, `anthropic` ou `none`. Nunca coloque as chaves em código, no repositório, em logs ou em um PR.

## Instalação segura de um Qwen recente

O servidor auditado tem cerca de 3,8 GiB de RAM, não possui GPU NVIDIA detectada e já tem `qwen2.5:3b-instruct` e `llama3.2`. Comece com uma variante pequena, como `qwen3.5:2b`, e não com 9B, 27B ou maior.

### 1. Registrar o estado atual

```bash
free -h
ollama list
ollama ps
```

Pare cargas locais concorrentes antes do teste. Mantenha pelo menos aproximadamente 1 GiB de RAM disponível para o sistema.

### 2. Baixar sem iniciar uma conversa longa

```bash
ollama pull qwen3.5:2b
ollama show qwen3.5:2b
```

O download usa disco e rede; o consumo principal de RAM ocorre quando o modelo é carregado para inferência.

### 3. Testar com limite baixo

```bash
OLLAMA_NUM_PARALLEL=1 ollama run qwen3.5:2b \
  "Responda em português em no máximo três frases: qual é a diferença entre uma hipótese e uma evidência?"
```

Depois verifique:

```bash
ollama ps
free -h
```

Não rode Qwen3.5 e outros modelos grandes simultaneamente. Para liberar memória do modelo:

```bash
ollama stop qwen3.5:2b
```

### 4. Testar pela API sem deixar uma sessão permanente

```bash
curl --fail-with-body --silent --show-error http://127.0.0.1:11434/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.5:2b","stream":false,"keep_alive":0,"options":{"num_ctx":4096,"num_predict":256},"messages":[{"role":"user","content":"Responda em português: liste dois cuidados para uma ação sensível no Android."}]}'
```

`keep_alive: 0` pede que o modelo seja descarregado após a resposta. `num_ctx` e `num_predict` menores reduzem o uso de memória e o tempo de teste.

### 5. Comparar antes de trocar o padrão

```bash
export ATENA_LOCAL_LLM_MODEL=qwen3.5:2b
PYTHONPATH="$PWD" python scripts/llm_cognitive_evaluation.py \
  --models qwen2.5:3b-instruct qwen3.5:2b llama3.2
```

Se o script do benchmark tiver parâmetros diferentes na versão instalada, consulte:

```bash
PYTHONPATH="$PWD" python scripts/llm_cognitive_evaluation.py --help
```

Compare factualidade, português, código, memória histórica, segurança e tempo de resposta. Não use apenas uma resposta ou uma pontuação isolada.

### 6. Reverter sem desinstalar o modelo atual

Para voltar ao modelo existente:

```bash
export ATENA_LOCAL_LLM_MODEL=qwen2.5:3b-instruct
sudo systemctl restart atena-telegram.service
```

Se o novo modelo for pesado ou não for mais necessário:

```bash
ollama rm qwen3.5:2b
```

A mudança do modelo padrão deve passar por benchmark e Pull Request. O download não deve ser feito automaticamente pelo ciclo de autoevolução.
