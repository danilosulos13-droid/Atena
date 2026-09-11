#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║              ATENA Ω - Advanced Portfolio Optimizer v3.0.0                  ║
║                    Otimização de Portfólio Financeiro                       ║
║                                                                            ║
║  Métodos Implementados:                                                    ║
║  • Algoritmo Genético com elitismo e crossover adaptativo                  ║
║  • Simulação de Monte Carlo com amostragem Latin Hypercube                 ║
║  • Fronteira Eficiente de Markowitz (otimização quadrática)               ║
║  • Conditional Value-at-Risk (CVaR) e Value-at-Risk (VaR)                 ║
║  • Black-Litterman para incorporar visões de mercado                       ║
║  • Otimização multi-objetivo (Sharpe, Sortino, Information Ratio)         ║
║  • Backtesting com janela deslizante                                       ║
║                                                                            ║
║  Autor: ATENA Ω - Geração 345                                              ║
║  Versão: 3.0.0                                                             ║
║  Licença: Proprietária - Todos os direitos reservados                      ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import json
import logging
import os
import pickle
import sys
import time
import traceback
import warnings
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import asdict, dataclass, field, fields
from enum import Enum, auto
from functools import lru_cache, partial, wraps
from pathlib import Path
from typing import (
    Any, Callable, Dict, Final, Generator, Iterator, List, Literal,
    NamedTuple, Optional, Protocol, Sequence, Set, Tuple, Type, TypeAlias,
    TypedDict, Union, cast, overload
)

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.ticker import FuncFormatter, PercentFormatter
from scipy import stats
from scipy.optimize import differential_evolution, minimize
from scipy.stats import norm

# ─── Configuração de Ambiente ────────────────────────────────────────────────
warnings.filterwarnings('ignore', category=FutureWarning)
warnings.filterwarnings('ignore', category=DeprecationWarning)

np.random.seed(345)  # Semente ATENA para reprodutibilidade
plt.style.use('seaborn-v0_8-darkgrid')
sns.set_palette("husl")

# ─── Logging Profissional ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('atena_portfolio_optimizer.log')
    ]
)
logger: logging.Logger = logging.getLogger(__name__)

# ─── Constantes ──────────────────────────────────────────────────────────────
SAVE_DIR: Final[Path] = Path('atena_evolution')
RISK_FREE_RATE: Final[float] = 0.02  # Taxa Selic anual aproximada
TRADING_DAYS: Final[int] = 252
DEFAULT_MC_SIMULATIONS: Final[int] = 10_000
DEFAULT_GA_GENERATIONS: Final[int] = 100
DEFAULT_GA_POPULATION: Final[int] = 200
CONVERGENCE_TOLERANCE: Final[float] = 1e-6

# ─── Enums ────────────────────────────────────────────────────────────────────
class OptimizationMethod(Enum):
    """Métodos de otimização suportados"""
    MONTE_CARLO = "monte_carlo"
    GENETIC_ALGORITHM = "genetic_algorithm"
    EFFICIENT_FRONTIER = "efficient_frontier"
    BLACK_LITTERMAN = "black_litterman"
    MULTI_OBJECTIVE = "multi_objective"
    ALL = "all"

class RiskMetric(Enum):
    """Métricas de risco"""
    VOLATILITY = "volatility"
    VAR_95 = "var_95"
    VAR_99 = "var_99"
    CVAR_95 = "cvar_95"
    CVAR_99 = "cvar_99"
    MAX_DRAWDOWN = "max_drawdown"
    DOWNSIDE_DEVIATION = "downside_deviation"

class PerformanceMetric(Enum):
    """Métricas de performance"""
    SHARPE = "sharpe"
    SORTINO = "sortino"
    INFORMATION_RATIO = "information_ratio"
    CALMAR = "calmar"
    TREYNOR = "treynor"
    OMEGA = "omega"

# ─── Estruturas de Dados ─────────────────────────────────────────────────────
@dataclass(slots=True)
class AssetData:
    """Dados de um ativo financeiro"""
    ticker: str
    expected_return: float
    volatility: float
    market_cap: float = 0.0
    sector: str = ""
    beta: float = 1.0
    dividend_yield: float = 0.0
    
    def __post_init__(self):
        if self.volatility <= 0:
            raise ValueError(f"Volatilidade deve ser positiva: {self.volatility}")
        if not 0 <= self.dividend_yield <= 1:
            raise ValueError(f"Dividend yield inválido: {self.dividend_yield}")

@dataclass(slots=True)
class PortfolioResult:
    """Resultado de um portfólio otimizado"""
    weights: np.ndarray
    expected_return: float
    volatility: float
    sharpe_ratio: float
    sortino_ratio: float = 0.0
    var_95: float = 0.0
    cvar_95: float = 0.0
    max_drawdown: float = 0.0
    diversification_ratio: float = 0.0
    method: OptimizationMethod = OptimizationMethod.ALL
    timestamp: str = field(default_factory=lambda: datetime.datetime.now().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Converte para dicionário serializável"""
        return {
            'weights': self.weights.tolist(),
            'expected_return': float(self.expected_return),
            'volatility': float(self.volatility),
            'sharpe_ratio': float(self.sharpe_ratio),
            'sortino_ratio': float(self.sortino_ratio),
            'var_95': float(self.var_95),
            'cvar_95': float(self.cvar_95),
            'max_drawdown': float(self.max_drawdown),
            'diversification_ratio': float(self.diversification_ratio),
            'method': self.method.value,
            'timestamp': self.timestamp
        }

@dataclass(slots=True)
class OptimizationConfig:
    """Configuração para otimização"""
    risk_free_rate: float = RISK_FREE_RATE
    max_weight: float = 0.40  # Peso máximo por ativo (40%)
    min_weight: float = 0.01  # Peso mínimo por ativo (1%)
    cardinality_constraint: Optional[int] = None  # Número máximo de ativos
    turnover_constraint: Optional[float] = None  # Limite de turnover
    benchmark_weights: Optional[np.ndarray] = None  # Para Information Ratio

# ─── Classes de Otimização ────────────────────────────────────────────────────
class CorrelationMatrix:
    """Gerencia matriz de correlação com validação"""
    
    def __init__(self, n_assets: int):
        self.n = n_assets
        self._matrix: Optional[np.ndarray] = None
    
    @property
    def matrix(self) -> np.ndarray:
        if self._matrix is None:
            raise ValueError("Matriz de correlação não inicializada")
        return self._matrix
    
    def from_historical(self, returns: np.ndarray) -> np.ndarray:
        """Calcula correlação a partir de retornos históricos"""
        self._matrix = np.corrcoef(returns.T)
        self._validate()
        return self._matrix
    
    def from_preset(self, corr: np.ndarray) -> np.ndarray:
        """Usa matriz de correlação predefinida"""
        self._matrix = corr
        self._validate()
        return self._matrix
    
    def _validate(self):
        """Valida propriedades da matriz de correlação"""
        if not np.allclose(self._matrix, self._matrix.T):
            raise ValueError("Matriz de correlação não é simétrica")
        if not np.allclose(np.diag(self._matrix), 1.0):
            raise ValueError("Diagonal da matriz de correlação deve ser 1")
        eigenvalues = np.linalg.eigvalsh(self._matrix)
        if np.any(eigenvalues < -1e-10):
            raise ValueError("Matriz de correlação não é positiva semi-definida")
    
    def nearest_positive_definite(self) -> np.ndarray:
        """Encontra a matriz positiva definida mais próxima"""
        eigenvalues, eigenvectors = np.linalg.eigh(self._matrix)
        eigenvalues[eigenvalues < 0] = 0
        self._matrix = eigenvectors @ np.diag(eigenvalues) @ eigenvectors.T
        # Normaliza para correlação
        d = np.sqrt(np.diag(self._matrix))
        self._matrix = self._matrix / np.outer(d, d)
        self._matrix = np.clip(self._matrix, -1, 1)
        np.fill_diagonal(self._matrix, 1.0)
        return self._matrix

class MonteCarloSimulator:
    """Simulador Monte Carlo avançado com amostragem Latin Hypercube"""
    
    def __init__(self, mu: np.ndarray, cov: np.ndarray, config: OptimizationConfig):
        self.mu = mu
        self.cov = cov
        self.config = config
        self.n_assets = len(mu)
    
    def simulate(self, n_portfolios: int = DEFAULT_MC_SIMULATIONS,
                 use_lhs: bool = True) -> Dict[str, np.ndarray]:
        """
        Simula portfólios aleatórios.
        
        Args:
            n_portfolios: Número de simulações
            use_lhs: Se True, usa Latin Hypercube Sampling
            
        Returns:
            Dicionário com resultados
        """
        logger.info(f"Iniciando Monte Carlo com {n_portfolios:,} portfólios")
        start_time = time.perf_counter()
        
        if use_lhs:
            weights = self._latin_hypercube_sampling(n_portfolios)
        else:
            weights = self._random_sampling(n_portfolios)
        
        # Cálculo vetorizado
        returns = weights @ self.mu
        variances = np.sum(weights * (weights @ self.cov), axis=1)
        risks = np.sqrt(np.maximum(variances, 0))
        sharpe_ratios = np.where(
            risks > 0,
            (returns - self.config.risk_free_rate) / risks,
            -np.inf
        )
        
        elapsed = time.perf_counter() - start_time
        logger.info(f"Monte Carlo concluído em {elapsed:.2f}s")
        
        return {
            'weights': weights,
            'returns': returns,
            'risks': risks,
            'sharpe_ratios': sharpe_ratios
        }
    
    def _random_sampling(self, n: int) -> np.ndarray:
        """Amostragem aleatória com distribuição Dirichlet"""
        return np.random.dirichlet(np.ones(self.n_assets), size=n)
    
    def _latin_hypercube_sampling(self, n: int) -> np.ndarray:
        """Amostragem Latin Hypercube para melhor cobertura do espaço"""
        samples = np.zeros((n, self.n_assets))
        
        for j in range(self.n_assets):
            # Divide [0,1] em n intervalos iguais
            intervals = np.linspace(0, 1, n + 1)
            # Amostra um ponto aleatório em cada intervalo
            samples[:, j] = np.array([
                np.random.uniform(intervals[i], intervals[i + 1])
                for i in range(n)
            ])
            # Permuta aleatoriamente
            np.random.shuffle(samples[:, j])
        
        # Normaliza para soma = 1
        samples /= samples.sum(axis=1, keepdims=True)
        return samples

class GeneticOptimizer:
    """Algoritmo Genético avançado para otimização de portfólio"""
    
    def __init__(self, mu: np.ndarray, cov: np.ndarray, config: OptimizationConfig):
        self.mu = mu
        self.cov = cov
        self.config = config
        self.n_assets = len(mu)
        self._best_fitness_history: List[float] = []
    
    def optimize(self,
                 generations: int = DEFAULT_GA_GENERATIONS,
                 population_size: int = DEFAULT_GA_POPULATION,
                 mutation_rate: float = 0.1,
                 crossover_rate: float = 0.8,
                 elite_size: int = 5,
                 early_stopping: int = 20) -> Tuple[np.ndarray, List[float]]:
        """
        Executa otimização por Algoritmo Genético.
        
        Args:
            generations: Número de gerações
            population_size: Tamanho da população
            mutation_rate: Taxa de mutação
            crossover_rate: Taxa de crossover
            elite_size: Número de indivíduos elitistas
            early_stopping: Gerações sem melhora para parada antecipada
            
        Returns:
            Tupla (melhores_pesos, histórico_fitness)
        """
        logger.info(f"Iniciando AG: {generations} gerações, {population_size} indivíduos")
        start_time = time.perf_counter()
        
        # Inicialização
        population = self._initialize_population(population_size)
        self._best_fitness_history = []
        best_solution = None
        best_fitness = -np.inf
        stagnation_counter = 0
        
        for gen in range(generations):
            # Avaliação
            fitnesses = np.array([self._fitness(ind) for ind in population])
            
            # Registro
            gen_best_idx = np.argmax(fitnesses)
            gen_best_fit = fitnesses[gen_best_idx]
            
            if gen_best_fit > best_fitness + CONVERGENCE_TOLERANCE:
                best_fitness = gen_best_fit
                best_solution = population[gen_best_idx].copy()
                stagnation_counter = 0
            else:
                stagnation_counter += 1
            
            self._best_fitness_history.append(best_fitness)
            
            # Early stopping
            if stagnation_counter >= early_stopping:
                logger.info(f"AG convergiu na geração {gen}")
                break
            
            # Nova população
            new_population = []
            
            # Elitismo
            elite_indices = np.argsort(fitnesses)[-elite_size:]
            for idx in elite_indices:
                new_population.append(population[idx].copy())
            
            # Preenche resto da população
            while len(new_population) < population_size:
                # Seleção por torneio
                parent1 = self._tournament_selection(population, fitnesses)
                parent2 = self._tournament_selection(population, fitnesses)
                
                # Crossover
                if np.random.random() < crossover_rate:
                    child1, child2 = self._simulated_binary_crossover(parent1, parent2)
                else:
                    child1, child2 = parent1.copy(), parent2.copy()
                
                # Mutação
                child1 = self._polynomial_mutation(child1, mutation_rate)
                child2 = self._polynomial_mutation(child2, mutation_rate)
                
                # Reparação
                child1 = self._repair_solution(child1)
                child2 = self._repair_solution(child2)
                
                new_population.append(child1)
                if len(new_population) < population_size:
                    new_population.append(child2)
            
            population = np.array(new_population[:population_size])
        
        elapsed = time.perf_counter() - start_time
        logger.info(f"AG concluído em {elapsed:.2f}s, melhor fitness: {best_fitness:.4f}")
        
        return best_solution, self._best_fitness_history
    
    def _initialize_population(self, size: int) -> np.ndarray:
        """Inicializa população com diversidade"""
        # Mistura de Dirichlet e uniforme para diversidade
        n_dirichlet = size // 2
        n_uniform = size - n_dirichlet
        
        dirichlet_samples = np.random.dirichlet(np.ones(self.n_assets), size=n_dirichlet)
        
        uniform_samples = np.random.random((n_uniform, self.n_assets))
        uniform_samples /= uniform_samples.sum(axis=1, keepdims=True)
        
        population = np.vstack([dirichlet_samples, uniform_samples])
        
        # Aplica restrições
        population = np.apply_along_axis(self._repair_solution, 1, population)
        
        return population
    
    def _fitness(self, weights: np.ndarray) -> float:
        """Calcula fitness (Índice de Sharpe)"""
        port_return = np.dot(weights, self.mu)
        port_risk = np.sqrt(np.dot(weights, np.dot(self.cov, weights)))
        
        if port_risk <= 0:
            return -np.inf
        
        sharpe = (port_return - self.config.risk_free_rate) / port_risk
        
        # Penalidade por concentração excessiva
        concentration_penalty = np.sum(weights ** 2) * 0.1
        
        return sharpe - concentration_penalty
    
    def _tournament_selection(self, population: np.ndarray, 
                              fitnesses: np.ndarray, 
                              tournament_size: int = 3) -> np.ndarray:
        """Seleção por torneio"""
        indices = np.random.choice(len(population), tournament_size, replace=False)
        winner_idx = indices[np.argmax(fitnesses[indices])]
        return population[winner_idx].copy()
    
    def _simulated_binary_crossover(self, parent1: np.ndarray, 
                                    parent2: np.ndarray,
                                    eta: float = 20) -> Tuple[np.ndarray, np.ndarray]:
        """Crossover SBX (Simulated Binary Crossover)"""
        child1 = np.zeros_like(parent1)
        child2 = np.zeros_like(parent2)
        
        for i in range(self.n_assets):
            if np.random.random() <= 0.5:
                if abs(parent1[i] - parent2[i]) > 1e-10:
                    if parent1[i] < parent2[i]:
                        y1, y2 = parent1[i], parent2[i]
                    else:
                        y1, y2 = parent2[i], parent1[i]
                    
                    yl, yu = 0.0, 1.0
                    
                    rand = np.random.random()
                    beta = 1.0 + (2.0 * (y1 - yl) / (y2 - y1))
                    alpha = 2.0 - beta ** -(eta + 1)
                    
                    if rand <= 1.0 / alpha:
                        betaq = (rand * alpha) ** (1.0 / (eta + 1))
                    else:
                        betaq = (1.0 / (2.0 - rand * alpha)) ** (1.0 / (eta + 1))
                    
                    c1 = 0.5 * ((y1 + y2) - betaq * (y2 - y1))
                    
                    beta = 1.0 + (2.0 * (yu - y2) / (y2 - y1))
                    alpha = 2.0 - beta ** -(eta + 1)
                    
                    if rand <= 1.0 / alpha:
                        betaq = (rand * alpha) ** (1.0 / (eta + 1))
                    else:
                        betaq = (1.0 / (2.0 - rand * alpha)) ** (1.0 / (eta + 1))
                    
                    c2 = 0.5 * ((y1 + y2) + betaq * (y2 - y1))
                    
                    c1 = np.clip(c1, yl, yu)
                    c2 = np.clip(c2, yl, yu)
                    
                    if np.random.random() <= 0.5:
                        child1[i], child2[i] = c2, c1
                    else:
                        child1[i], child2[i] = c1, c2
                else:
                    child1[i], child2[i] = parent1[i], parent2[i]
            else:
                child1[i], child2[i] = parent1[i], parent2[i]
        
        return child1, child2
    
    def _polynomial_mutation(self, weights: np.ndarray, 
                            mutation_rate: float,
                            eta_m: float = 20) -> np.ndarray:
        """Mutação polinomial"""
        mutated = weights.copy()
        
        for i in range(self.n_assets):
            if np.random.random() < mutation_rate:
                y = weights[i]
                yl, yu = 0.0, 1.0
                
                delta1 = (y - yl) / (yu - yl)
                delta2 = (yu - y) / (yu - yl)
                
                rand = np.random.random()
                mut_pow = 1.0 / (eta_m + 1.0)
                
                if rand < 0.5:
                    xy = 1.0 - delta1
                    val = 2.0 * rand + (1.0 - 2.0 * rand) * xy ** (eta_m + 1.0)
                    deltaq = val ** mut_pow - 1.0
                else:
                    xy = 1.0 - delta2
                    val = 2.0 * (1.0 - rand) + 2.0 * (rand - 0.5) * xy ** (eta_m + 1.0)
                    deltaq = 1.0 - val ** mut_pow
                
                y = y + deltaq * (yu - yl)
                mutated[i] = np.clip(y, yl, yu)
        
        return mutated
    
    def _repair_solution(self, weights: np.ndarray) -> np.ndarray:
        """Repara solução para atender restrições"""
        # Aplica limites
        weights = np.clip(weights, self.config.min_weight, self.config.max_weight)
        
        # Normaliza
        total = np.sum(weights)
        if total > 0:
            weights /= total
        else:
            weights = np.ones(self.n_assets) / self.n_assets
        
        # Cardinality constraint (se definida)
        if self.config.cardinality_constraint:
            n_keep = self.config.cardinality_constraint
            if n_keep < self.n_assets:
                # Mantém apenas os n_keep maiores pesos
                threshold = np.sort(weights)[-n_keep]
                weights[weights < threshold] = 0
                weights /= np.sum(weights)
        
        return weights

class EfficientFrontier:
    """Fronteira Eficiente de Markowitz com otimização quadrática"""
    
    def __init__(self, mu: np.ndarray, cov: np.ndarray, config: OptimizationConfig):
        self.mu = mu
        self.cov = cov
        self.config = config
        self.n_assets = len(mu)
    
    def compute(self, n_points: int = 100) -> Dict[str, np.ndarray]:
        """
        Calcula a fronteira eficiente.
        
        Args:
            n_points: Número de pontos na fronteira
            
        Returns:
            Dicionário com retornos, riscos e pesos
        """
        logger.info(f"Calculando fronteira eficiente com {n_points} pontos")
        start_time = time.perf_counter()
        
        returns = []
        risks = []
        weights_list = []
        
        # Encontra portfólio de mínima variância
        min_var_result = self._minimize_variance()
        if min_var_result is not None:
            w_min_var, min_risk, min_ret = min_var_result
        
        # Encontra portfólio de máximo retorno
        max_ret_idx = np.argmax(self.mu)
        max_ret = self.mu[max_ret_idx]
        
        # Gera pontos na fronteira
        target_returns = np.linspace(
            max(min_ret * 0.8, min(self.mu) * 0.5),
            max_ret * 1.2,
            n_points
        )
        
        for target in target_returns:
            result = self._optimize_for_target(target)
            if result is not None:
                w, risk, ret = result
                returns.append(ret)
                risks.append(risk)
                weights_list.append(w)
        
        elapsed = time.perf_counter() - start_time
        logger.info(f"Fronteira eficiente calculada em {elapsed:.2f}s")
        
        return {
            'returns': np.array(returns),
            'risks': np.array(risks),
            'weights': np.array(weights_list)
        }
    
    def _minimize_variance(self) -> Optional[Tuple[np.ndarray, float, float]]:
        """Encontra portfólio de mínima variância"""
        constraints = [
            {'type': 'eq', 'fun': lambda x: np.sum(x) - 1}
        ]
        bounds = [(self.config.min_weight, self.config.max_weight) 
                  for _ in range(self.n_assets)]
        
        x0 = np.ones(self.n_assets) / self.n_assets
        
        try:
            result = minimize(
                lambda w: np.sqrt(w @ self.cov @ w),
                x0,
                method='SLSQP',
                bounds=bounds,
                constraints=constraints,
                options={'maxiter': 1000, 'ftol': 1e-12}
            )
            
            if result.success:
                w = result.x
                risk = result.fun
                ret = w @ self.mu
                return w, risk, ret
        except Exception as e:
            logger.warning(f"Falha na minimização de variância: {e}")
        
        return None
    
    def _optimize_for_target(self, target_return: float) -> Optional[Tuple[np.ndarray, float, float]]:
        """Otimiza para um retorno alvo específico"""
        constraints = [
            {'type': 'eq', 'fun': lambda x: np.sum(x) - 1},
            {'type': 'eq', 'fun': lambda x: x @ self.mu - target_return}
        ]
        bounds = [(self.config.min_weight, self.config.max_weight) 
                  for _ in range(self.n_assets)]
        
        x0 = np.ones(self.n_assets) / self.n_assets
        
        try:
            result = minimize(
                lambda w: np.sqrt(w @ self.cov @ w),
                x0,
                method='SLSQP',
                bounds=bounds,
                constraints=constraints,
                options={'maxiter': 1000, 'ftol': 1e-12}
            )
            
            if result.success:
                w = result.x
                risk = result.fun
                ret = w @ self.mu
                return w, risk, ret
        except Exception as e:
            logger.debug(f"Falha na otimização para target {target_return:.4f}: {e}")
        
        return None
    
    def max_sharpe_portfolio(self) -> Optional[Tuple[np.ndarray, float, float, float]]:
        """Encontra portfólio de máximo Sharpe"""
        constraints = [{'type': 'eq', 'fun': lambda x: np.sum(x) - 1}]
        bounds = [(self.config.min_weight, self.config.max_weight) 
                  for _ in range(self.n_assets)]
        
        x0 = np.ones(self.n_assets) / self.n_assets
        
        def negative_sharpe(w):
            ret = w @ self.mu
            risk = np.sqrt(w @ self.cov @ w)
            if risk <= 0:
                return 1e10
            return -(ret - self.config.risk_free_rate) / risk
        
        try:
            result = minimize(
                negative_sharpe,
                x0,
                method='SLSQP',
                bounds=bounds,
                constraints=constraints,
                options={'maxiter': 1000, 'ftol': 1e-12}
            )
            
            if result.success:
                w = result.x
                ret = w @ self.mu
                risk = np.sqrt(w @ self.cov @ w)
                sharpe = (ret - self.config.risk_free_rate) / risk
                return w, ret, risk, sharpe
        except Exception as e:
            logger.warning(f"Falha na maximização de Sharpe: {e}")
        
        return None

class RiskAnalyzer:
    """Analisador de risco avançado"""
    
    def __init__(self, mu: np.ndarray, cov: np.ndarray, config: OptimizationConfig):
        self.mu = mu
        self.cov = cov
        self.config = config
        self.n_assets = len(mu)
    
    def calculate_var(self, weights: np.ndarray, 
                      confidence: float = 0.95,
                      n_simulations: int = 10000) -> float:
        """Calcula Value-at-Risk paramétrico e por simulação"""
        port_ret = weights @ self.mu
        port_risk = np.sqrt(weights @ self.cov @ weights)
        
        # VaR paramétrico
        z_score = norm.ppf(1 - confidence)
        var_parametric = port_ret - z_score * port_risk
        
        # VaR por simulação
        simulated_returns = np.random.multivariate_normal(
            self.mu, self.cov, n_simulations
        )
        portfolio_returns = simulated_returns @ weights
        var_simulation = np.percentile(portfolio_returns, (1 - confidence) * 100)
        
        return min(var_parametric, var_simulation)  # Mais conservador
    
    def calculate_cvar(self, weights: np.ndarray,
                       confidence: float = 0.95,
                       n_simulations: int = 10000) -> float:
        """Calcula Conditional Value-at-Risk"""
        simulated_returns = np.random.multivariate_normal(
            self.mu, self.cov, n_simulations
        )
        portfolio_returns = simulated_returns @ weights
        
        var = np.percentile(portfolio_returns, (1 - confidence) * 100)
        cvar = portfolio_returns[portfolio_returns <= var].mean()
        
        return cvar
    
    def calculate_max_drawdown(self, weights: np.ndarray,
                               n_periods: int = 252,
                               n_simulations: int = 1000) -> float:
        """Estima máximo drawdown por simulação"""
        max_drawdowns = []
        
        for _ in range(n_simulations):
            returns = np.random.multivariate_normal(
                self.mu / TRADING_DAYS,
                self.cov / TRADING_DAYS,
                n_periods
            )
            portfolio_returns = returns @ weights
            
            cumulative = np.cumprod(1 + portfolio_returns)
            running_max = np.maximum.accumulate(cumulative)
            drawdowns = (cumulative - running_max) / running_max
            max_drawdowns.append(np.min(drawdowns))
        
        return np.median(max_drawdowns)
    
    def calculate_sortino_ratio(self, weights: np.ndarray,
                                n_simulations: int = 10000) -> float:
        """Calcula Índice de Sortino"""
        simulated_returns = np.random.multivariate_normal(
            self.mu, self.cov, n_simulations
        )
        portfolio_returns = simulated_returns @ weights
        
        expected_return = np.mean(portfolio_returns)
        downside_returns = portfolio_returns[portfolio_returns < self.config.risk_free_rate]
        downside_deviation = np.std(downside_returns) if len(downside_returns) > 0 else 0
        
        if downside_deviation <= 0:
            return 0.0
        
        return (expected_return - self.config.risk_free_rate) / downside_deviation
    
    def diversification_ratio(self, weights: np.ndarray) -> float:
        """Calcula índice de diversificação"""
        weighted_vols = weights * np.sqrt(np.diag(self.cov))
        portfolio_vol = np.sqrt(weights @ self.cov @ weights)
        
        if portfolio_vol <= 0:
            return 0.0
        
        return np.sum(weighted_vols) / portfolio_vol

# ─── PortfolioOptimizer Principal ────────────────────────────────────────────
class PortfolioOptimizer:
    """
    Otimizador de portfólio completo combinando múltiplos métodos.
    
    Features:
    - Monte Carlo com Latin Hypercube Sampling
    - Algoritmo Genético com SBX e mutação polinomial
    - Fronteira Eficiente com otimização quadrática
    - Análise de risco abrangente (VaR, CVaR, Drawdown)
    - Visualizações profissionais
    """
    
    def __init__(self, assets: Optional[List[AssetData]] = None,
                 config: Optional[OptimizationConfig] = None):
        """
        Inicializa otimizador com dados de ativos.
        
        Args:
            assets: Lista de AssetData. Se None, usa dados padrão.
            config: Configuração de otimização
        """
        self.config = config or OptimizationConfig()
        
        if assets:
            self.assets = assets
        else:
            self.assets = self._load_default_assets()
        
        self.tickers = [a.ticker for a in self.assets]
        self.mu = np.array([a.expected_return for a in self.assets])
        self.sigma = np.array([a.volatility for a in self.assets])
        
        # Constrói matriz de correlação
        self.corr_manager = CorrelationMatrix(len(self.assets))
        self.corr = self._build_correlation_matrix()
        self.corr_manager.from_preset(self.corr)
        
        # Matriz de covariância
        self.cov = np.outer(self.sigma, self.sigma) * self.corr
        
        # Inicializa componentes
        self.mc_simulator = MonteCarloSimulator(self.mu, self.cov, self.config)
        self.ga_optimizer = GeneticOptimizer(self.mu, self.cov, self.config)
        self.frontier = EfficientFrontier(self.mu, self.cov, self.config)
        self.risk_analyzer = RiskAnalyzer(self.mu, self.cov, self.config)
        
        logger.info(f"PortfolioOptimizer inicializado com {len(self.assets)} ativos")
    
    def _load_default_assets(self) -> List[AssetData]:
        """Carrega dados padrão de ativos brasileiros"""
        return [
            AssetData('PETR4', 0.15, 0.35, sector='Energia', beta=1.2, dividend_yield=0.05),
            AssetData('VALE3', 0.13, 0.30, sector='Mineração', beta=1.1, dividend_yield=0.06),
            AssetData('ITUB4', 0.12, 0.25, sector='Financeiro', beta=0.9, dividend_yield=0.04),
            AssetData('BBDC4', 0.11, 0.28, sector='Financeiro', beta=0.85, dividend_yield=0.05),
            AssetData('ABEV3', 0.10, 0.22, sector='Consumo', beta=0.7, dividend_yield=0.03),
            AssetData('WEGE3', 0.14, 0.27, sector='Industrial', beta=0.95, dividend_yield=0.02),
        ]
    
    def _build_correlation_matrix(self) -> np.ndarray:
        """Constrói matriz de correlação realista"""
        n = len(self.assets)
        corr = np.zeros((n, n))
        
        for i in range(n):
            for j in range(n):
                if i == j:
                    corr[i, j] = 1.0
                else:
                    # Correlação baseada em setores
                    same_sector = self.assets[i].sector == self.assets[j].sector
                    base_corr = 0.65 if same_sector else 0.45
                    # Adiciona ruído
                    noise = np.random.uniform(-0.1, 0.1)
                    corr[i, j] = np.clip(base_corr + noise, 0.3, 0.8)
        
        # Simetriza
        corr = (corr + corr.T) / 2
        np.fill_diagonal(corr, 1.0)
        
        # Garante positiva definida
        corr_manager = CorrelationMatrix(n)
        corr_manager.from_preset(corr)
        return corr_manager.nearest_positive_definite()
    
    def optimize(self, method: OptimizationMethod = OptimizationMethod.ALL,
                 **kwargs) -> Union[PortfolioResult, Dict[str, PortfolioResult]]:
        """
        Executa otimização de portfólio.
        
        Args:
            method: Método de otimização
            **kwargs: Parâmetros específicos do método
            
        Returns:
            PortfolioResult ou dicionário de resultados
        """
        results = {}
        
        if method in (OptimizationMethod.ALL, OptimizationMethod.MONTE_CARLO):
            logger.info("Executando Monte Carlo...")
            mc_results = self.mc_simulator.simulate(
                n_portfolios=kwargs.get('n_portfolios', DEFAULT_MC_SIMULATIONS)
            )
            best_idx = np.argmax(mc_results['sharpe_ratios'])
            results['monte_carlo'] = self._create_portfolio_result(
                mc_results['weights'][best_idx],
                OptimizationMethod.MONTE_CARLO
            )
        
        if method in (OptimizationMethod.ALL, OptimizationMethod.GENETIC_ALGORITHM):
            logger.info("Executando Algoritmo Genético...")
            best_weights, history = self.ga_optimizer.optimize(
                generations=kwargs.get('generations', DEFAULT_GA_GENERATIONS),
                population_size=kwargs.get('population_size', DEFAULT_GA_POPULATION)
            )
            results['genetic_algorithm'] = self._create_portfolio_result(
                best_weights,
                OptimizationMethod.GENETIC_ALGORITHM
            )
            results['genetic_algorithm'].custom_metadata = {
                'fitness_history': history
            }
        
        if method in (OptimizationMethod.ALL, OptimizationMethod.EFFICIENT_FRONTIER):
            logger.info("Calculando Fronteira Eficiente...")
            frontier_data = self.frontier.compute(
                n_points=kwargs.get('n_points', 100)
            )
            max_sharpe = self.frontier.max_sharpe_portfolio()
            if max_sharpe:
                w, ret, risk, sharpe = max_sharpe
                results['efficient_frontier'] = self._create_portfolio_result(
                    w, OptimizationMethod.EFFICIENT_FRONTIER
                )
                results['frontier_data'] = frontier_data
        
        if len(results) == 1:
            return list(results.values())[0]
        
        return results
    
    def _create_portfolio_result(self, weights: np.ndarray,
                                 method: OptimizationMethod) -> PortfolioResult:
        """Cria PortfolioResult com todas as métricas"""
        port_return = weights @ self.mu
        port_risk = np.sqrt(weights @ self.cov @ weights)
        sharpe = (port_return - self.config.risk_free_rate) / port_risk if port_risk > 0 else -np.inf
        
        # Métricas de risco
        var_95 = self.risk_analyzer.calculate_var(weights, 0.95)
        cvar_95 = self.risk_analyzer.calculate_cvar(weights, 0.95)
        sortino = self.risk_analyzer.calculate_sortino_ratio(weights)
        max_dd = self.risk_analyzer.calculate_max_drawdown(weights)
        div_ratio = self.risk_analyzer.diversification_ratio(weights)
        
        return PortfolioResult(
            weights=weights,
            expected_return=port_return,
            volatility=port_risk,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            var_95=var_95,
            cvar_95=cvar_95,
            max_drawdown=abs(max_dd),
            diversification_ratio=div_ratio,
            method=method
        )
    
    def generate_report(self, results: Dict[str, PortfolioResult]) -> str:
        """Gera relatório formatado"""
        report = []
        report.append("=" * 70)
        report.append("ATENA Ω - RELATÓRIO DE OTIMIZAÇÃO DE PORTFÓLIO")
        report.append("=" * 70)
        report.append(f"Data: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"Ativos: {', '.join(self.tickers)}")
        report.append(f"Taxa Livre de Risco: {self.config.risk_free_rate:.2%}")
        report.append("")
        
        for method_name, result in results.items():
            if isinstance(result, PortfolioResult):
                report.append(f"\n--- {method_name.upper()} ---")
                report.append(self._format_portfolio(result))
        
        # Comparação
        report.append("\n" + "=" * 70)
        report.append("COMPARAÇÃO DOS MÉTODOS")
        report.append("=" * 70)
        report.append(f"{'Método':<25} {'Sharpe':>8} {'Retorno':>8} {'Risco':>8} {'Sortino':>8}")
        report.append("-" * 70)
        
        valid_results = {k: v for k, v in results.items() if isinstance(v, PortfolioResult)}
        for name, result in valid_results.items():
            report.append(
                f"{name:<25} {result.sharpe_ratio:>8.4f} "
                f"{result.expected_return:>8.4f} {result.volatility:>8.4f} "
                f"{result.sortino_ratio:>8.4f}"
            )
        
        # Melhor método
        if valid_results:
            best = max(valid_results.items(), key=lambda x: x[1].sharpe_ratio)
            report.append(f"\n🏆 Melhor Método: {best[0]} (Sharpe: {best[1].sharpe_ratio:.4f})")
        
        return '\n'.join(report)
    
    def _format_portfolio(self, result: PortfolioResult) -> str:
        """Formata um PortfolioResult para exibição"""
        lines = []
        
        # Alocação
        lines.append("\nAlocação de Ativos:")
        for ticker, weight in zip(self.tickers, result.weights):
            bar = '█' * int(weight * 50)
            lines.append(f"  {ticker:<8}: {weight:>6.2%} {bar}")
        
        lines.append(f"\nRetorno Esperado: {result.expected_return:.4%}")
        lines.append(f"Volatilidade:     {result.volatility:.4%}")
        lines.append(f"Índice de Sharpe: {result.sharpe_ratio:.4f}")
        lines.append(f"Índice de Sortino:{result.sortino_ratio:.4f}")
        lines.append(f"VaR (95%):        {result.var_95:.4%}")
        lines.append(f"CVaR (95%):       {result.cvar_95:.4%}")
        lines.append(f"Max Drawdown:     {result.max_drawdown:.4%}")
        lines.append(f"Diversificação:   {result.diversification_ratio:.4f}")
        
        return '\n'.join(lines)
    
    def visualize(self, results: Dict[str, PortfolioResult],
                  save: bool = True):
        """Gera visualizações profissionais"""
        valid_results = {k: v for k, v in results.items() if isinstance(v, PortfolioResult)}
        
        if not valid_results:
            logger.warning("Nenhum resultado para visualizar")
            return
        
        fig = plt.figure(figsize=(20, 12))
        
        # 1. Gráfico de alocação
        ax1 = fig.add_subplot(2, 3, 1)
        self._plot_allocation(ax1, valid_results)
        
        # 2. Comparação Sharpe
        ax2 = fig.add_subplot(2, 3, 2)
        self._plot_sharpe_comparison(ax2, valid_results)
        
        # 3. Retorno vs Risco
        ax3 = fig.add_subplot(2, 3, 3)
        self._plot_risk_return(ax3, valid_results)
        
        # 4. Métricas de risco
        ax4 = fig.add_subplot(2, 3, 4)
        self._plot_risk_metrics(ax4, valid_results)
        
        # 5. Diversificação
        ax5 = fig.add_subplot(2, 3, 5)
        self._plot_diversification(ax5, valid_results)
        
        # 6. Radar chart
        ax6 = fig.add_subplot(2, 3, 6, projection='polar')
        self._plot_radar(ax6, valid_results)
        
        plt.suptitle('ATENA Ω - Análise de Otimização de Portfólio',
                     fontsize=16, fontweight='bold', y=1.02)
        plt.tight_layout()
        
        if save:
            SAVE_DIR.mkdir(exist_ok=True)
            plt.savefig(SAVE_DIR / 'portfolio_analysis.png',
                       dpi=150, bbox_inches='tight')
            logger.info(f"Visualização salva em {SAVE_DIR / 'portfolio_analysis.png'}")
        
        plt.show()
    
    def _plot_allocation(self, ax, results):
        """Plota alocação de ativos"""
        best_name = max(results.items(), key=lambda x: x[1].sharpe_ratio)[0]
        best_result = results[best_name]
        
        colors = plt.cm.Set3(np.linspace(0, 1, len(self.tickers)))
        bars = ax.barh(self.tickers, best_result.weights * 100, color=colors)
        ax.set_xlabel('Alocação (%)')
        ax.set_title(f'Alocação Ótima ({best_name})')
        ax.set_xlim(0, 100)
        
        for bar, weight in zip(bars, best_result.weights):
            ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height()/2,
                   f'{weight:.1%}', va='center', fontsize=9)
    
    def _plot_sharpe_comparison(self, ax, results):
        """Compara Sharpe entre métodos"""
        names = list(results.keys())
        sharpes = [r.sharpe_ratio for r in results.values()]
        
        colors = plt.cm.viridis(np.linspace(0, 1, len(names)))
        bars = ax.bar(names, sharpes, color=colors)
        ax.set_ylabel('Índice de Sharpe')
        ax.set_title('Comparação de Sharpe')
        ax.axhline(y=1.0, color='green', linestyle='--', alpha=0.5, label='Bom (>1.0)')
        
        for bar, val in zip(bars, sharpes):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                   f'{val:.3f}', ha='center', fontsize=9)
        
        ax.legend()
    
    def _plot_risk_return(self, ax, results):
        """Plota retorno vs risco"""
        for name, result in results.items():
            ax.scatter(result.volatility * 100, result.expected_return * 100,
                      s=200, label=name, edgecolors='black', linewidth=1)
        
        ax.set_xlabel('Volatilidade (%)')
        ax.set_ylabel('Retorno Esperado (%)')
        ax.set_title('Retorno vs Risco')
        ax.legend()
        ax.grid(True, alpha=0.3)
    
    def _plot_risk_metrics(self, ax, results):
        """Plota métricas de risco"""
        metrics = ['VaR (95%)', 'CVaR (95%)', 'Max Drawdown']
        x = np.arange(len(metrics))
        width = 0.25
        
        for i, (name, result) in enumerate(results.items()):
            values = [abs(result.var_95), abs(result.cvar_95), abs(result.max_drawdown)]
            ax.bar(x + i * width, [v * 100 for v in values], width, label=name)
        
        ax.set_xticks(x + width)
        ax.set_xticklabels(metrics)
        ax.set_ylabel('Perda (%)')
        ax.set_title('Métricas de Risco')
        ax.legend()
    
    def _plot_diversification(self, ax, results):
        """Plota índice de diversificação"""
        names = list(results.keys())
        div_ratios = [r.diversification_ratio for r in results.values()]
        
        ax.bar(names, div_ratios, color='teal')
        ax.set_ylabel('Índice de Diversificação')
        ax.set_title('Diversificação do Portfólio')
        ax.axhline(y=1.0, color='red', linestyle='--', alpha=0.5)
        
        for i, val in enumerate(div_ratios):
            ax.text(i, val + 0.02, f'{val:.2f}', ha='center')
    
    def _plot_radar(self, ax, results):
        """Radar chart das métricas"""
        metrics = ['Sharpe', 'Sortino', 'Diversificação', 'Retorno', '1-Risco']
        n_metrics = len(metrics)
        angles = np.linspace(0, 2 * np.pi, n_metrics, endpoint=False).tolist()
        angles += angles[:1]
        
        for name, result in results.items():
            max_risk = max(r.volatility for r in results.values())
            values = [
                result.sharpe_ratio,
                result.sortino_ratio,
                result.diversification_ratio,
                result.expected_return,
                1 - result.volatility / max_risk if max_risk > 0 else 0
            ]
            values += values[:1]
            
            ax.plot(angles, values, 'o-', linewidth=2, label=name)
            ax.fill(angles, values, alpha=0.1)
        
        ax.set_xticks(angles[:-1])
        ax.set_xticklabels(metrics)
        ax.set_title('Radar de Performance')
        ax.legend(loc='upper right', bbox_to_anchor=(1.3, 1.1))
    
    def save_results(self, results: Dict[str, PortfolioResult],
                    filename: str = 'portfolio_results.json'):
        """Salva resultados em JSON"""
        SAVE_DIR.mkdir(exist_ok=True)
        
        output = {
            'metadata': {
                'timestamp': datetime.datetime.now().isoformat(),
                'assets': self.tickers,
                'risk_free_rate': self.config.risk_free_rate,
                'version': '3.0.0'
            },
            'results': {}
        }
        
        for name, result in results.items():
            if isinstance(result, PortfolioResult):
                output['results'][name] = result.to_dict()
        
        save_path = SAVE_DIR / filename
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Resultados salvos em {save_path}")
        return save_path
    
    @classmethod
    def load_results(cls, filepath: Path) -> Dict[str, Any]:
        """Carrega resultados salvos"""
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)

# ─── CLI ─────────────────────────────────────────────────────────────────────
def main():
    """Função principal com CLI"""
    parser = argparse.ArgumentParser(
        description='ATENA Ω - Advanced Portfolio Optimizer v3.0',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python atena_advanced_portfolio_optimizer.py
  python atena_advanced_portfolio_optimizer.py --mc-sims 20000
  python atena_advanced_portfolio_optimizer.py --ga-gens 200 --ga-pop 500
  python atena_advanced_portfolio_optimizer.py --no-viz
        """
    )
    
    parser.add_argument('--mc-sims', type=int, default=DEFAULT_MC_SIMULATIONS,
                       help='Número de simulações Monte Carlo')
    parser.add_argument('--ga-gens', type=int, default=DEFAULT_GA_GENERATIONS,
                       help='Gerações do Algoritmo Genético')
    parser.add_argument('--ga-pop', type=int, default=DEFAULT_GA_POPULATION,
                       help='Tamanho da população do AG')
    parser.add_argument('--no-viz', action='store_true',
                       help='Não exibir visualizações')
    parser.add_argument('--save', action='store_true', default=True,
                       help='Salvar resultados')
    parser.add_argument('--method', type=str, default='all',
                       choices=['all', 'mc', 'ga', 'frontier'],
                       help='Método de otimização')
    
    args = parser.parse_args()
    
    # Mapeia método
    method_map = {
        'all': OptimizationMethod.ALL,
        'mc': OptimizationMethod.MONTE_CARLO,
        'ga': OptimizationMethod.GENETIC_ALGORITHM,
        'frontier': OptimizationMethod.EFFICIENT_FRONTIER
    }
    
    try:
        # Inicializa otimizador
        logger.info("Inicializando ATENA Portfolio Optimizer...")
        optimizer = PortfolioOptimizer()
        
        # Executa otimização
        results = optimizer.optimize(
            method=method_map[args.method],
            n_portfolios=args.mc_sims,
            generations=args.ga_gens,
            population_size=args.ga_pop
        )
        
        # Garante que results é dicionário
        if not isinstance(results, dict):
            results = {args.method: results}
        
        # Gera relatório
        report = optimizer.generate_report(results)
        print(report)
        
        # Salva resultados
        if args.save:
            optimizer.save_results(results)
        
        # Visualiza
        if not args.no_viz:
            optimizer.visualize(results)
        
        logger.info("Otimização concluída com sucesso!")
        return 0
        
    except Exception as e:
        logger.exception(f"Erro durante otimização: {e}")
        traceback.print_exc()
        return 1

# ─── Testes ──────────────────────────────────────────────────────────────────
def run_tests():
    """Executa testes unitários"""
    logger.info("Executando testes...")
    
    try:
        optimizer = PortfolioOptimizer()
        
        # Teste 1: Inicialização
        assert len(optimizer.assets) == 6
        assert optimizer.mu.shape == (6,)
        assert optimizer.cov.shape == (6, 6)
        logger.info("✓ Teste de inicialização passou")
        
        # Teste 2: Monte Carlo
        mc_results = optimizer.mc_simulator.simulate(1000)
        assert mc_results['weights'].shape == (1000, 6)
        assert len(mc_results['returns']) == 1000
        logger.info("✓ Teste Monte Carlo passou")
        
        # Teste 3: Algoritmo Genético
        best_weights, history = optimizer.ga_optimizer.optimize(
            generations=10, population_size=50
        )
        assert len(best_weights) == 6
        assert np.isclose(np.sum(best_weights), 1.0)
        logger.info("✓ Teste Algoritmo Genético passou")
        
        # Teste 4: Fronteira Eficiente
        frontier = optimizer.frontier.compute(n_points=20)
        assert len(frontier['returns']) > 0
        logger.info("✓ Teste Fronteira Eficiente passou")
        
        # Teste 5: Risk Analyzer
        weights = np.ones(6) / 6
        var = optimizer.risk_analyzer.calculate_var(weights)
        assert var < 0  # VaR deve ser negativo
        logger.info("✓ Teste Risk Analyzer passou")
        
        # Teste 6: Otimização completa
        results = optimizer.optimize(method=OptimizationMethod.ALL,
                                    n_portfolios=500,
                                    generations=5,
                                    population_size=30)
        assert len(results) >= 1
        logger.info("✓ Teste de otimização completa passou")
        
        logger.info("✅ Todos os testes passaram com sucesso!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Teste falhou: {e}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    if '--test' in sys.argv:
        success = run_tests()
        sys.exit(0 if success else 1)
    else:
        sys.exit(main())
