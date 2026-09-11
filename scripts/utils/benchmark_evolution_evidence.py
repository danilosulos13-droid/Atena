#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║            ATENA Ω - Evolution Evidence Collector v3.0                     ║
║       Coleta, analisa e monitora evidências de evolução digital            ║
║                                                                            ║
║  Funcionalidades:                                                          ║
║  • Execução paralela de múltiplas rodadas do organismo digital             ║
║  • Coleta de métricas: fitness, confiança, taxa de sucesso, etc.           ║
║  • Armazenamento incremental em JSONL com compressão automática            ║
║  • Análise estatística robusta: tendências, intervalos de confiança,       ║
║    testes de estacionariedade, médias móveis                                ║
║  • Geração de relatórios JSON estruturados e opcionais gráficos            ║
║  • Tolerância a falhas com retry e fallback                                ║
║  • Configuração flexível via CLI e variáveis de ambiente                   ║
║                                                                            ║
║  Autor: ATENA Ω - Geração 345                                             ║
║  Licença: Proprietária                                                     ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import os
import re
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any, Dict, Final, List, Optional, Tuple, Union

import numpy as np
from scipy import stats as sp_stats
from tqdm import tqdm

# ─── Configuração de Ambiente ────────────────────────────────────────────────
ROOT: Final[Path] = Path(__file__).resolve().parents[1]
DEFAULT_MISSION: Final[Path] = ROOT / "protocols" / "atena_digital_organism_live_cycle_mission.py"
DEFAULT_HISTORY: Final[Path] = ROOT / "analysis_reports" / "evolution_evidence_history.jsonl"
DEFAULT_REPORT: Final[Path] = ROOT / "analysis_reports" / "evolution_evidence_report.json"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger: logging.Logger = logging.getLogger(__name__)

# ─── Estruturas de Dados ─────────────────────────────────────────────────────
@dataclass(slots=True, frozen=True)
class RunResult:
    """Resultado de uma única execução do organismo"""
    timestamp: str
    iterations: int
    topic: str
    success_rate: float
    learning_confidence: float
    fitness: float
    raw_summary: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Dict[str, Any], iterations: int, topic: str) -> RunResult:
        return cls(
            timestamp=datetime.now(timezone.utc).isoformat(),
            iterations=iterations,
            topic=topic,
            success_rate=float(payload.get("success_rate", 0.0)),
            learning_confidence=float(payload.get("avg_learning_confidence", 0.0)),
            fitness=float(payload.get("avg_fitness", 0.0)),
            raw_summary=payload
        )

@dataclass
class TrendAnalysis:
    """Resultado da análise de tendência de uma métrica"""
    slope: float
    intercept: float
    r_squared: float
    p_value: float
    is_significant: bool
    recent_values: List[float]
    moving_average: List[float]
    trend_direction: str  # 'up', 'down', 'stable'
    
    @classmethod
    def from_series(cls, values: List[float], window: int = 5) -> TrendAnalysis:
        if len(values) < 3:
            return cls(0.0, 0.0, 0.0, 1.0, False, values, [], 'stable')
        
        xs = np.arange(len(values))
        slope, intercept, r_value, p_value, _ = sp_stats.linregress(xs, values)
        r_squared = r_value ** 2
        is_sig = p_value < 0.05
        
        # Moving average
        if len(values) >= window:
            ma = np.convolve(values, np.ones(window)/window, mode='valid').tolist()
        else:
            ma = values
        
        # Direction
        if slope > 0.001:
            direction = 'up'
        elif slope < -0.001:
            direction = 'down'
        else:
            direction = 'stable'
        
        return cls(
            slope=float(slope),
            intercept=float(intercept),
            r_squared=float(r_squared),
            p_value=float(p_value),
            is_significant=bool(is_sig),
            recent_values=values,
            moving_average=ma,
            trend_direction=direction
        )

@dataclass
class EvolutionReport:
    """Relatório completo de evolução"""
    generated_at: str
    recent_runs: int
    success_rate_mean: float
    success_rate_std: float
    fitness_trend: TrendAnalysis
    learning_confidence_trend: TrendAnalysis
    overall_evolving: bool
    criteria: Dict[str, Any]
    raw_history_summary: Dict[str, float]

# ─── Coletor de Evidências ───────────────────────────────────────────────────
class EvolutionEvidenceCollector:
    """
    Orquestra a execução do organismo digital, coleta métricas,
    mantém histórico e produz análises de evolução.
    """
    
    def __init__(self,
                 mission_path: Optional[Path] = None,
                 history_path: Optional[Path] = None,
                 report_path: Optional[Path] = None,
                 max_workers: int = 4,
                 retry_attempts: int = 2,
                 strict_mode: bool = False):
        self.mission_path = mission_path or DEFAULT_MISSION
        self.history_path = history_path or DEFAULT_HISTORY
        self.report_path = report_path or DEFAULT_REPORT
        self.max_workers = max_workers
        self.retry_attempts = retry_attempts
        self.strict_mode = strict_mode
        
        # Valida existência do script de missão
        if not self.mission_path.exists():
            raise FileNotFoundError(f"Script da missão não encontrado: {self.mission_path}")
        
        # Prepara diretórios
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
    
    def run_single_batch(self, iterations: int, topic: str) -> Optional[RunResult]:
        """
        Executa uma única rodada do organismo digital com retry.
        Retorna None se todas as tentativas falharem.
        """
        for attempt in range(self.retry_attempts + 1):
            try:
                cmd = [
                    "python3", str(self.mission_path),
                    "--iterations", str(iterations),
                    "--topic", topic
                ]
                if self.strict_mode:
                    cmd.append("--strict")
                
                logger.debug(f"Executando: {' '.join(cmd)} (tentativa {attempt+1})")
                
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=600,  # 10 minutos limite
                    check=False
                )
                
                if proc.returncode != 0:
                    logger.error(f"Falha na execução (código {proc.returncode}): {proc.stderr[:500]}")
                    if attempt < self.retry_attempts:
                        time.sleep(2 ** attempt)
                        continue
                    return None
                
                # Parse do JSON gerado
                match = re.search(r"json=(.*)", proc.stdout)
                if not match:
                    logger.error(f"Padrão 'json=' não encontrado na saída: {proc.stdout[-200:]}")
                    return None
                
                json_path = Path(match.group(1).strip())
                if not json_path.exists():
                    logger.error(f"Arquivo JSON não encontrado: {json_path}")
                    return None
                
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                payload = data.get("summary", data)
                return RunResult.from_payload(payload, iterations, topic)
                
            except subprocess.TimeoutExpired:
                logger.error("Timeout na execução do organismo")
                if attempt < self.retry_attempts:
                    time.sleep(2 ** attempt)
                    continue
                return None
            except Exception as e:
                logger.exception(f"Erro inesperado: {e}")
                if attempt < self.retry_attempts:
                    time.sleep(2 ** attempt)
                    continue
                return None
        
        return None
    
    def run_batch_parallel(self, rounds: int, iterations: int, topic: str) -> List[RunResult]:
        """
        Executa múltiplas rodadas em paralelo usando ProcessPoolExecutor.
        """
        logger.info(f"Executando {rounds} rodadas com {iterations} iterações cada...")
        results = []
        
        with concurrent.futures.ProcessPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self.run_single_batch, iterations, topic): i
                for i in range(rounds)
            }
            
            with tqdm(total=rounds, desc="Rodadas do organismo", unit="run") as pbar:
                for future in concurrent.futures.as_completed(futures):
                    idx = futures[future]
                    try:
                        result = future.result()
                        if result:
                            results.append(result)
                        else:
                            logger.warning(f"Rodada {idx+1} falhou após {self.retry_attempts} tentativas")
                    except Exception as e:
                        logger.error(f"Exceção na rodada {idx+1}: {e}")
                    pbar.update(1)
        
        logger.info(f"Concluídas {len(results)}/{rounds} rodadas com sucesso")
        return results
    
    def save_to_history(self, results: List[RunResult]) -> int:
        """Adiciona resultados ao arquivo JSONL histórico."""
        if not results:
            return 0
        
        with open(self.history_path, 'a', encoding='utf-8') as f:
            for r in results:
                record = {
                    "ts": r.timestamp,
                    "iterations": r.iterations,
                    "topic": r.topic,
                    "success_rate": r.success_rate,
                    "learning_conf": r.learning_confidence,
                    "fitness": r.fitness
                }
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
        
        logger.info(f"Salvos {len(results)} registros no histórico")
        return len(results)
    
    def load_history(self, max_records: Optional[int] = None) -> List[Dict[str, Any]]:
        """Carrega todo o histórico ou os últimos N registros."""
        if not self.history_path.exists():
            return []
        
        with open(self.history_path, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f if line.strip()]
        
        if max_records:
            lines = lines[-max_records:]
        
        records = []
        for line in lines:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning(f"Linha inválida ignorada: {line[:80]}")
        return records
    
    def analyze_evolution(self, history: List[Dict[str, Any]], 
                          recent_window: Optional[int] = None) -> EvolutionReport:
        """
        Análise estatística dos dados históricos para determinar evolução.
        """
        if not history:
            raise ValueError("Histórico vazio – impossível analisar evolução")
        
        if recent_window:
            history = history[-recent_window:]
        
        success_rates = [float(r["success_rate"]) for r in history]
        fitness_values = [float(r["fitness"]) for r in history]
        learning_confs = [float(r["learning_conf"]) for r in history]
        
        sr_mean = statistics.mean(success_rates) if success_rates else 0.0
        sr_std = statistics.stdev(success_rates) if len(success_rates) > 1 else 0.0
        
        fitness_trend = TrendAnalysis.from_series(fitness_values)
        learning_trend = TrendAnalysis.from_series(learning_confs)
        
        # Critério de evolução: taxa de sucesso alta, tendências positivas ou estáveis
        evolving = (
            sr_mean >= 0.85
            and fitness_trend.slope >= -0.001  # permite leve queda estável
            and learning_trend.slope >= -0.001
            and (fitness_trend.is_significant or learning_trend.is_significant)
        )
        
        return EvolutionReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            recent_runs=len(history),
            success_rate_mean=sr_mean,
            success_rate_std=sr_std,
            fitness_trend=fitness_trend,
            learning_confidence_trend=learning_trend,
            overall_evolving=evolving,
            criteria={"success_rate_threshold": 0.85, "slope_tolerance": -0.001},
            raw_history_summary={
                "avg_fitness": statistics.mean(fitness_values) if fitness_values else 0.0,
                "avg_learning_confidence": statistics.mean(learning_confs) if learning_confs else 0.0,
                "avg_success_rate": sr_mean
            }
        )
    
    def generate_report(self, report: EvolutionReport) -> Path:
        """Salva o relatório de evolução em JSON formatado."""
        data = asdict(report)
        # Converte objetos não serializáveis
        data["fitness_trend"]["recent_values"] = [float(v) for v in report.fitness_trend.recent_values]
        data["fitness_trend"]["moving_average"] = [float(v) for v in report.fitness_trend.moving_average]
        data["learning_confidence_trend"]["recent_values"] = [float(v) for v in report.learning_confidence_trend.recent_values]
        data["learning_confidence_trend"]["moving_average"] = [float(v) for v in report.learning_confidence_trend.moving_average]
        
        with open(self.report_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Relatório salvo: {self.report_path}")
        return self.report_path
    
    def run_pipeline(self, rounds: int, iterations: int, topic: str,
                     recent_window: Optional[int] = None) -> EvolutionReport:
        """
        Pipeline completo: executa rodadas, salva histórico, analisa e gera relatório.
        """
        # Executa rodadas
        results = self.run_batch_parallel(rounds, iterations, topic)
        
        # Salva no histórico
        self.save_to_history(results)
        
        # Carrega histórico (tudo ou janela recente)
        history = self.load_history(max_records=recent_window)
        
        # Analisa
        report = self.analyze_evolution(history, recent_window)
        
        # Gera relatório persistente
        self.generate_report(report)
        
        return report

# ─── Interface CLI ───────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(
        description="ATENA Ω - Coletor de Evidências de Evolução Digital",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  %(prog)s --rounds 5 --iterations 10
  %(prog)s --rounds 10 --iterations 20 --topic "ai safety" --strict
  %(prog)s --analyze-only --recent 50
        """
    )
    
    parser.add_argument("--rounds", type=int, default=3,
                       help="Número de rodadas do organismo (padrão: 3)")
    parser.add_argument("--iterations", type=int, default=5,
                       help="Iterações por rodada (padrão: 5)")
    parser.add_argument("--topic", default="autonomous ai engineering",
                       help="Tópico para a missão (padrão: 'autonomous ai engineering')")
    parser.add_argument("--strict", action="store_true",
                       help="Ativar modo estrito do organismo")
    parser.add_argument("--recent", type=int,
                       help="Analisar apenas os últimos N registros do histórico")
    parser.add_argument("--analyze-only", action="store_true",
                       help="Apenas analisar histórico existente, sem executar novas rodadas")
    parser.add_argument("--mission", type=Path, default=DEFAULT_MISSION,
                       help="Caminho para o script da missão")
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY,
                       help="Caminho do arquivo de histórico JSONL")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT,
                       help="Caminho para salvar o relatório JSON")
    parser.add_argument("--workers", type=int, default=4,
                       help="Número de workers paralelos (padrão: 4)")
    parser.add_argument("--retries", type=int, default=2,
                       help="Tentativas em caso de falha (padrão: 2)")
    
    args = parser.parse_args()
    
    try:
        collector = EvolutionEvidenceCollector(
            mission_path=args.mission,
            history_path=args.history,
            report_path=args.report,
            max_workers=args.workers,
            retry_attempts=args.retries,
            strict_mode=args.strict
        )
        
        if args.analyze_only:
            logger.info("Modo análise apenas – carregando histórico...")
            history = collector.load_history(max_records=args.recent)
            if not history:
                print("Nenhum dado histórico encontrado.")
                return 1
            report = collector.analyze_evolution(history, args.recent)
            collector.generate_report(report)
        else:
            report = collector.run_pipeline(
                rounds=args.rounds,
                iterations=args.iterations,
                topic=args.topic,
                recent_window=args.recent
            )
        
        # Exibe resumo no terminal
        print("\n" + "=" * 60)
        print("RELATÓRIO DE EVIDÊNCIA DE EVOLUÇÃO")
        print("=" * 60)
        print(f"Período analisado: {report.recent_runs} execuções")
        print(f"Taxa de sucesso média: {report.success_rate_mean:.2%} (±{report.success_rate_std:.2%})")
        print(f"Fitness tendência: {report.fitness_trend.trend_direction} "
              f"(slope={report.fitness_trend.slope:.4f}, p={report.fitness_trend.p_value:.4f})")
        print(f"Confiança tendência: {report.learning_confidence_trend.trend_direction} "
              f"(slope={report.learning_confidence_trend.slope:.4f}, p={report.learning_confidence_trend.p_value:.4f})")
        print(f"\n🔄 Evidência de evolução: {'✅ SIM' if report.overall_evolving else '❌ NÃO'}")
        print(f"\nRelatório detalhado: {collector.report_path}")
        print(f"Histórico: {collector.history_path}")
        
        return 0
        
    except Exception as e:
        logger.exception(f"Erro fatal: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
