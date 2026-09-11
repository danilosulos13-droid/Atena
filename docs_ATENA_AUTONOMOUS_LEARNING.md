# ATENA — Aprendizagem Autônoma v5

Este módulo fecha o ciclo **experiência → evidência → dataset → treino opcional → avaliação → promoção**.

## O que muda

1. **Memória vira dado de treino somente quando há evidência**.
2. Episódios bem-sucedidos de `consequence_memory` podem alimentar SFT.
3. Feedback explícito pode entrar em `atena_evolution/training/feedback.jsonl`.
4. Duplicatas são removidas por hash estável.
5. Preferências só são criadas quando existem duas respostas reais para o mesmo prompt com scores diferentes — a Atena não fabrica rejeições.
6. Fine-tuning usa **LoRA/PEFT** e mantém o modelo base intacto.
7. O treinamento é opt-in: `ATENA_AUTOTRAIN=1` e `ATENA_TRAIN_MODEL=<modelo>`.
8. Artefatos candidatos ficam separados de produção.
9. O sistema não concede permissão de escrita no repositório ao workflow de aprendizagem.

## Uso local

```bash
python -m pip install -r setup/requirements-pinned.txt
python scripts/atena_autonomous_learning.py collect

# Somente se quiser habilitar treino:
python -m pip install -r setup/requirements-autonomous-learning.txt
export ATENA_TRAIN_MODEL="SEU_MODELO_HF"
export ATENA_AUTOTRAIN=1
python scripts/atena_autonomous_learning.py cycle --train
```

## Política de promoção

O artefato em `atena_evolution/models/candidate/` é **candidato**, não produção. A promoção deve passar pelos benchmarks e gates já existentes da ATENA. Um ganho de loss de treino sozinho nunca é considerado prova de inteligência maior.

## Próxima camada

Para treinamento realmente contínuo, o próximo estágio é registrar também avaliações independentes por tarefa, manter conjuntos de regressão congelados e comparar o candidato com o baseline em: correção, segurança, factualidade, uso de ferramentas, memória e generalização. Só depois disso um adaptador pode ser promovido.
