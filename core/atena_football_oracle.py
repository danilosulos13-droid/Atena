#!/usr/bin/env python3
"""
ATENA Ω - MÓDULO M41: Atena-Oracle (Predição de Futebol)
Utiliza Distribuição de Poisson para prever resultados de jogos baseados em dados reais.
"""

import math
import json
from datetime import datetime

class AtenaFootballOracle:
    def __init__(self):
        self.timestamp = datetime.now().isoformat()

    def poisson(self, actual, mean):
        """Calcula a probabilidade de 'actual' gols dado uma média 'mean'."""
        return (math.exp(-mean) * (mean**actual)) / math.factorial(actual)

    def predict_match(self, home_team, away_team, home_avg_scored, home_avg_conceded, away_avg_scored, away_avg_conceded, league_avg=1.3):
        """
        Calcula a probabilidade do placar e resultado.
        league_avg: Média de gols da liga (usada para normalizar força).
        """
        # Calcular Força de Ataque e Defesa
        home_attack = home_avg_scored / league_avg
        home_defense = home_avg_conceded / league_avg
        away_attack = away_avg_scored / league_avg
        away_defense = away_avg_conceded / league_avg

        # Gols Esperados (Expected Goals - xG)
        home_xg = home_attack * away_defense * league_avg
        away_xg = away_attack * home_defense * league_avg

        # Calcular matriz de probabilidades (até 5 gols)
        probs = []
        home_win_prob = 0
        draw_prob = 0
        away_win_prob = 0

        max_goals = 6
        for h in range(max_goals):
            for a in range(max_goals):
                p_h = self.poisson(h, home_xg)
                p_a = self.poisson(a, away_xg)
                p_score = p_h * p_a
                
                if h > a: home_win_prob += p_score
                elif h == a: draw_prob += p_score
                else: away_win_prob += p_score
                
                probs.append({"score": f"{h}-{a}", "prob": round(p_score * 100, 2)})

        # Ordenar placares mais prováveis
        top_scores = sorted(probs, key=lambda x: x['prob'], reverse=True)[:3]

        prediction = {
            "match": f"{home_team} vs {away_team}",
            "home_xg": round(home_xg, 2),
            "away_xg": round(away_xg, 2),
            "probabilities": {
                home_team: f"{round(home_win_prob * 100, 2)}%",
                "Draw": f"{round(draw_prob * 100, 2)}%",
                away_team: f"{round(away_win_prob * 100, 2)}%"
            },
            "most_likely_scores": top_scores,
            "verdict": home_team if home_win_prob > away_win_prob else away_team
        }
        return prediction

    def run_oracle_mission(self):
        print("======================================================")
        print(" ATENA Ω — ORÁCULO DO FUTEBOL (M41)")
        print(f" DATA: {self.timestamp}")
        print("======================================================")

        # Teste 1: Avaí vs CRB (Série B)
        # Dados: Avaí (Scored 1.35, Conceded 1.35), CRB (Scored 1.6, Conceded 1.4 - est.)
        pred1 = self.predict_match("Avaí", "CRB", 1.35, 1.35, 1.6, 1.4, league_avg=1.2)

        # Teste 2: Bodø/Glimt vs Union SG (Champions League)
        # Dados: Bodø (Scored 3.0, Conceded 0.8), Union SG (Scored 3.3, Conceded 1.5 - est.)
        pred2 = self.predict_match("Bodø/Glimt", "Union SG", 3.0, 0.8, 3.3, 1.5, league_avg=1.5)

        results = [pred1, pred2]
        
        output_path = "/home/ubuntu/Atena-IA/docs/FOOTBALL_ORACLE_PREDICTIONS.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=4, ensure_ascii=False)
        
        for p in results:
            print(f"\n[⚽] Predição: {p['match']}")
            print(f"    xG: {p['home_xg']} - {p['away_xg']}")
            print(f"    Probabilidades: {p['probabilities']}")
            print(f"    Placares Prováveis: {p['most_likely_scores']}")
        
        print(f"\n[OK] Predições do Oráculo salvas em {output_path}")
        return results

if __name__ == "__main__":
    oracle = AtenaFootballOracle()
    oracle.run_oracle_mission()
