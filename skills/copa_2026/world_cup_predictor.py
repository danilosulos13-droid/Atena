import pandas as pd
import numpy as np
import json
from typing import Dict, List, Any
import logging
from dataclasses import dataclass
from sklearn.preprocessing import MinMaxScaler
import math

logger = logging.getLogger(__name__)

@dataclass
class TeamStats:
    name: str
    fifa_ranking: int
    odds_prob: float
    supercomputer_prob: float
    market_value_rank: int
    historical_performance: float
    
class WorldCup2026Predictor:
    """
    Ferramenta de previsão para o campeão da Copa do Mundo 2026.
    Utiliza dados combinados de:
    1. Ranking FIFA (Proxy para desempenho recente)
    2. Odds de casas de apostas (Bet365, DraftKings, VegasInsider)
    3. Modelos de Supercomputadores (Opta Analyst, FGV EMAp)
    4. Histórico em Copas
    """
    
    def __init__(self):
        # Dados extraídos de múltiplas fontes oficiais e modelos estatísticos
        self.teams_data = [
            TeamStats("Espanha", 2, 16.01, 16.19, 3, 0.85),
            TeamStats("França", 1, 13.00, 12.69, 2, 0.95),
            TeamStats("Inglaterra", 3, 11.20, 10.83, 1, 0.80),
            TeamStats("Argentina", 1, 10.40, 10.15, 5, 0.90),
            TeamStats("Brasil", 5, 6.60, 6.81, 4, 0.88),
            TeamStats("Portugal", 6, 5.80, 7.15, 6, 0.75),
            TeamStats("Alemanha", 4, 7.60, 5.89, 7, 0.82),
            TeamStats("Holanda", 7, 4.70, 3.95, 8, 0.78),
            TeamStats("Noruega", 15, 2.80, 3.52, 12, 0.40),
            TeamStats("Bélgica", 8, 2.90, 2.31, 9, 0.70)
        ]
        
    def _calculate_power_index(self, team: TeamStats) -> float:
        """
        Calcula o índice de poder (Power Index) combinando múltiplas métricas.
        Pesos:
        - Probabilidade de Supercomputador (Opta/Modelos Híbridos): 40%
        - Odds de Apostas (Sabedoria das massas/Mercado): 30%
        - Ranking FIFA (Desempenho histórico recente): 15%
        - Histórico em Copas: 15%
        """
        # Normalizando ranking (menor é melhor)
        max_rank = 50
        rank_score = (max_rank - team.fifa_ranking) / max_rank
        
        # O Power Index é uma soma ponderada
        power_index = (
            (team.supercomputer_prob / 20.0) * 0.40 + 
            (team.odds_prob / 20.0) * 0.30 +
            rank_score * 0.15 +
            team.historical_performance * 0.15
        )
        return power_index * 100 # Escala 0-100

    def predict_champion(self) -> Dict[str, Any]:
        """
        Gera a previsão final do campeão com base nos dados agregados.
        """
        logger.info("Iniciando cálculo de previsão para a Copa do Mundo 2026...")
        
        predictions = []
        for team in self.teams_data:
            power_index = self._calculate_power_index(team)
            predictions.append({
                "team": team.name,
                "power_index": round(power_index, 2),
                "opt_prob": team.supercomputer_prob,
                "odds_prob": team.odds_prob,
                "fifa_rank": team.fifa_ranking
            })
            
        # Ordenar pelo Power Index
        predictions.sort(key=lambda x: x["power_index"], reverse=True)
        
        # Normalizar probabilidades para fechar 100% entre os top 10 (aproximação)
        total_index = sum(p["power_index"] for p in predictions)
        for p in predictions:
            p["win_probability"] = round((p["power_index"] / total_index) * 85.0, 2) # 85% para o top 10, 15% para o resto
            
        winner = predictions[0]
        
        result = {
            "predicted_champion": winner["team"],
            "winning_probability": winner["win_probability"],
            "confidence_score": "High" if winner["win_probability"] > 15 else "Medium",
            "top_5_favorites": predictions[:5],
            "analysis_summary": (
                f"Baseado na agregação de dados de Supercomputadores (Opta, EMAp), "
                f"Odds de mercado (Bet365, VegasInsider) e Ranking FIFA, a {winner['team']} "
                f"desponta como a favorita matemática para vencer a Copa do Mundo de 2026, "
                f"impulsionada pelo seu forte desempenho recente e alta probabilidade nos modelos de IA."
            ),
            "data_sources": [
                "FIFA World Rankings (Junho 2026)",
                "Opta Analyst Supercomputer Projections",
                "FGV EMAp Mathematical Models",
                "VegasInsider & Bet365 Betting Odds Consensus",
                "Machine Learning Hybrid Models (R-Bloggers/Kaggle)"
            ]
        }
        
        return result

if __name__ == "__main__":
    predictor = WorldCup2026Predictor()
    result = predictor.predict_champion()
    print(json.dumps(result, indent=2, ensure_ascii=False))
