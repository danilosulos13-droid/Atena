# Observação da Terra e benchmark de generalização

## Capacidade satelital

A Atena agora possui uma capacidade de pesquisa de observação da Terra em `core/satellite_observation.py`. O módulo consulta metadados de catálogos STAC e NASA CMR, preserva a proveniência e limita a operação a leitura. Ele não controla satélites, envia comandos, baixa imagens por padrão ou declara que uma imagem prova algo sem validação.

As fontes catalogadas estão em `config/satellite_sources.json`. O catálogo inclui NASA Earthdata CMR, NASA GIBS, Copernicus Data Space, Earth Search STAC e dois catálogos comunitários do GitHub. Fontes comunitárias são referências de métodos e precisam ser validadas contra documentação oficial ou publicações primárias.

Exemplo local para construir uma consulta STAC sem executá-la:

```python
from core.satellite_observation import build_stac_search

endpoint, payload = build_stac_search(
    bbox=(-45.0, -23.0, -44.0, -22.0),
    datetime_range="2026-01-01/2026-01-31",
    collections=["sentinel-2-l2a"],
)
```

A Atena reconhece perguntas sobre satélite, Sentinel, Landsat, STAC e sensoriamento remoto como o domínio `observacao_terra` e prioriza NASA, Copernicus e catálogos de observação da Terra.

## Benchmark no GitHub Actions

O workflow gera cinco casos held-out com `scripts/novel_generalization_cases.py`. O executor existente `scripts/run_rotating_benchmark_ollama.py` roda o mesmo conjunto contra o modelo baseline e o candidato. O avaliador `scripts/evaluate_novel_generalization.py` calcula score médio, taxa de aprovação, falhas críticas, ganho de tarefas inéditas e taxa de regressão.

Para executar as chamadas automaticamente, configure os seguintes secrets no repositório:

| Secret | Conteúdo |
|---|---|
| `ATENA_BENCHMARK_OLLAMA_HOST` | URL de um endpoint Ollama compatível e acessível pelo runner |
| `ATENA_BENCHMARK_BASELINE_MODEL` | Nome do modelo baseline |
| `ATENA_BENCHMARK_CANDIDATE_MODEL` | Nome do modelo candidato ou adaptador servido |

Sem esses secrets, o workflow gera um relatório `blocked` e não falha o treinamento. Isso evita fingir que o benchmark foi executado.

A decisão atual é `promote` quando não existem falhas de infraestrutura ou críticas, o ganho médio é de pelo menos dois pontos percentuais e a taxa de regressão fica abaixo de 5%. O relatório é publicado no artefato do workflow. A promoção real do modelo deve continuar subordinada aos gates já existentes; o benchmark não deve substituir a avaliação de holdout.

## Projetos e documentação usados como referência

- NASA Earthdata CMR: `https://cmr.earthdata.nasa.gov/search/granules.json`.
- NASA GIBS: `https://www.earthdata.nasa.gov/data/tools/gibs`.
- Copernicus Data Space: `https://dataspace.copernicus.eu/analyse/apis/sentinel-hub`.
- Earth Search STAC: `https://earth-search.aws.element84.com/v1`.
- Catálogo de código de observação da Terra: `https://github.com/acgeospatial/awesome-earthobservation-code`.
- Técnicas de deep learning em imagens de satélite: `https://github.com/satellite-image-deep-learning/techniques`.
