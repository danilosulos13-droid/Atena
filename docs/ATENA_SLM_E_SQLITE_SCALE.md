# SLM da Atena e escala do SQLite

## Decisão recomendada

A Atena deve usar um **SLM local como componente auxiliar**, e não como substituto do RAG. O modelo pequeno deve classificar a intenção da pergunta, reranquear os candidatos recuperados, comprimir o contexto e verificar se as citações estão presentes. A resposta final continua dependente das evidências recuperadas e dos gates de segurança da Atena.

O perfil inicial está em [`config/atena_slm_profile.json`](../config/atena_slm_profile.json). O modelo-base proposto é `Qwen/Qwen2.5-1.5B-Instruct`, treinado por QLoRA em 4 bits. O repositório já contém o fluxo de treinamento em `scripts/train_qlora.py` e o workflow GPU em `atena-qlora-1.5b.yml`.

## Fluxo do SLM

1. O RAG recupera os candidatos usando BM25 e embeddings.
2. O SLM recebe somente a pergunta, os candidatos e a política ativa.
3. O SLM devolve intenção, citações selecionadas, contexto comprimido e flags de segurança.
4. A Atena rejeita qualquer saída sem citação quando a pergunta exigir evidência.
5. A Atena usa o LLM principal ou uma resposta extrativa baseada nos candidatos.
6. Se o SLM exceder 1,5 segundo, falhar ou produzir schema inválido, o sistema retorna os resultados originais do RAG.

O SLM deve operar inicialmente em **modo advisory-only**. Ele não deve executar ferramentas, modificar memória, enviar mensagens, alterar credenciais ou publicar resultados.

## Dataset

O dataset deve combinar exemplos curados da Atena, consultas reais anonimizadas, casos de segurança e exemplos negativos. Cada registro precisa manter `source_url`, `citation` e a separação entre pergunta, evidência e decisão. Segredos devem ser redigidos antes da geração do dataset.

As classes mínimas são `ai`, `security`, `hybrid` e `general`. Para reranking, os exemplos devem indicar quais citações são relevantes. Para compressão, a saída deve usar apenas fatos presentes nos candidatos. O holdout deve conter consultas de prompt injection, conflito entre fontes, ausência de evidência e documentos irrelevantes.

## Treinamento e promoção

O treinamento inicial deve usar uma época, comprimento máximo de 512 tokens, batch físico 1, acumulação de gradiente 8, learning rate de `2e-4` e LoRA nos módulos de atenção `q_proj`, `k_proj`, `v_proj` e `o_proj`. O adaptador deve ser salvo separadamente do modelo-base.

Nenhum candidato deve ser promovido apenas porque a perda de treinamento diminuiu. A promoção exige melhora mínima de 2% no holdout, ausência de regressão de segurança, citações válidas e artefato de rollback. O workflow GPU existente já contém preflight CUDA, validação no holdout e conversão para GGUF.

## Mitigação do `database is locked`

A implementação do RAG foi ajustada para usar WAL, `busy_timeout` de 30 segundos, `check_same_thread=False`, um lock de escrita por processo e retry exponencial para operações que retornam `locked` ou `busy`. As atualizações de `access_count` e os eventos de auditoria agora passam pelo mesmo caminho protegido.

Essa mudança reduz contenção entre threads, mas SQLite continua tendo um único escritor efetivo. Portanto, a solução de longo prazo é retirar a auditoria e os contadores do caminho crítico da consulta. O desenho recomendado é uma fila em memória limitada, com um único escritor de auditoria em background, descarte controlado de métricas não essenciais e flush periódico. A evidência de auditoria obrigatória deve ter política de durabilidade explícita; ela não deve ser descartada silenciosamente.

Para múltiplos processos, o lock Python não é suficiente. Nesse cenário, mantenha WAL e retry, reduza o tempo das transações, evite DDL durante tráfego e considere migrar a escrita de auditoria para PostgreSQL ou outro armazenamento com concorrência de escrita apropriada.

## Validação

O teste de regressão deve incluir consultas simultâneas em 4, 8, 16, 32 e 64 workers. Os critérios sugeridos são taxa de sucesso de 100%, zero `database is locked`, p95 dentro do SLO definido e preservação do número de eventos de auditoria. O teste deve ser executado com o índice real da Atena, não apenas com um fixture reduzido.

## Próximos passos

O próximo passo de baixo risco é rodar novamente o benchmark de 1.000 consultas após a mitigação e comparar os resultados com o baseline. Em paralelo, deve ser criado o dataset de destilação do SLM e executado o workflow QLoRA somente em runner GPU disponível. O modelo não deve ser conectado ao caminho de ações externas antes da validação do holdout.
