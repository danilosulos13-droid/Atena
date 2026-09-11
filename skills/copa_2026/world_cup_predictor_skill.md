# World Cup 2026 Predictor Skill

## Description
Esta skill fornece à Atena a capacidade de prever o campeão da Copa do Mundo FIFA 2026 utilizando um modelo híbrido que agrega dados de múltiplas fontes oficiais e estatísticas.

## Capabilities
- Agregação de probabilidades de Supercomputadores (Opta Analyst, FGV EMAp)
- Análise de Odds de casas de apostas (Bet365, VegasInsider)
- Integração com Ranking Oficial da FIFA
- Cálculo de Power Index ponderado para as principais seleções

## Usage
Para utilizar esta ferramenta de previsão, execute o script Python fornecido:

```bash
python3 /home/ubuntu/Atena-IA/skills/world_cup_predictor.py
```

## Data Sources
A ferramenta utiliza o maior volume possível de dados oficiais e estatísticos disponíveis em Junho de 2026:
1. **FIFA World Rankings**: Dados oficiais de classificação das seleções.
2. **Opta Analyst**: Simulações de supercomputador baseadas em milhares de cenários.
3. **FGV EMAp**: Modelos matemáticos de probabilidade.
4. **VegasInsider**: Consenso de odds de mercado.
5. **Machine Learning Models**: Dados históricos e de valor de mercado (Transfermarkt).
