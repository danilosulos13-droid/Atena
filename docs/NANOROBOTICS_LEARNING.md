# Aprendizagem temática sobre nanorrobótica

A Atena agora possui um coletor temático para construir uma memória baseada em evidências sobre **nanorrobôs, microrrobótica, nanomedicina, materiais, controle, fabricação e segurança**. O catálogo curado contém **56 fontes** entre APIs acadêmicas, repositórios, registros clínicos, órgãos reguladores, normas, periódicos e laboratórios. O fluxo é somente leitura: consulta fontes públicas, registra a proveniência, deduplica os itens, indexa títulos e resumos na memória SQLite e grava relatórios em `analysis_reports/research/`.

## Uso

```bash
# Com o ambiente virtual do projeto
.venv/bin/python core/nanorobotics_learning.py --no-html

# Ou pelo launcher
bash atena nanorobotics --no-html --max-sources 20 --limit-per-source 5

# Descobrir e validar novas fontes automaticamente antes da coleta
bash atena nanorobotics --discover-sources --max-sources 50 --limit-per-source 3

# Consultar a memória temática
.venv/bin/python scripts/atena_research.py --search nanorobotics
```

O arquivo `config/nanorobotics_sources.json` contém o catálogo de fontes. APIs acadêmicas como PubMed, Europe PMC, Crossref, OpenAlex, Semantic Scholar, arXiv, DOAJ e Zenodo são priorizadas. Páginas institucionais de NIH/NCI, FDA, EMA, WHO, OECD, EPA, NIST, ISO, IEEE, RSC, ACS, Nature e universidades complementam literatura, normas, segurança, ensaios clínicos, patentes e engenharia. O modo `--discover-sources` consulta índices públicos, adiciona novos hosts com URL e proveniência, testa se respondem com conteúdo textual e somente então os ativa; candidatos inacessíveis permanecem desativados. Algumas páginas possuem apenas metadados ou resumos públicos e podem exigir acesso institucional para o texto integral; o coletor não contorna paywalls, robots, autenticação ou limites de acesso.

## Proveniência e segurança

Cada item indexado mantém fonte, URL, autoridade, peso inicial, data de publicação e consulta. O conteúdo remoto é tratado como **dado não confiável** e nunca é executado como instrução. A coleta não concede permissões, não envia comandos para dispositivos físicos e não modifica o código ou os pesos da Atena.

A Atena pode aprender no sentido de atualizar sua memória de evidências e gerar relatórios. Alterações de código ou modelo devem continuar sujeitas a sandbox, testes, gate de segurança/regressão, revisão e rollback. O daemon existente não deve ser iniciado com permissões irrestritas nem ser usado para promover automaticamente alterações não validadas.

## Pesos existentes

O arquivo `benchmarks/weights_v1.json` contém pesos de avaliação funcional, não um checkpoint neural: memória `0,25`, planejamento `0,25`, uso de ferramentas `0,20`, raciocínio causal `0,15` e transferência `0,15`. Os gates configurados exigem pontuação geral mínima de `0,80`, segurança mínima de `0,90`, regressão mínima de `0,90` e nenhuma queda permitida em relação ao baseline. O repositório não contém arquivos de pesos de rede (`.safetensors`, `.pt`, `.pth`, `.onnx` ou checkpoints) no estado auditado.
