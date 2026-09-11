#!/usr/bin/env python3
"""
ATENA Ω - MÓDULO M42: Player Intelligence Layer (Oráculo com Dados de Jogadores e Lesões)
Integra desfalques, escalações prováveis e o 'Fator Estrela' no motor de predição.
"""

import sys
import os
import json
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from atena_football_oracle import AtenaFootballOracle

class PlayerIntelligenceOracle(AtenaFootballOracle):
    def __init__(self):
        super().__init__()

    def predict_with_lineups(self, home_team, away_team, home_stats, away_stats, home_absences, away_absences):
        """
        Ajusta o xG base com base nos desfalques e presença de estrelas.
        absences: lista de dicionários ex: [{'name': 'Neymar Jr', 'impact': +0.3, 'status': 'Available'}]
        """
        h_scored = home_stats['scored']
        h_conceded = home_stats['conceded']
        a_scored = away_stats['scored']
        a_conceded = away_stats['conceded']

        # Ajustar por desfalques e estrelas
        for abs_h in home_absences:
            h_scored += abs_h['impact_scored']
            h_conceded += abs_h['impact_conceded']

        for abs_a in away_absences:
            a_scored += abs_a['impact_scored']
            a_conceded += abs_a['impact_conceded']

        # Chamar o modelo base de Poisson com os valores ajustados
        return self.predict_match(home_team, away_team, h_scored, h_conceded, a_scored, a_conceded, league_avg=1.25)

def run_m42_analysis():
    oracle = PlayerIntelligenceOracle()
    
    print("======================================================")
    print(" ATENA Ω — MÓDULO M42: PLAYER INTELLIGENCE LAYER")
    print("======================================================")

    # Contexto de Elenco e Desfalques (Contexto Agosto 2026 - Copa do Brasil)
    # Santos: Com Neymar recuperado (fator ofensivo +0.25 xG), mas ausência de titular na zaga (defesa -0.15)
    santos_stats = {'scored': 1.38, 'conceded': 1.67}
    santos_absences = [
        {'player': 'Neymar Jr', 'role': 'Star Forward', 'impact_scored': +0.25, 'impact_conceded': 0.0, 'status': 'Fit & Active'},
        {'player': 'Gabriel Brazão', 'role': 'Goalkeeper/Defensive adjustment', 'impact_scored': 0.0, 'impact_conceded': +0.10, 'status': 'Minor rotation'}
    ]

    # Palmeiras: Elenco completo, forte consistência tática e ausência de Jhon Arias por suspensão/lesão leve (-0.15 xG)
    palmeiras_stats = {'scored': 1.81, 'conceded': 0.76}
    palmeiras_absences = [
        {'player': 'Jhon Arias', 'role': 'Winger', 'impact_scored': -0.15, 'impact_conceded': 0.0, 'status': 'Doubtful/Suspended'}
    ]

    # Jogo 1: Santos vs Palmeiras (Vila Belmiro)
    leg1 = oracle.predict_with_lineups("Santos", "Palmeiras", santos_stats, palmeiras_stats, santos_absences, palmeiras_absences)

    # Jogo 2: Palmeiras vs Santos (Allianz Parque)
    leg2 = oracle.predict_with_lineups("Palmeiras", "Santos", palmeiras_stats, santos_stats, palmeiras_absences, santos_absences)

    # Agregado
    santos_total_xg = leg1['home_xg'] + leg2['away_xg']
    palmeiras_total_xg = leg1['away_xg'] + leg2['home_xg']

    winner = "Palmeiras" if palmeiras_total_xg > santos_total_xg else "Santos"

    report = {
        "protocol": "Player Intelligence Layer M42",
        "timestamp": datetime.now().isoformat(),
        "matchup": "Santos vs Palmeiras - Copa do Brasil 2026",
        "santos_absences_and_boosts": santos_absences,
        "palmeiras_absences_and_boosts": palmeiras_absences,
        "leg_1": leg1,
        "leg_2": leg2,
        "aggregate_xG_with_players": {
            "Santos": round(santos_total_xg, 2),
            "Palmeiras": round(palmeiras_total_xg, 2)
        },
        "predicted_qualifier": winner
    }

    output_path = "/home/ubuntu/Atena-IA/docs/PLAYER_INTELLIGENCE_PREDICTION.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=4, ensure_ascii=False)

    print(f"\n[⚽] Jogo 1 (Com Fator Elenco): Santos {leg1['home_xg']} x {leg1['away_xg']} Palmeiras")
    print(f"[⚽] Jogo 2 (Com Fator Elenco): Palmeiras {leg2['home_xg']} x {leg2['away_xg']} Santos")
    print(f"[📊] xG Agregado (M42): Santos {round(santos_total_xg, 2)} x {round(palmeiras_total_xg, 2)} Palmeiras")
    print(f"[🏆] VEREDITO M42 (COM JOGADORES E DESFALQUES): -> {winner.upper()}!")
    print(f"[OK] Relatório salvo em {output_path}")

    return report

if __name__ == "__main__":
    run_m42_analysis()
