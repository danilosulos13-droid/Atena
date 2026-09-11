#!/usr/bin/env python3
"""
ATENA Ω - SIMULAÇÃO COPA DO BRASIL 2026: Santos vs Palmeiras
Utiliza estatísticas reais da temporada 2026 e Distribuição de Poisson.
"""

import sys
import os
import json
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from atena_football_oracle import AtenaFootballOracle

def simulate_tie():
    oracle = AtenaFootballOracle()
    
    print("======================================================")
    print(" ATENA-ORACLE: SANTOS vs PALMEIRAS (COPA DO BRASIL 2026)")
    print("======================================================")
    
    league_avg = 1.25
    
    # Jogo 1: Santos (Casa) vs Palmeiras (Fora)
    leg1 = oracle.predict_match(
        home_team="Santos", 
        away_team="Palmeiras", 
        home_avg_scored=1.38, 
        home_avg_conceded=1.67, 
        away_avg_scored=1.70, 
        away_avg_conceded=0.76, 
        league_avg=league_avg
    )
    
    # Jogo 2: Palmeiras (Casa) vs Santos (Fora)
    leg2 = oracle.predict_match(
        home_team="Palmeiras", 
        away_team="Santos", 
        home_avg_scored=1.81, 
        home_avg_conceded=0.76, 
        away_avg_scored=1.42, 
        away_avg_conceded=1.33, 
        league_avg=league_avg
    )
    
    # Agregação correta de xG
    santos_total_xg = leg1['home_xg'] + leg2['away_xg']
    palmeiras_total_xg = leg1['away_xg'] + leg2['home_xg']
    
    if palmeiras_total_xg > santos_total_xg:
        winner = "Palmeiras"
    elif santos_total_xg > palmeiras_total_xg:
        winner = "Santos"
    else:
        winner = "Empate / Disputa de Pênaltis"

    report = {
        "matchup": "Santos vs Palmeiras - Copa do Brasil 2026 (Quartas de Final)",
        "timestamp": datetime.now().isoformat(),
        "leg_1_santos_home": leg1,
        "leg_2_palmeiras_home": leg2,
        "aggregate_xG": {
            "Santos": round(santos_total_xg, 2),
            "Palmeiras": round(palmeiras_total_xg, 2)
        },
        "predicted_qualifier": winner
    }
    
    output_path = "/home/ubuntu/Atena-IA/docs/SANTOS_PALMEIRAS_PREDICTION.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=4, ensure_ascii=False)
        
    print(f"\n[⚽] Jogo 1 (Vila Belmiro): Santos {leg1['home_xg']} x {leg1['away_xg']} Palmeiras")
    print(f"    Probabilidades: {leg1['probabilities']}")
    print(f"[⚽] Jogo 2 (Allianz Parque): Palmeiras {leg2['home_xg']} x {leg2['home_xg']} Santos" if False else f"[⚽] Jogo 2 (Allianz Parque): Palmeiras {leg2['home_xg']} x {leg2['away_xg']} Santos")
    print(f"    Probabilidades: {leg2['probabilities']}")
    print(f"\n[📊] xG Agregado: Santos {round(santos_total_xg, 2)} x {round(palmeiras_total_xg, 2)} Palmeiras")
    print(f"[🏆] VEREDITO DA ATENA-ORACLE: Quem passa é -> {winner.upper()}!")
    print(f"[OK] Relatório salvo em {output_path}")
    
    return report

if __name__ == "__main__":
    simulate_tie()
