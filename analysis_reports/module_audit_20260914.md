# Auditoria de módulos da Atena — 14/09/2026

## Resumo executivo

A Atena possui um núcleo amplo de memória, pesquisa, planejamento, benchmarks, evolução, CSI Wi-Fi e observação da Terra. A auditoria distinguiu módulos executáveis de demonstrações, simuladores e integrações opcionais. O doctor do projeto terminou saudável. O smoke suite do Codex executou **106/106 módulos com sucesso**. O healthcheck principal inicialmente falhava por um problema de caminho de importação ao ser chamado diretamente; esse defeito foi corrigido e o healthcheck passou com todos os módulos listados como `ok`.

## Capacidades executadas

| Área | Execução | Resultado | Natureza |
|---|---|---|---|
| Diagnóstico | `atena --doctor --json` | Saudável | Local, somente leitura |
| Smoke suite | `protocols/atena_codex.py --smoke` | 106/106 ok | Testes locais |
| Saúde do núcleo | `scripts/main_healthcheck.py` | Todos os imports ok | Diagnóstico local |
| CSI Wi-Fi | `test_synthetic_csi_presence.py` | `possible_presence` | Dados sintéticos |
| Benchmark | `novel_generalization_cases.py` | 5 tarefas, 5 famílias | Held-out em relação ao treino |
| Satélite | `satellite_capability` + consulta STAC construída | 6 fontes, somente leitura | Plano sem chamada externa |
| Agente unificado | `default_cycle` | `accepted` | Observação local, sem ferramenta externa |

## Correção aplicada

`scripts/main_healthcheck.py` não encontrava o pacote `core` quando executado diretamente a partir de `scripts/`. O script agora insere a raiz do repositório no `sys.path` antes de importar os módulos. Isso não altera os módulos de produção nem habilita autoalteração.

## Classificação de capacidades

A interpretação de CSI continua limitada a dados fornecidos pelo chamador. O resultado `possible_presence` é uma inferência experimental sobre o sinal; não é identificação de pessoa nem prova de ocupação real. A capacidade satelital constrói e consulta catálogos de metadados, mas não controla satélites. O ciclo unificado executado usou apenas a ferramenta local `observe_objective`, portanto não realizou ações externas.

O registro de capacidades confirma que a descoberta é estática e que a execução de uma capacidade exige uma allowlist explícita em `ATENA_CAPABILITY_ALLOWLIST`. Os defaults de segurança observados foram `ALLOW_DEEP_SELF_MOD=false`, `ALLOW_CHECKER_EVOLVE=false`, sem configuração de deploy automático.

## Limitações e próximos passos

O healthcheck de integração geral continua podendo classificar o sistema como `degraded` quando conectores opcionais não estão configurados. Isso não foi tratado como falha de código. Não foram executados Telegram, chamadas de rede, downloads, publicação externa adicional ou ciclos de autoalteração.

A melhoria prioritária recomendada é manter o healthcheck executável diretamente, expandir testes de contrato para cada integração opcional e preservar a separação entre módulos de demonstração, simuladores e capacidades com dados reais.
