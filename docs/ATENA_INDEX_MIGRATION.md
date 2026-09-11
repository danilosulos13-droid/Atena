# Migração dos índices da Atena

## FTS5

O script `scripts/migrate_sqlite_fts5.py` cria uma tabela FTS5 external-content sobre `memory`, cria triggers de insert/update/delete e valida a contagem de linhas. A operação é idempotente.

```bash
python scripts/migrate_sqlite_fts5.py /path/atena.sqlite3 --rebuild --json
```

O índice não deve ser reconstruído enquanto houver escrita concorrente no banco. Para bancos de produção, construir uma cópia, validar as contagens e trocar o arquivo de forma controlada.

## Índice vetorial

O script `scripts/build_vector_index.py` lê embeddings float32 em lotes e grava IDs e vetores em arquivos persistentes. O vetor completo não é materializado em uma lista Python. Se `faiss` estiver instalado, também gera `vectors.faiss` com `IndexFlatIP`; caso contrário, mantém `vectors.f32.memmap` para um backend posterior.

```bash
python scripts/build_vector_index.py \
  /path/atena.sqlite3 \
  /path/indexes/atena-vectors \
  --batch-size 4096
```

O índice vetorial espera embeddings pré-calculados na coluna `memory.embedding`, em `float32`. Para 1 milhão de vetores MiniLM de 384 dimensões, o arquivo bruto terá aproximadamente 1,5 GB. O próximo passo de produção é usar float16 ou HNSW/FAISS com armazenamento e busca por IDs.

## Ordem operacional

1. Pausar o worker de escrita ou usar uma cópia consistente do SQLite.
2. Executar a migração FTS5 com `--rebuild`.
3. Validar `memory_rows == fts_rows`.
4. Construir o índice vetorial em diretório separado.
5. Validar o manifesto e uma amostra de IDs.
6. Ativar o mecanismo lexical por feature flag somente após a validação.

Os scripts não alteram a tabela `memory` nem apagam índices antigos. O BM25 Python continua disponível como fallback até a integração do caminho de consulta FTS5.
