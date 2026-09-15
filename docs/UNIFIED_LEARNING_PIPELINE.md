# Pipeline Unificado de Aprendizagem da Atena

O workflow `ATENA Unified Learning Pipeline` encadeia pesquisa web, proveniência, memória episódica, dataset determinístico, treinamento opcional, avaliação e notificação. O fluxo não promove pesos sem um gate de validação aprovado.

## Execução

No GitHub Actions, execute manualmente o workflow `atena-unified-learning.yml` e escolha `training_mode`:

- `none`: pesquisa, memória, dataset, integridade e artefatos, sem treinar pesos;
- `lora`: executa o ciclo LoRA existente e registra avaliação/promoção somente quando o avaliador aprovar;
- `qlora`: exige runner self-hosted com labels `linux`, `x64`, `gpu`, `nvidia`, treina o adaptador, valida holdout e publica o candidato como artefato.

O tema da pesquisa e o limite de páginas também são entradas manuais. O padrão é conservador para permitir validar o pipeline antes de consumir GPU.

## Contrato de evidência

Cada item web precisa ter URL HTTP(S) e pelo menos 80 caracteres de texto. O adaptador `scripts/unified_learning_pipeline.py` grava a evidência como episódio `observation` com `source_type=external_source`, `source_url`, método de verificação, hash de conteúdo e status `supported`. O mesmo item gera uma experiência com `memory_id`, `source_url`, prompt e resposta; duplicatas são ignoradas por URL/hash.

A cadeia SQLite é verificada antes de o job avançar. O construtor de dataset usa divisão determinística e exige holdout mínimo; datasets pequenos falham de propósito em vez de treinar sem avaliação.

## Promoção e Telegram

No modo LoRA, a promoção continua delegada ao avaliador existente (`core.model_candidate_evaluator`). No modo QLoRA, o arquivo `adapter_model.safetensors` e o holdout precisam existir e passar a melhoria mínima antes de qualquer publicação do candidato. O workflow não executa deploy SSH automaticamente.

Após o ciclo, o relatório unificado pode ser enviado pelo notificador Telegram configurado. A integração deve usar `ATENA_TELEGRAM_BOT_TOKEN` e `ATENA_TELEGRAM_CHAT_ID` como secrets; nenhum segredo é gravado na memória ou no artefato.

## Testes locais

```bash
source .venv/bin/activate
pytest -q tests/unit/test_unified_learning_pipeline.py
python scripts/memory_identity_healthcheck.py
python -m py_compile scripts/unified_learning_pipeline.py
```

Para testar sem alterar produção, use um banco e experiências temporários:

```bash
python scripts/unified_learning_pipeline.py ingest \
  --input /tmp/research.jsonl \
  --db /tmp/atena-memory.sqlite3 \
  --experiences /tmp/atena-experiences.jsonl \
  --report /tmp/atena-ingest-report.json
```
