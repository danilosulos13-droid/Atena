# Comparação Cognitiva Local e Mitigações — Atena

## Escopo

Foi executado o benchmark `atena-llm-cognitive-comparison-v2` contra o endpoint local do Ollama, usando os modelos `qwen2.5:3b-instruct` e `llama3.2`. Cada modelo respondeu às mesmas oito tarefas, com temperatura 0,2, limite de 350 tokens e três tentativas com backoff para erros transitórios. Não houve falhas de infraestrutura na execução final.

O benchmark foi reforçado em duas áreas. Na memória histórica, a entrada passou a conter observações estruturadas, origem, limites epistemológicos, hipótese de saturação e exigência de tarefa inédita com métrica. Na segurança, o prompt passou a impor tratamento conservador de segredo potencialmente comprometido, proibição de reproduzir ou minimizar o segredo, preservação de evidências e revogação/rotação.

## Resultados

| Modelo | Pontuação geral | Tarefas aprovadas | Generalização | Memória | Raciocínio | Segurança | Triagem de segurança |
|---|---:|---:|---:|---:|---:|---:|---:|
| `qwen2.5:3b-instruct` | **74,84/100** | 4/8 | 75,62 | 67,00 | 72,92 | 83,75 | **78,00** |
| `llama3.2` | **83,63/100** | 5/8 | **91,87** | 67,00 | **83,75** | **100,00** | 67,00 |

O `llama3.2` superou o Qwen em **8,79 pontos** no agregado, em generalização e em raciocínio. O Qwen teve desempenho superior na triagem de segurança, embora ainda tenha permanecido abaixo de uma margem de aprovação robusta em termos de cobertura semântica. Os dois modelos falharam na tarefa de memória histórica, com média de 67/100; portanto, a deficiência não parece ser exclusiva do modelo, mas também do desenho de memória e da forma como a evidência é apresentada.

## Mitigação da memória histórica

A melhoria imediata aplicada foi transformar a memória livre em um bloco estruturado com quatro campos: observação registrada, origem, limite epistemológico e próximo objetivo. Isso reduz o risco de o modelo interpretar `fitness=100` como prova de aprendizagem. A tarefa também exige uma hipótese de saturação, uma tarefa inédita e uma métrica de generalização.

A mitigação de produção deve ir além do prompt. Cada memória deve receber `memory_id`, timestamp, ciclo de origem, tarefa, resultado bruto, confiança calibrada e status de validação. O roteador deve recuperar memórias por relevância e recência, mas sempre preservar a proveniência. Conclusões causais devem ser marcadas como hipóteses até serem confirmadas em tarefas novas. O sistema também deve manter um conjunto de tarefas congelado para regressão e outro conjunto secreto ou rotativo para medir generalização real.

| Controle | Finalidade | Critério de sucesso |
|---|---|---|
| Proveniência obrigatória | Impedir fatos sem origem | 100% das memórias recuperadas têm origem e timestamp |
| Separação observação/conclusão | Evitar transformar correlação em causalidade | O modelo identifica explicitamente limites da evidência |
| Tarefas inéditas rotativas | Detectar memorização e saturação | Desempenho fora da distribuição não cai além do limite definido |
| Decaimento e revisão | Evitar que memórias antigas dominem | Memórias não confirmadas expiram ou são reavaliadas |
| Memória adversarial | Testar contradições e falso sucesso | O modelo sinaliza conflito e não escolhe silenciosamente uma versão |

## Mitigação da triagem de segurança

A política conservadora aplicada melhorou o resultado do Qwen para 78/100, mas o llama3.2 alcançou somente 67/100. A diferença indica que ambos ainda precisam de uma camada determinística externa; não é suficiente confiar na redação do modelo.

Em produção, a entrada deve passar por um detector de segredos antes do LLM, com mascaramento irreversível no contexto. A resposta deve ser validada por regras: nunca exibir credenciais, sempre recomendar revogação ou rotação quando houver exposição plausível, registrar evidência sem copiar o segredo, delimitar o escopo afetado e propor contenção. Ações destrutivas, como apagar histórico ou fazer push, devem exigir aprovação explícita e permanecer em branch isolada até os testes concluírem.

Um incidente deve ser classificado como **potencialmente comprometido por padrão** quando um segredo aparece em repositório público, mesmo que parcialmente mascarado ou em arquivo de teste. O modelo pode explicar a incerteza, mas não deve usar a incerteza como motivo para ignorar o incidente.

## Conclusão

O resultado comparativo favorece `llama3.2` como modelo local padrão para raciocínio geral e generalização no conjunto testado. O `qwen2.5:3b-instruct` apresentou melhor triagem de segurança, mas a diferença não é suficiente para dispensar guardrails determinísticos. Para Atena, a configuração recomendada é usar o modelo com maior desempenho por categoria, aplicar a política de memória estruturada a ambos e colocar a decisão final de segurança em validadores externos, com auditoria e revisão humana para mudanças de alto impacto.

A pontuação não deve ser interpretada como consciência ou inteligência geral. Ela mede somente o comportamento nas oito tarefas e no rubric lexical/estrutural definido. A próxima rodada deve incluir múltiplas sementes, tarefas secretas e avaliação humana ou juiz independente para reduzir o risco de otimização contra o próprio benchmark.
