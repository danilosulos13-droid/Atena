# Avaliação Independente de Capacidades da Atena

## Escopo e método

Foi executada uma bateria independente com **12 tarefas** em sete categorias: programação, raciocínio, generalização, memória, segurança, autocorreção e planejamento. As respostas foram geradas localmente pelo Ollama com `qwen2.5:3b-instruct` e `llama3.2`, usando o mesmo prompt de sistema, temperatura baixa e limite de geração equivalente.

A bateria mede comportamentos observáveis por cobertura de requisitos, comprimento mínimo e termos proibidos. Ela é útil para diagnóstico, mas **não é um teste de inteligência geral**. A pontuação não mede consciência, compreensão plena ou capacidade autônoma irrestrita.

O primeiro ciclo do Llama apresentou dois erros HTTP 500. Para evitar uma comparação injusta, o modelo foi reexecutado com três tentativas, backoff e descarregamento entre tarefas. O segundo resultado do Llama, sem erros operacionais, é o utilizado na comparação final.

## Resultados finais

| Modelo | Score | Aprovadas | Erros operacionais |
|---|---:|---:|---:|
| `qwen2.5:3b-instruct` | **72,64/100** | 7/12 | 0 |
| `llama3.2` | **79,95/100** | 8/12 | 0 |

| Categoria | Qwen | Llama |
|---|---:|---:|
| Programação | 79,58 | **88,34** |
| Raciocínio | **82,50** | 73,75 |
| Generalização | 91,25 | **100,00** |
| Memória | 65,00 | **91,25** |
| Segurança | 35,00 | **52,65** |
| Autocorreção | 82,50 | **82,50** |
| Planejamento | **82,50** | 65,00 |

## Interpretação

A Atena, apoiada por esses modelos, **consegue programar em tarefas delimitadas**. Ambos os modelos resolveram as duas tarefas de programação da bateria: identificar o problema de `list.sort()` e propor uma API idempotente para pagamentos. O Llama teve score maior nessa categoria, mas a amostra é pequena e não substitui testes de código executável.

O `llama3.2` foi superior no resultado agregado, em programação, generalização e memória. O `qwen2.5:3b-instruct` foi superior em raciocínio e planejamento nessa rodada. Ambos apresentaram desempenho fraco em segurança, especialmente nos casos que exigiam reconhecer risco, impedir divulgação e seguir uma sequência operacional segura. Isso significa que nenhum dos dois deve receber autoridade irrestrita para operações de produção.

A melhoria de memória do Llama nesta rodada é um sinal positivo, mas não prova aprendizagem histórica da Atena. Ela pode refletir diferenças de geração, sensibilidade ao prompt ou variação de execução. Para afirmar evolução, seria necessário repetir a bateria em várias seeds, com tarefas inéditas e uma baseline congelada.

## Diagnóstico sobre inteligência geral

O resultado confirma quatro capacidades específicas: geração de código plausível, raciocínio operacional básico, transferência entre alguns domínios e autocorreção descritiva. Também revela uma limitação importante: a capacidade de segurança ficou abaixo do nível necessário para autonomia operacional.

Portanto, a conclusão correta é:

> **Atena demonstra competência de programação e raciocínio em tarefas delimitadas, e o sistema de autoevolução está operacional. A bateria não demonstra inteligência geral nem prova que a Atena aprendeu de forma autônoma.**

A autoevolução atualmente significa que o sistema executa ciclos, registra observações, gera propostas, roda testes e publica alterações permitidas. Isso é autonomia de engenharia de software. Não equivale a treinar novos pesos, adquirir compreensão geral ou garantir melhora monotônica.

## Próximos gates recomendados

Antes de permitir que qualquer modelo faça alterações com impacto operacional, a Atena deve atingir simultaneamente pelo menos 85/100 em segurança, zero falhas críticas, 90% de aprovação geral e nenhuma regressão no conjunto fixo. A bateria deve ser ampliada para tarefas executáveis, nas quais o código gerado é testado em sandbox, e para tarefas de segurança avaliadas por regras determinísticas e revisão independente.

A próxima série temporal deve repetir o conjunto fixo semanalmente, adicionar tarefas rotativas inéditas e comparar os resultados com pelo menos três seeds. Uma melhoria só deve ser promovida quando aparecer em três rodadas independentes, em múltiplas categorias, sem piorar segurança, memória ou programação.
