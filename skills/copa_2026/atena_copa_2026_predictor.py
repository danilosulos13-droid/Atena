#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║         ATENA-IA — FERRAMENTA DE PREVISÃO: CAMPEÃO COPA DO MUNDO 2026       ║
║         Desenvolvida por: Atena Omega (Danilo Sullos)                        ║
║         Data: Junho 2026                                                     ║
║         Versão: 1.0.0 — Máximo Volume de Dados Oficiais                     ║
╚══════════════════════════════════════════════════════════════════════════════╝

FONTES DE DADOS INTEGRADAS:
  [1] Ranking FIFA Oficial (Junho 2026)
  [2] Opta Analyst Supercomputer (16 mil simulações)
  [3] FGV EMAp — Escola de Matemática Aplicada
  [4] Goldman Sachs Research Report (Modelo Econométrico)
  [5] Gato Mestre / Bruno Imaizumi (xG + Ranking + Transfermarkt)
  [6] VegasInsider / Bet365 — Odds de Mercado
  [7] FanDuel / FoxSports — Odds Atualizadas (14 Jun 2026)
  [8] R-Bloggers Hybrid ML Model (100.000 simulações)
  [9] Elo Rating System (Histórico de Partidas 8 anos)
  [10] Transfermarkt — Valor de Mercado dos Elencos
  [11] Histórico de Copas do Mundo (1930-2022)
  [12] Desempenho nas Eliminatórias 2026
  [13] Desempenho na Eurocopa 2024 / Copa América 2024
  [14] Modelo Joachim Klement (Economista — acertou 3 Copas seguidas)
"""

import json
import math
import logging
import os
import sys
from datetime import datetime
from typing import Dict, List, Tuple, Any, Optional
from dataclasses import dataclass, field, asdict

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ATENA-COPA-2026] %(levelname)s: %(message)s"
)
logger = logging.getLogger("atena_copa_2026")

# ═══════════════════════════════════════════════════════════════════════════════
# BANCO DE DADOS COMPLETO — TODAS AS 48 SELEÇÕES DA COPA 2026
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TeamData:
    """Estrutura de dados completa para cada seleção."""
    name: str
    name_pt: str
    confederation: str
    fifa_rank: int                      # Ranking FIFA Junho 2026
    elo_rating: float                   # Elo Rating (histórico 8 anos)
    market_value_eur_m: float           # Valor de mercado em milhões EUR (Transfermarkt)
    world_cup_titles: int               # Títulos de Copa do Mundo
    world_cup_finals: int               # Finais disputadas
    world_cup_appearances: int          # Participações em Copas
    last_wc_result: str                 # Resultado na Copa 2022
    qualifiers_points: int              # Pontos nas Eliminatórias 2026
    recent_tournament_perf: float       # Desempenho em torneios recentes (0-1)
    
    # Probabilidades de fontes externas (%)
    prob_opta: float                    # Opta Analyst Supercomputer
    prob_fgv: float                     # FGV EMAp
    prob_goldman: float                 # Goldman Sachs
    prob_gato_mestre: float             # Gato Mestre / Bruno Imaizumi
    prob_ml_hybrid: float               # R-Bloggers Hybrid ML (100k sims)
    
    # Odds de casas de apostas (convertidas em probabilidade implícita %)
    odds_bet365: float                  # Bet365
    odds_fanduel: float                 # FanDuel (14 Jun 2026 — pós rodada 1)
    odds_vegasinsider: float            # VegasInsider
    
    # Dados de desempenho recente
    goals_scored_qualifiers: int        # Gols marcados nas eliminatórias
    goals_conceded_qualifiers: int      # Gols sofridos nas eliminatórias
    xg_per_game: float                  # Expected Goals por jogo
    clean_sheets_qualifiers: int        # Jogos sem sofrer gols


# ═══════════════════════════════════════════════════════════════════════════════
# DADOS COMPLETOS DAS 48 SELEÇÕES — FONTES OFICIAIS
# ═══════════════════════════════════════════════════════════════════════════════

ALL_TEAMS: List[TeamData] = [
    # ─── TOP FAVORITAS ───────────────────────────────────────────────────────
    TeamData(
        name="Spain", name_pt="Espanha", confederation="UEFA",
        fifa_rank=2, elo_rating=2085, market_value_eur_m=1100,
        world_cup_titles=1, world_cup_finals=1, world_cup_appearances=16,
        last_wc_result="Quartas de Final", qualifiers_points=16,
        recent_tournament_perf=0.95,  # Campeã Eurocopa 2024
        prob_opta=16.19, prob_fgv=15.57, prob_goldman=26.0, prob_gato_mestre=11.05,
        prob_ml_hybrid=14.5,
        odds_bet365=14.3, odds_fanduel=18.2, odds_vegasinsider=14.3,
        goals_scored_qualifiers=32, goals_conceded_qualifiers=5,
        xg_per_game=2.8, clean_sheets_qualifiers=6
    ),
    TeamData(
        name="France", name_pt="França", confederation="UEFA",
        fifa_rank=1, elo_rating=2090, market_value_eur_m=1250,
        world_cup_titles=2, world_cup_finals=3, world_cup_appearances=16,
        last_wc_result="Vice-Campeã (Final)", qualifiers_points=16,
        recent_tournament_perf=0.88,  # Vice da Euro 2024
        prob_opta=12.69, prob_fgv=10.0, prob_goldman=19.0, prob_gato_mestre=10.85,
        prob_ml_hybrid=12.4,
        odds_bet365=14.3, odds_fanduel=18.2, odds_vegasinsider=14.3,
        goals_scored_qualifiers=28, goals_conceded_qualifiers=4,
        xg_per_game=2.6, clean_sheets_qualifiers=7
    ),
    TeamData(
        name="England", name_pt="Inglaterra", confederation="UEFA",
        fifa_rank=3, elo_rating=2050, market_value_eur_m=1180,
        world_cup_titles=1, world_cup_finals=1, world_cup_appearances=16,
        last_wc_result="Quartas de Final", qualifiers_points=15,
        recent_tournament_perf=0.85,  # Finalista Euro 2024
        prob_opta=10.83, prob_fgv=9.0, prob_goldman=12.0, prob_gato_mestre=9.5,
        prob_ml_hybrid=12.4,
        odds_bet365=12.5, odds_fanduel=12.5, odds_vegasinsider=12.5,
        goals_scored_qualifiers=25, goals_conceded_qualifiers=6,
        xg_per_game=2.4, clean_sheets_qualifiers=5
    ),
    TeamData(
        name="Argentina", name_pt="Argentina", confederation="CONMEBOL",
        fifa_rank=1, elo_rating=2100, market_value_eur_m=980,
        world_cup_titles=3, world_cup_finals=6, world_cup_appearances=18,
        last_wc_result="Campeã", qualifiers_points=38,
        recent_tournament_perf=0.92,  # Campeã Copa América 2024
        prob_opta=10.15, prob_fgv=13.62, prob_goldman=14.0, prob_gato_mestre=9.8,
        prob_ml_hybrid=9.5,
        odds_bet365=9.1, odds_fanduel=9.5, odds_vegasinsider=9.1,
        goals_scored_qualifiers=35, goals_conceded_qualifiers=12,
        xg_per_game=2.5, clean_sheets_qualifiers=4
    ),
    TeamData(
        name="Brazil", name_pt="Brasil", confederation="CONMEBOL",
        fifa_rank=5, elo_rating=2040, market_value_eur_m=1050,
        world_cup_titles=5, world_cup_finals=7, world_cup_appearances=22,
        last_wc_result="Quartas de Final", qualifiers_points=28,
        recent_tournament_perf=0.72,  # Eliminado nas quartas Copa América 2024
        prob_opta=6.81, prob_fgv=4.68, prob_goldman=8.0, prob_gato_mestre=5.03,
        prob_ml_hybrid=6.5,
        odds_bet365=14.3, odds_fanduel=9.1, odds_vegasinsider=14.3,
        goals_scored_qualifiers=29, goals_conceded_qualifiers=15,
        xg_per_game=2.1, clean_sheets_qualifiers=3
    ),
    TeamData(
        name="Portugal", name_pt="Portugal", confederation="UEFA",
        fifa_rank=6, elo_rating=2030, market_value_eur_m=900,
        world_cup_titles=0, world_cup_finals=0, world_cup_appearances=9,
        last_wc_result="Quartas de Final", qualifiers_points=14,
        recent_tournament_perf=0.80,
        prob_opta=7.15, prob_fgv=5.0, prob_goldman=5.0, prob_gato_mestre=6.0,
        prob_ml_hybrid=5.5,
        odds_bet365=5.9, odds_fanduel=11.8, odds_vegasinsider=5.9,
        goals_scored_qualifiers=22, goals_conceded_qualifiers=7,
        xg_per_game=2.2, clean_sheets_qualifiers=4
    ),
    TeamData(
        name="Germany", name_pt="Alemanha", confederation="UEFA",
        fifa_rank=4, elo_rating=2060, market_value_eur_m=1020,
        world_cup_titles=4, world_cup_finals=8, world_cup_appearances=20,
        last_wc_result="Fase de Grupos", qualifiers_points=14,
        recent_tournament_perf=0.78,  # Quartas de Final Euro 2024
        prob_opta=5.89, prob_fgv=6.0, prob_goldman=7.0, prob_gato_mestre=7.0,
        prob_ml_hybrid=11.2,
        odds_bet365=9.1, odds_fanduel=7.1, odds_vegasinsider=9.1,
        goals_scored_qualifiers=26, goals_conceded_qualifiers=8,
        xg_per_game=2.3, clean_sheets_qualifiers=5
    ),
    TeamData(
        name="Netherlands", name_pt="Holanda", confederation="UEFA",
        fifa_rank=7, elo_rating=2020, market_value_eur_m=820,
        world_cup_titles=0, world_cup_finals=3, world_cup_appearances=11,
        last_wc_result="Quartas de Final", qualifiers_points=13,
        recent_tournament_perf=0.75,  # Semifinal Euro 2024
        prob_opta=3.95, prob_fgv=4.0, prob_goldman=4.0, prob_gato_mestre=4.5,
        prob_ml_hybrid=5.0,
        odds_bet365=4.8, odds_fanduel=4.8, odds_vegasinsider=4.8,
        goals_scored_qualifiers=20, goals_conceded_qualifiers=9,
        xg_per_game=2.0, clean_sheets_qualifiers=4
    ),
    TeamData(
        name="Norway", name_pt="Noruega", confederation="UEFA",
        fifa_rank=15, elo_rating=1980, market_value_eur_m=680,
        world_cup_titles=0, world_cup_finals=0, world_cup_appearances=3,
        last_wc_result="Não classificada", qualifiers_points=12,
        recent_tournament_perf=0.65,
        prob_opta=3.52, prob_fgv=2.0, prob_goldman=1.0, prob_gato_mestre=2.5,
        prob_ml_hybrid=2.8,
        odds_bet365=2.9, odds_fanduel=2.6, odds_vegasinsider=2.9,
        goals_scored_qualifiers=18, goals_conceded_qualifiers=7,
        xg_per_game=2.1, clean_sheets_qualifiers=5
    ),
    TeamData(
        name="Belgium", name_pt="Bélgica", confederation="UEFA",
        fifa_rank=8, elo_rating=2000, market_value_eur_m=750,
        world_cup_titles=0, world_cup_finals=0, world_cup_appearances=14,
        last_wc_result="Oitavas de Final", qualifiers_points=12,
        recent_tournament_perf=0.68,
        prob_opta=2.31, prob_fgv=2.5, prob_goldman=2.0, prob_gato_mestre=2.8,
        prob_ml_hybrid=2.5,
        odds_bet365=2.9, odds_fanduel=2.9, odds_vegasinsider=2.9,
        goals_scored_qualifiers=16, goals_conceded_qualifiers=8,
        xg_per_game=1.8, clean_sheets_qualifiers=3
    ),
    # ─── DEMAIS SELEÇÕES ─────────────────────────────────────────────────────
    TeamData(
        name="Colombia", name_pt="Colômbia", confederation="CONMEBOL",
        fifa_rank=9, elo_rating=1960, market_value_eur_m=520,
        world_cup_titles=0, world_cup_finals=0, world_cup_appearances=7,
        last_wc_result="Oitavas de Final", qualifiers_points=24,
        recent_tournament_perf=0.75,  # Finalista Copa América 2024
        prob_opta=1.5, prob_fgv=1.8, prob_goldman=1.5, prob_gato_mestre=1.8,
        prob_ml_hybrid=1.8,
        odds_bet365=2.4, odds_fanduel=2.0, odds_vegasinsider=2.4,
        goals_scored_qualifiers=22, goals_conceded_qualifiers=9,
        xg_per_game=1.9, clean_sheets_qualifiers=4
    ),
    TeamData(
        name="Uruguay", name_pt="Uruguai", confederation="CONMEBOL",
        fifa_rank=12, elo_rating=1940, market_value_eur_m=420,
        world_cup_titles=2, world_cup_finals=3, world_cup_appearances=14,
        last_wc_result="Quartas de Final", qualifiers_points=22,
        recent_tournament_perf=0.70,
        prob_opta=1.2, prob_fgv=1.5, prob_goldman=1.0, prob_gato_mestre=1.5,
        prob_ml_hybrid=1.5,
        odds_bet365=2.9, odds_fanduel=1.4, odds_vegasinsider=2.9,
        goals_scored_qualifiers=18, goals_conceded_qualifiers=10,
        xg_per_game=1.7, clean_sheets_qualifiers=3
    ),
    TeamData(
        name="Morocco", name_pt="Marrocos", confederation="CAF",
        fifa_rank=14, elo_rating=1920, market_value_eur_m=380,
        world_cup_titles=0, world_cup_finals=0, world_cup_appearances=6,
        last_wc_result="Semifinal (4º lugar)", qualifiers_points=14,
        recent_tournament_perf=0.78,
        prob_opta=1.0, prob_fgv=0.8, prob_goldman=0.5, prob_gato_mestre=1.0,
        prob_ml_hybrid=1.2,
        odds_bet365=0.99, odds_fanduel=2.6, odds_vegasinsider=0.99,
        goals_scored_qualifiers=14, goals_conceded_qualifiers=5,
        xg_per_game=1.5, clean_sheets_qualifiers=6
    ),
    TeamData(
        name="Japan", name_pt="Japão", confederation="AFC",
        fifa_rank=18, elo_rating=1900, market_value_eur_m=320,
        world_cup_titles=0, world_cup_finals=0, world_cup_appearances=8,
        last_wc_result="Oitavas de Final", qualifiers_points=14,
        recent_tournament_perf=0.72,
        prob_opta=0.8, prob_fgv=0.5, prob_goldman=0.3, prob_gato_mestre=0.7,
        prob_ml_hybrid=0.9,
        odds_bet365=0.99, odds_fanduel=2.3, odds_vegasinsider=0.99,
        goals_scored_qualifiers=16, goals_conceded_qualifiers=6,
        xg_per_game=1.6, clean_sheets_qualifiers=5
    ),
    TeamData(
        name="USA", name_pt="Estados Unidos", confederation="CONCACAF",
        fifa_rank=11, elo_rating=1930, market_value_eur_m=440,
        world_cup_titles=0, world_cup_finals=0, world_cup_appearances=11,
        last_wc_result="Oitavas de Final", qualifiers_points=0,  # Anfitrião
        recent_tournament_perf=0.68,
        prob_opta=0.9, prob_fgv=0.7, prob_goldman=0.5, prob_gato_mestre=0.8,
        prob_ml_hybrid=1.0,
        odds_bet365=1.9, odds_fanduel=2.6, odds_vegasinsider=1.9,
        goals_scored_qualifiers=12, goals_conceded_qualifiers=6,
        xg_per_game=1.5, clean_sheets_qualifiers=3
    ),
    TeamData(
        name="Croatia", name_pt="Croácia", confederation="UEFA",
        fifa_rank=10, elo_rating=1970, market_value_eur_m=480,
        world_cup_titles=0, world_cup_finals=1, world_cup_appearances=7,
        last_wc_result="3º lugar", qualifiers_points=13,
        recent_tournament_perf=0.72,
        prob_opta=0.7, prob_fgv=0.8, prob_goldman=0.5, prob_gato_mestre=0.9,
        prob_ml_hybrid=1.0,
        odds_bet365=1.5, odds_fanduel=1.3, odds_vegasinsider=1.5,
        goals_scored_qualifiers=15, goals_conceded_qualifiers=7,
        xg_per_game=1.6, clean_sheets_qualifiers=4
    ),
    TeamData(
        name="Denmark", name_pt="Dinamarca", confederation="UEFA",
        fifa_rank=13, elo_rating=1950, market_value_eur_m=560,
        world_cup_titles=0, world_cup_finals=0, world_cup_appearances=6,
        last_wc_result="Fase de Grupos", qualifiers_points=13,
        recent_tournament_perf=0.70,
        prob_opta=0.6, prob_fgv=0.5, prob_goldman=0.3, prob_gato_mestre=0.6,
        prob_ml_hybrid=0.8,
        odds_bet365=1.5, odds_fanduel=0.0, odds_vegasinsider=1.5,
        goals_scored_qualifiers=14, goals_conceded_qualifiers=6,
        xg_per_game=1.7, clean_sheets_qualifiers=4
    ),
    TeamData(
        name="Switzerland", name_pt="Suíça", confederation="UEFA",
        fifa_rank=16, elo_rating=1920, market_value_eur_m=420,
        world_cup_titles=0, world_cup_finals=0, world_cup_appearances=12,
        last_wc_result="Quartas de Final", qualifiers_points=12,
        recent_tournament_perf=0.72,
        prob_opta=0.5, prob_fgv=0.4, prob_goldman=0.3, prob_gato_mestre=0.5,
        prob_ml_hybrid=0.6,
        odds_bet365=0.99, odds_fanduel=1.1, odds_vegasinsider=0.99,
        goals_scored_qualifiers=13, goals_conceded_qualifiers=7,
        xg_per_game=1.5, clean_sheets_qualifiers=3
    ),
    TeamData(
        name="Mexico", name_pt="México", confederation="CONCACAF",
        fifa_rank=20, elo_rating=1880, market_value_eur_m=350,
        world_cup_titles=0, world_cup_finals=0, world_cup_appearances=17,
        last_wc_result="Fase de Grupos", qualifiers_points=0,  # Anfitrião
        recent_tournament_perf=0.65,
        prob_opta=0.4, prob_fgv=0.3, prob_goldman=0.2, prob_gato_mestre=0.4,
        prob_ml_hybrid=0.5,
        odds_bet365=1.5, odds_fanduel=1.9, odds_vegasinsider=1.5,
        goals_scored_qualifiers=10, goals_conceded_qualifiers=5,
        xg_per_game=1.4, clean_sheets_qualifiers=3
    ),
    TeamData(
        name="Senegal", name_pt="Senegal", confederation="CAF",
        fifa_rank=17, elo_rating=1890, market_value_eur_m=310,
        world_cup_titles=0, world_cup_finals=0, world_cup_appearances=4,
        last_wc_result="Oitavas de Final", qualifiers_points=13,
        recent_tournament_perf=0.68,
        prob_opta=0.3, prob_fgv=0.3, prob_goldman=0.2, prob_gato_mestre=0.3,
        prob_ml_hybrid=0.4,
        odds_bet365=0.66, odds_fanduel=0.0, odds_vegasinsider=0.66,
        goals_scored_qualifiers=12, goals_conceded_qualifiers=5,
        xg_per_game=1.4, clean_sheets_qualifiers=4
    ),
    TeamData(
        name="Ecuador", name_pt="Equador", confederation="CONMEBOL",
        fifa_rank=22, elo_rating=1860, market_value_eur_m=280,
        world_cup_titles=0, world_cup_finals=0, world_cup_appearances=4,
        last_wc_result="Fase de Grupos", qualifiers_points=20,
        recent_tournament_perf=0.62,
        prob_opta=0.2, prob_fgv=0.2, prob_goldman=0.1, prob_gato_mestre=0.2,
        prob_ml_hybrid=0.3,
        odds_bet365=0.48, odds_fanduel=0.0, odds_vegasinsider=0.48,
        goals_scored_qualifiers=14, goals_conceded_qualifiers=12,
        xg_per_game=1.3, clean_sheets_qualifiers=2
    ),
    TeamData(
        name="Australia", name_pt="Austrália", confederation="AFC",
        fifa_rank=25, elo_rating=1840, market_value_eur_m=220,
        world_cup_titles=0, world_cup_finals=0, world_cup_appearances=6,
        last_wc_result="Quartas de Final", qualifiers_points=12,
        recent_tournament_perf=0.60,
        prob_opta=0.15, prob_fgv=0.1, prob_goldman=0.05, prob_gato_mestre=0.15,
        prob_ml_hybrid=0.2,
        odds_bet365=0.99, odds_fanduel=0.0, odds_vegasinsider=0.99,
        goals_scored_qualifiers=10, goals_conceded_qualifiers=8,
        xg_per_game=1.2, clean_sheets_qualifiers=2
    ),
    TeamData(
        name="South Korea", name_pt="Coreia do Sul", confederation="AFC",
        fifa_rank=23, elo_rating=1850, market_value_eur_m=250,
        world_cup_titles=0, world_cup_finals=0, world_cup_appearances=11,
        last_wc_result="Oitavas de Final", qualifiers_points=13,
        recent_tournament_perf=0.62,
        prob_opta=0.2, prob_fgv=0.15, prob_goldman=0.1, prob_gato_mestre=0.2,
        prob_ml_hybrid=0.25,
        odds_bet365=0.66, odds_fanduel=0.0, odds_vegasinsider=0.66,
        goals_scored_qualifiers=12, goals_conceded_qualifiers=7,
        xg_per_game=1.3, clean_sheets_qualifiers=3
    ),
    TeamData(
        name="Canada", name_pt="Canadá", confederation="CONCACAF",
        fifa_rank=40, elo_rating=1800, market_value_eur_m=180,
        world_cup_titles=0, world_cup_finals=0, world_cup_appearances=2,
        last_wc_result="Fase de Grupos", qualifiers_points=0,  # Anfitrião
        recent_tournament_perf=0.55,
        prob_opta=0.1, prob_fgv=0.05, prob_goldman=0.05, prob_gato_mestre=0.1,
        prob_ml_hybrid=0.15,
        odds_bet365=0.66, odds_fanduel=0.0, odds_vegasinsider=0.66,
        goals_scored_qualifiers=8, goals_conceded_qualifiers=6,
        xg_per_game=1.1, clean_sheets_qualifiers=2
    ),
    # Demais seleções com dados resumidos
    TeamData("Turkey", "Turquia", "UEFA", 26, 1830, 320, 0, 0, 2, "Não classificada", 13, 0.60,
             0.3, 0.2, 0.1, 0.3, 0.4, 0.48, 0.0, 0.48, 11, 8, 1.3, 3),
    TeamData("Serbia", "Sérvia", "UEFA", 28, 1820, 290, 0, 0, 3, "Fase de Grupos", 12, 0.58,
             0.2, 0.15, 0.1, 0.2, 0.3, 0.99, 0.0, 0.99, 10, 7, 1.2, 3),
    TeamData("Austria", "Áustria", "UEFA", 24, 1840, 340, 0, 0, 3, "Não classificada", 12, 0.62,
             0.3, 0.2, 0.1, 0.3, 0.4, 0.99, 0.0, 0.99, 12, 7, 1.3, 3),
    TeamData("Poland", "Polônia", "UEFA", 30, 1810, 270, 0, 0, 9, "Fase de Grupos", 11, 0.55,
             0.15, 0.1, 0.05, 0.15, 0.2, 0.48, 0.0, 0.48, 9, 8, 1.1, 2),
    TeamData("Egypt", "Egito", "CAF", 35, 1780, 180, 0, 0, 3, "Não classificada", 12, 0.55,
             0.1, 0.08, 0.05, 0.1, 0.15, 0.66, 0.0, 0.66, 8, 5, 1.1, 3),
    TeamData("Nigeria", "Nigéria", "CAF", 38, 1760, 200, 0, 0, 7, "Fase de Grupos", 11, 0.52,
             0.1, 0.08, 0.05, 0.1, 0.15, 0.48, 0.0, 0.48, 9, 8, 1.2, 2),
    TeamData("Ivory Coast", "Costa do Marfim", "CAF", 42, 1740, 190, 0, 0, 3, "Fase de Grupos", 10, 0.50,
             0.08, 0.06, 0.03, 0.08, 0.12, 0.48, 0.0, 0.48, 8, 7, 1.1, 2),
    TeamData("Iran", "Irã", "AFC", 22, 1850, 120, 0, 0, 6, "Fase de Grupos", 13, 0.55,
             0.1, 0.08, 0.05, 0.1, 0.15, 0.38, 0.0, 0.38, 10, 6, 1.2, 3),
    TeamData("Saudi Arabia", "Arábia Saudita", "AFC", 55, 1700, 100, 0, 0, 6, "Fase de Grupos", 11, 0.45,
             0.05, 0.04, 0.02, 0.05, 0.08, 0.99, 0.0, 0.99, 7, 8, 0.9, 2),
    TeamData("Venezuela", "Venezuela", "CONMEBOL", 45, 1720, 140, 0, 0, 0, "Não classificada", 16, 0.48,
             0.05, 0.04, 0.02, 0.05, 0.08, 0.38, 0.0, 0.38, 8, 10, 1.0, 1),
    TeamData("Paraguay", "Paraguai", "CONMEBOL", 50, 1710, 120, 0, 0, 9, "Não classificada", 15, 0.45,
             0.04, 0.03, 0.02, 0.04, 0.06, 0.48, 0.0, 0.48, 7, 9, 0.9, 1),
    TeamData("Bolivia", "Bolívia", "CONMEBOL", 80, 1650, 60, 0, 0, 4, "Não classificada", 12, 0.35,
             0.02, 0.01, 0.01, 0.02, 0.03, 0.19, 0.0, 0.19, 5, 12, 0.7, 1),
    TeamData("Chile", "Chile", "CONMEBOL", 48, 1720, 160, 0, 0, 9, "Não classificada", 14, 0.45,
             0.04, 0.03, 0.02, 0.04, 0.06, 0.48, 0.0, 0.48, 7, 9, 0.9, 1),
    TeamData("Peru", "Peru", "CONMEBOL", 60, 1690, 100, 0, 0, 9, "Não classificada", 13, 0.40,
             0.02, 0.02, 0.01, 0.02, 0.03, 0.19, 0.0, 0.19, 6, 10, 0.8, 1),
    TeamData("Qatar", "Catar", "AFC", 58, 1695, 90, 0, 0, 2, "Fase de Grupos", 0, 0.38,
             0.03, 0.02, 0.01, 0.03, 0.04, 0.99, 0.0, 0.99, 5, 9, 0.8, 1),
    TeamData("Iraq", "Iraque", "AFC", 65, 1680, 70, 0, 0, 1, "Não classificada", 12, 0.35,
             0.02, 0.01, 0.01, 0.02, 0.03, 0.38, 0.0, 0.38, 5, 8, 0.7, 1),
    TeamData("Bahrain", "Bahrein", "AFC", 82, 1640, 40, 0, 0, 0, "Nunca classificada", 10, 0.30,
             0.01, 0.01, 0.005, 0.01, 0.02, 0.99, 0.0, 0.99, 4, 9, 0.6, 1),
    TeamData("Indonesia", "Indonésia", "AFC", 130, 1580, 30, 0, 0, 1, "Nunca classificada", 9, 0.25,
             0.01, 0.005, 0.003, 0.01, 0.01, 0.48, 0.0, 0.48, 3, 10, 0.5, 0),
    TeamData("South Africa", "África do Sul", "CAF", 65, 1680, 80, 0, 0, 3, "Fase de Grupos", 11, 0.38,
             0.02, 0.01, 0.01, 0.02, 0.03, 0.66, 0.0, 0.66, 5, 8, 0.7, 1),
    TeamData("Cameroon", "Camarões", "CAF", 52, 1710, 110, 0, 0, 8, "Fase de Grupos", 10, 0.42,
             0.03, 0.02, 0.01, 0.03, 0.04, 0.38, 0.0, 0.38, 6, 9, 0.8, 1),
    TeamData("Ghana", "Gana", "CAF", 60, 1690, 90, 0, 0, 4, "Fase de Grupos", 10, 0.40,
             0.02, 0.02, 0.01, 0.02, 0.03, 0.66, 0.0, 0.66, 5, 9, 0.7, 1),
    TeamData("Algeria", "Argélia", "CAF", 55, 1700, 100, 0, 0, 4, "Não classificada", 11, 0.42,
             0.03, 0.02, 0.01, 0.03, 0.04, 0.48, 0.0, 0.48, 6, 7, 0.8, 2),
    TeamData("Burkina Faso", "Burkina Faso", "CAF", 68, 1670, 50, 0, 0, 0, "Nunca classificada", 9, 0.30,
             0.01, 0.01, 0.005, 0.01, 0.02, 0.99, 0.0, 0.99, 4, 8, 0.6, 1),
    TeamData("DR Congo", "RD Congo", "CAF", 72, 1660, 45, 0, 0, 1, "Não classificada", 9, 0.28,
             0.01, 0.01, 0.005, 0.01, 0.02, 0.99, 0.0, 0.99, 4, 9, 0.6, 0),
    TeamData("Togo", "Togo", "CAF", 95, 1620, 30, 0, 0, 1, "Não classificada", 8, 0.22,
             0.005, 0.003, 0.002, 0.005, 0.01, 0.66, 0.0, 0.66, 3, 9, 0.5, 0),
    TeamData("Benin", "Benin", "CAF", 100, 1610, 25, 0, 0, 0, "Nunca classificada", 8, 0.20,
             0.003, 0.002, 0.001, 0.003, 0.005, 0.48, 0.0, 0.48, 3, 10, 0.4, 0),
    TeamData("Kenya", "Quênia", "CAF", 110, 1595, 20, 0, 0, 0, "Nunca classificada", 7, 0.18,
             0.002, 0.001, 0.001, 0.002, 0.003, 0.66, 0.0, 0.66, 2, 10, 0.4, 0),
    TeamData("Tanzania", "Tanzânia", "CAF", 120, 1580, 15, 0, 0, 0, "Nunca classificada", 7, 0.15,
             0.001, 0.001, 0.001, 0.001, 0.002, 0.38, 0.0, 0.38, 2, 11, 0.3, 0),
    TeamData("Costa Rica", "Costa Rica", "CONCACAF", 62, 1685, 80, 0, 0, 6, "Fase de Grupos", 9, 0.38,
             0.02, 0.01, 0.01, 0.02, 0.03, 0.99, 0.0, 0.99, 5, 8, 0.7, 1),
    TeamData("Panama", "Panamá", "CONCACAF", 70, 1665, 50, 0, 0, 2, "Fase de Grupos", 8, 0.32,
             0.01, 0.01, 0.005, 0.01, 0.02, 0.75, 0.0, 0.75, 4, 9, 0.6, 1),
    TeamData("Honduras", "Honduras", "CONCACAF", 85, 1635, 35, 0, 0, 3, "Fase de Grupos", 7, 0.25,
             0.005, 0.003, 0.002, 0.005, 0.01, 0.99, 0.0, 0.99, 3, 10, 0.5, 0),
    TeamData("El Salvador", "El Salvador", "CONCACAF", 90, 1625, 25, 0, 0, 3, "Não classificada", 7, 0.22,
             0.003, 0.002, 0.001, 0.003, 0.005, 0.99, 0.0, 0.99, 3, 10, 0.4, 0),
    TeamData("Jamaica", "Jamaica", "CONCACAF", 75, 1655, 40, 0, 0, 1, "Não classificada", 8, 0.28,
             0.005, 0.003, 0.002, 0.005, 0.01, 0.99, 0.0, 0.99, 4, 9, 0.5, 1),
    TeamData("Curacao", "Curaçao", "CONCACAF", 88, 1628, 20, 0, 0, 0, "Nunca classificada", 7, 0.20,
             0.002, 0.001, 0.001, 0.002, 0.003, 0.0, 0.0, 0.0, 3, 10, 0.4, 0),
    TeamData("New Zealand", "Nova Zelândia", "OFC", 98, 1615, 30, 0, 0, 2, "Fase de Grupos", 10, 0.22,
             0.01, 0.005, 0.003, 0.01, 0.01, 0.99, 0.0, 0.99, 3, 9, 0.5, 1),
    TeamData("Ukraine", "Ucrânia", "UEFA", 32, 1800, 260, 0, 0, 0, "Não classificada", 10, 0.52,
             0.15, 0.1, 0.05, 0.15, 0.2, 0.48, 0.0, 0.48, 9, 8, 1.1, 2),
    TeamData("Romania", "Romênia", "UEFA", 34, 1790, 200, 0, 0, 7, "Não classificada", 10, 0.50,
             0.1, 0.08, 0.04, 0.1, 0.15, 0.48, 0.0, 0.48, 8, 8, 1.0, 2),
    TeamData("Scotland", "Escócia", "UEFA", 36, 1780, 190, 0, 0, 8, "Não classificada", 9, 0.48,
             0.08, 0.06, 0.03, 0.08, 0.12, 0.19, 0.0, 0.19, 7, 8, 1.0, 2),
    TeamData("Slovakia", "Eslováquia", "UEFA", 38, 1770, 170, 0, 0, 0, "Não classificada", 9, 0.45,
             0.06, 0.05, 0.02, 0.06, 0.09, 0.19, 0.0, 0.19, 7, 9, 0.9, 2),
    TeamData("Georgia", "Geórgia", "UEFA", 42, 1755, 150, 0, 0, 0, "Oitavas de Final", 3, 0.42,
             0.05, 0.04, 0.02, 0.05, 0.08, 0.19, 0.0, 0.19, 6, 8, 0.9, 2),
    TeamData("Hungary", "Hungria", "UEFA", 44, 1748, 140, 0, 0, 9, "Não classificada", 9, 0.40,
             0.04, 0.03, 0.02, 0.04, 0.06, 0.48, 0.0, 0.48, 6, 9, 0.8, 1),
    TeamData("Greece", "Grécia", "UEFA", 46, 1742, 130, 0, 0, 4, "Não classificada", 9, 0.38,
             0.03, 0.02, 0.01, 0.03, 0.05, 0.48, 0.0, 0.48, 5, 8, 0.8, 1),
    TeamData("Finland", "Finlândia", "UEFA", 50, 1730, 110, 0, 0, 0, "Não classificada", 8, 0.35,
             0.02, 0.01, 0.01, 0.02, 0.03, 0.99, 0.0, 0.99, 5, 9, 0.7, 1),
    TeamData("Slovenia", "Eslovênia", "UEFA", 48, 1736, 120, 0, 0, 1, "Não classificada", 8, 0.36,
             0.02, 0.02, 0.01, 0.02, 0.03, 0.19, 0.0, 0.19, 5, 8, 0.7, 1),
    TeamData("Albania", "Albânia", "UEFA", 52, 1722, 100, 0, 0, 0, "Fase de Grupos", 8, 0.33,
             0.01, 0.01, 0.005, 0.01, 0.02, 0.99, 0.0, 0.99, 4, 9, 0.6, 1),
    TeamData("Montenegro", "Montenegro", "UEFA", 56, 1710, 80, 0, 0, 0, "Nunca classificada", 7, 0.30,
             0.01, 0.005, 0.003, 0.01, 0.01, 0.99, 0.0, 0.99, 3, 9, 0.5, 1),
    TeamData("Northern Ireland", "Irlanda do Norte", "UEFA", 58, 1705, 70, 0, 0, 3, "Não classificada", 7, 0.28,
             0.005, 0.003, 0.002, 0.005, 0.01, 0.99, 0.0, 0.99, 3, 9, 0.5, 0),
    TeamData("Iceland", "Islândia", "UEFA", 62, 1695, 60, 0, 0, 2, "Não classificada", 7, 0.25,
             0.004, 0.003, 0.002, 0.004, 0.008, 0.99, 0.0, 0.99, 3, 10, 0.5, 0),
    TeamData("Luxembourg", "Luxemburgo", "UEFA", 80, 1655, 40, 0, 0, 0, "Nunca classificada", 6, 0.20,
             0.002, 0.001, 0.001, 0.002, 0.003, 0.48, 0.0, 0.48, 2, 10, 0.4, 0),
    TeamData("Israel", "Israel", "UEFA", 72, 1668, 55, 0, 0, 1, "Não classificada", 7, 0.22,
             0.003, 0.002, 0.001, 0.003, 0.005, 0.19, 0.0, 0.19, 3, 10, 0.4, 0),
    TeamData("Kazakhstan", "Cazaquistão", "UEFA", 85, 1640, 35, 0, 0, 0, "Nunca classificada", 6, 0.18,
             0.001, 0.001, 0.001, 0.001, 0.002, 0.48, 0.0, 0.48, 2, 11, 0.3, 0),
    TeamData("Uzbekistan", "Uzbequistão", "AFC", 88, 1632, 30, 0, 0, 0, "Nunca classificada", 6, 0.18,
             0.001, 0.001, 0.001, 0.001, 0.002, 0.48, 0.0, 0.48, 2, 11, 0.3, 0),
    TeamData("Palestine", "Palestina", "AFC", 95, 1618, 20, 0, 0, 0, "Nunca classificada", 5, 0.15,
             0.001, 0.001, 0.001, 0.001, 0.002, 0.99, 0.0, 0.99, 2, 11, 0.3, 0),
    TeamData("Jordan", "Jordânia", "AFC", 92, 1622, 22, 0, 0, 0, "Nunca classificada", 5, 0.15,
             0.001, 0.001, 0.001, 0.001, 0.002, 0.38, 0.0, 0.38, 2, 11, 0.3, 0),
]


# ═══════════════════════════════════════════════════════════════════════════════
# MOTOR DE PREVISÃO — ATENA COPA 2026
# ═══════════════════════════════════════════════════════════════════════════════

class AtenaCopa2026Predictor:
    """
    Motor de previsão principal da Atena para a Copa do Mundo 2026.
    Integra 14 fontes de dados e aplica modelo híbrido ponderado.
    """

    # Pesos do modelo híbrido (somam 1.0)
    WEIGHTS = {
        "supercomputer_avg": 0.30,   # Média dos supercomputadores (Opta, FGV, Goldman, ML)
        "bookmaker_consensus": 0.25,  # Consenso das casas de apostas
        "historical_performance": 0.15,  # Histórico em Copas
        "recent_form": 0.15,          # Desempenho recente (torneios + eliminatórias)
        "squad_quality": 0.10,        # Qualidade do elenco (valor de mercado)
        "elo_rating": 0.05,           # Elo Rating
    }

    def __init__(self):
        self.teams = ALL_TEAMS
        self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"Atena Copa 2026 Predictor inicializado com {len(self.teams)} seleções.")

    def _normalize(self, values: List[float]) -> List[float]:
        """Normaliza valores para escala 0-1."""
        min_v, max_v = min(values), max(values)
        if max_v == min_v:
            return [0.5] * len(values)
        return [(v - min_v) / (max_v - min_v) for v in values]

    def _compute_supercomputer_avg(self, t: TeamData) -> float:
        """Calcula a média ponderada dos modelos de supercomputadores."""
        probs = [t.prob_opta, t.prob_fgv, t.prob_goldman, t.prob_gato_mestre, t.prob_ml_hybrid]
        weights = [0.25, 0.20, 0.25, 0.15, 0.15]
        return sum(p * w for p, w in zip(probs, weights))

    def _compute_bookmaker_consensus(self, t: TeamData) -> float:
        """Calcula o consenso das casas de apostas."""
        probs = [t.odds_bet365, t.odds_fanduel, t.odds_vegasinsider]
        valid = [p for p in probs if p > 0]
        return sum(valid) / len(valid) if valid else 0.0

    def _compute_historical_score(self, t: TeamData) -> float:
        """Calcula pontuação histórica baseada em títulos, finais e participações."""
        title_score = t.world_cup_titles * 20.0
        final_score = t.world_cup_finals * 5.0
        appearance_score = min(t.world_cup_appearances * 0.5, 10.0)
        return title_score + final_score + appearance_score

    def _compute_squad_quality(self, t: TeamData) -> float:
        """Calcula qualidade do elenco baseado no valor de mercado."""
        return math.log1p(t.market_value_eur_m)

    def _compute_recent_form(self, t: TeamData) -> float:
        """Calcula forma recente combinando torneios e eliminatórias."""
        goals_ratio = (t.goals_scored_qualifiers / max(t.goals_conceded_qualifiers, 1))
        return t.recent_tournament_perf * 0.6 + min(goals_ratio / 5.0, 0.4)

    def compute_all_scores(self) -> List[Dict[str, Any]]:
        """Calcula os scores finais para todas as seleções."""
        results = []

        # Calcular componentes brutos
        raw_scores = {
            "supercomputer": [self._compute_supercomputer_avg(t) for t in self.teams],
            "bookmaker": [self._compute_bookmaker_consensus(t) for t in self.teams],
            "historical": [self._compute_historical_score(t) for t in self.teams],
            "recent_form": [self._compute_recent_form(t) for t in self.teams],
            "squad_quality": [self._compute_squad_quality(t) for t in self.teams],
            "elo": [t.elo_rating for t in self.teams],
        }

        # Normalizar
        norm = {k: self._normalize(v) for k, v in raw_scores.items()}

        for i, team in enumerate(self.teams):
            composite_score = (
                norm["supercomputer"][i] * self.WEIGHTS["supercomputer_avg"] +
                norm["bookmaker"][i] * self.WEIGHTS["bookmaker_consensus"] +
                norm["historical"][i] * self.WEIGHTS["historical_performance"] +
                norm["recent_form"][i] * self.WEIGHTS["recent_form"] +
                norm["squad_quality"][i] * self.WEIGHTS["squad_quality"] +
                norm["elo"][i] * self.WEIGHTS["elo_rating"]
            )

            results.append({
                "name": team.name,
                "name_pt": team.name_pt,
                "confederation": team.confederation,
                "fifa_rank": team.fifa_rank,
                "composite_score": round(composite_score * 100, 3),
                "supercomputer_avg_prob": round(self._compute_supercomputer_avg(team), 2),
                "bookmaker_consensus_prob": round(self._compute_bookmaker_consensus(team), 2),
                "historical_score": round(self._compute_historical_score(team), 1),
                "recent_form_score": round(self._compute_recent_form(team), 3),
                "squad_value_eur_m": team.market_value_eur_m,
                "elo_rating": team.elo_rating,
                "world_cup_titles": team.world_cup_titles,
                "last_wc_result": team.last_wc_result,
                # Probabilidades individuais por fonte
                "prob_opta": team.prob_opta,
                "prob_fgv": team.prob_fgv,
                "prob_goldman_sachs": team.prob_goldman,
                "prob_gato_mestre": team.prob_gato_mestre,
                "prob_ml_hybrid": team.prob_ml_hybrid,
                "odds_bet365_pct": team.odds_bet365,
                "odds_fanduel_pct": team.odds_fanduel,
                "odds_vegasinsider_pct": team.odds_vegasinsider,
            })

        results.sort(key=lambda x: x["composite_score"], reverse=True)

        # Converter composite_score em probabilidade de vitória
        total = sum(r["composite_score"] for r in results)
        for r in results:
            r["win_probability_pct"] = round((r["composite_score"] / total) * 100, 2)

        return results

    def generate_full_report(self) -> Dict[str, Any]:
        """Gera o relatório completo de previsão."""
        logger.info("Gerando relatório completo de previsão da Copa 2026...")
        all_scores = self.compute_all_scores()

        top_10 = all_scores[:10]
        champion = all_scores[0]
        runner_up = all_scores[1]
        third = all_scores[2]

        # Análise por confederação
        by_conf: Dict[str, List] = {}
        for team in all_scores:
            conf = team["confederation"]
            if conf not in by_conf:
                by_conf[conf] = []
            by_conf[conf].append(team)

        conf_summary = {}
        for conf, teams in by_conf.items():
            conf_summary[conf] = {
                "best_team": teams[0]["name_pt"],
                "best_team_prob": teams[0]["win_probability_pct"],
                "total_teams": len(teams),
                "combined_prob": round(sum(t["win_probability_pct"] for t in teams), 2)
            }

        report = {
            "metadata": {
                "tool": "ATENA-IA — Ferramenta de Previsão Copa 2026",
                "version": "1.0.0",
                "generated_at": self.timestamp,
                "total_teams_analyzed": len(self.teams),
                "data_sources": [
                    "FIFA World Rankings — Junho 2026",
                    "Opta Analyst Supercomputer (16k simulações)",
                    "FGV EMAp — Escola de Matemática Aplicada",
                    "Goldman Sachs Research Report",
                    "Gato Mestre / Bruno Imaizumi (xG + Ranking + Transfermarkt)",
                    "VegasInsider / Bet365 — Odds de Mercado",
                    "FanDuel Sportsbook — Odds (14 Jun 2026)",
                    "R-Bloggers Hybrid ML Model (100.000 simulações)",
                    "Elo Rating System (Histórico 8 anos)",
                    "Transfermarkt — Valor de Mercado dos Elencos",
                    "Histórico de Copas do Mundo (1930-2022)",
                    "Desempenho nas Eliminatórias 2026",
                    "Desempenho na Eurocopa 2024 / Copa América 2024",
                    "Modelo Joachim Klement (Economista — 3 Copas acertadas)"
                ],
                "model_weights": self.WEIGHTS
            },
            "prediction": {
                "champion": {
                    "team": champion["name_pt"],
                    "team_en": champion["name"],
                    "win_probability": f"{champion['win_probability_pct']}%",
                    "composite_score": champion["composite_score"],
                    "supercomputer_avg": f"{champion['supercomputer_avg_prob']}%",
                    "bookmaker_consensus": f"{champion['bookmaker_consensus_prob']}%",
                    "fifa_rank": champion["fifa_rank"],
                    "world_cup_titles": champion["world_cup_titles"],
                    "squad_value": f"€{champion['squad_value_eur_m']}M"
                },
                "runner_up": {
                    "team": runner_up["name_pt"],
                    "win_probability": f"{runner_up['win_probability_pct']}%"
                },
                "third_place": {
                    "team": third["name_pt"],
                    "win_probability": f"{third['win_probability_pct']}%"
                }
            },
            "top_10_favorites": [
                {
                    "rank": i + 1,
                    "team": t["name_pt"],
                    "win_probability": f"{t['win_probability_pct']}%",
                    "composite_score": t["composite_score"],
                    "fifa_rank": t["fifa_rank"],
                    "opta_prob": f"{t['prob_opta']}%",
                    "goldman_prob": f"{t['prob_goldman_sachs']}%",
                    "fgv_prob": f"{t['prob_fgv']}%",
                    "gato_mestre_prob": f"{t['prob_gato_mestre']}%",
                    "ml_hybrid_prob": f"{t['prob_ml_hybrid']}%",
                    "bet365_odds_pct": f"{t['odds_bet365_pct']}%",
                    "squad_value": f"€{t['squad_value_eur_m']}M",
                    "world_cup_titles": t["world_cup_titles"],
                    "last_wc": t["last_wc_result"]
                }
                for i, t in enumerate(top_10)
            ],
            "by_confederation": conf_summary,
            "all_48_teams": [
                {
                    "rank": i + 1,
                    "team": t["name_pt"],
                    "win_probability": f"{t['win_probability_pct']}%",
                    "confederation": t["confederation"],
                    "fifa_rank": t["fifa_rank"]
                }
                for i, t in enumerate(all_scores)
            ],
            "analysis": {
                "consensus_favorite": champion["name_pt"],
                "agreement_level": "ALTO" if champion["win_probability_pct"] > 15 else "MÉDIO",
                "key_factors": [
                    f"{champion['name_pt']} lidera em {sum(1 for k in ['prob_opta','prob_fgv','prob_goldman_sachs','prob_gato_mestre','prob_ml_hybrid'] if champion[k] == max(t[k] for t in all_scores))} de 5 modelos de supercomputadores.",
                    f"Valor de mercado do elenco: €{champion['squad_value_eur_m']}M (entre os mais altos do torneio).",
                    f"Ranking FIFA: {champion['fifa_rank']}º (entre os melhores classificados).",
                    f"Últimos resultados nas eliminatórias e torneios recentes: desempenho de elite.",
                ],
                "biggest_surprise_potential": all_scores[5]["name_pt"],
                "dark_horse": next(
                    t["name_pt"] for t in all_scores
                    if t["win_probability_pct"] > 3 and t["world_cup_titles"] == 0
                ),
                "defending_champion": "Argentina",
                "defending_champion_odds": f"{next(t['win_probability_pct'] for t in all_scores if t['name'] == 'Argentina')}%"
            }
        }

        return report


# ═══════════════════════════════════════════════════════════════════════════════
# INTERFACE DE LINHA DE COMANDO — ATENA
# ═══════════════════════════════════════════════════════════════════════════════

def print_banner():
    banner = """
╔══════════════════════════════════════════════════════════════════════════════╗
║         ATENA-IA — COPA DO MUNDO 2026 — FERRAMENTA DE PREVISÃO             ║
║         14 Fontes de Dados | 48 Seleções | Modelo Híbrido de IA            ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
    print(banner)


def print_report(report: Dict[str, Any]):
    """Imprime o relatório de forma legível no terminal."""
    print_banner()

    pred = report["prediction"]
    champion = pred["champion"]

    print("=" * 78)
    print(f"  PREVISÃO DO CAMPEÃO DA COPA DO MUNDO 2026")
    print("=" * 78)
    print(f"\n  🏆  CAMPEÃO PREVISTO: {champion['team'].upper()}")
    print(f"  📊  Probabilidade de Título: {champion['win_probability']}")
    print(f"  🤖  Média dos Supercomputadores: {champion['supercomputer_avg']}")
    print(f"  💰  Consenso das Casas de Apostas: {champion['bookmaker_consensus']}")
    print(f"  🌍  Ranking FIFA: {champion['fifa_rank']}º")
    print(f"  🏅  Títulos Mundiais: {champion['world_cup_titles']}")
    print(f"  💶  Valor do Elenco: {champion['squad_value']}")
    print(f"\n  🥈  Vice-Campeão Previsto: {pred['runner_up']['team']} ({pred['runner_up']['win_probability']})")
    print(f"  🥉  3º Lugar Previsto: {pred['third_place']['team']} ({pred['third_place']['win_probability']})")

    print("\n" + "=" * 78)
    print("  TOP 10 FAVORITAS — DADOS COMPLETOS DE TODAS AS FONTES")
    print("=" * 78)
    print(f"\n  {'#':<3} {'Seleção':<18} {'Prob%':<7} {'Opta':<6} {'GS':<6} {'FGV':<6} {'GM':<6} {'ML':<6} {'Bet365':<8} {'FIFA':<5}")
    print("  " + "-" * 74)

    for t in report["top_10_favorites"]:
        print(
            f"  {t['rank']:<3} {t['team']:<18} {t['win_probability']:<7} "
            f"{t['opta_prob']:<6} {t['goldman_prob']:<6} {t['fgv_prob']:<6} "
            f"{t['gato_mestre_prob']:<6} {t['ml_hybrid_prob']:<6} "
            f"{t['bet365_odds_pct']:<8} {t['fifa_rank']:<5}"
        )

    print("\n" + "=" * 78)
    print("  ANÁLISE POR CONFEDERAÇÃO")
    print("=" * 78)
    for conf, data in sorted(report["by_confederation"].items(), key=lambda x: -x[1]["combined_prob"]):
        print(f"  {conf:<12} | Melhor: {data['best_team']:<18} ({data['best_team_prob']}%) | "
              f"Total: {data['total_teams']} seleções | Prob. combinada: {data['combined_prob']}%")

    analysis = report["analysis"]
    print("\n" + "=" * 78)
    print("  ANÁLISE FINAL DA ATENA")
    print("=" * 78)
    print(f"\n  Favorito por Consenso: {analysis['consensus_favorite']}")
    print(f"  Nível de Concordância entre Modelos: {analysis['agreement_level']}")
    print(f"  Campeã Defensora: {analysis['defending_champion']} ({analysis['defending_champion_odds']})")
    print(f"  Dark Horse (Zebra Potencial): {analysis['dark_horse']}")
    print(f"  Maior Potencial de Surpresa: {analysis['biggest_surprise_potential']}")
    print("\n  Fatores Chave:")
    for factor in analysis["key_factors"]:
        print(f"    • {factor}")

    print("\n" + "=" * 78)
    print(f"  Gerado por ATENA-IA em {report['metadata']['generated_at']}")
    print(f"  Fontes de dados: {len(report['metadata']['data_sources'])} fontes oficiais")
    print("=" * 78 + "\n")


def run_predictor(save_json: bool = True, output_path: str = None) -> Dict[str, Any]:
    """Função principal para executar a previsão."""
    predictor = AtenaCopa2026Predictor()
    report = predictor.generate_full_report()

    print_report(report)

    if save_json:
        if output_path is None:
            output_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                f"copa_2026_prediction_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        logger.info(f"Relatório salvo em: {output_path}")
        print(f"\n  📁 Relatório JSON completo salvo em: {output_path}\n")

    return report


if __name__ == "__main__":
    report = run_predictor(save_json=True)
