#!/usr/bin/env python3
"""
ATENA Dynamic Evolution Optimizer v2.0 – Real Execution Engine

Recursos:
- Execução real de subprocessos (main.py, módulos, scripts)
- Análise detalhada de falhas (logs, exit codes, exceções)
- Auto‑correção de dependências e configurações
- Estratégias adaptativas baseadas em histórico
- Métricas em tempo real (duração, sucesso, tipo de erro)
- Persistência em SQLite (histórico, métricas, estratégias)
"""

import json
import os
import sys
import time
import subprocess
import shutil
import logging
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass, field, asdict
from collections import defaultdict
import threading
import queue
import signal

# Logging estruturado
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("AtenaEvoOptimizer")


@dataclass
class EvolutionMetrics:
    """Métricas reais de uma execução."""
    timestamp: str
    command: str
    exit_code: int
    duration_seconds: float
    stdout: str
    stderr: str
    error_type: Optional[str] = None   # "import_error", "timeout", "api_error", etc.
    success: bool = True


@dataclass
class StrategyConfig:
    """Configuração estratégica adaptativa."""
    retry_count: int = 3
    timeout_seconds: int = 300
    prioritize_modules: List[str] = field(default_factory=lambda: ["core", "api"])
    auto_fix_enabled: bool = True
    memory_limit_mb: int = 4096
    env_vars: Dict[str, str] = field(default_factory=dict)
    flags: List[str] = field(default_factory=list)  # ex: ["--debug", "--no-cache"]


class AtenaDynamicEvolutionOptimizer:
    """
    Otimizador dinâmico real – executa, analisa, aprende e evolui.
    """

    def __init__(self, root_path: Union[str, Path]):
        self.root = Path(root_path).resolve()
        self.db_path = self.root / "atena_evolution/evolution.db"
        self.strategy_file = self.root / "atena_evolution/current_strategy.json"
        self.log_dir = self.root / "atena_evolution/logs"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self.strategy = self._load_strategy()

    # ─── Banco de Dados ────────────────────────────────────────────────────

    def _init_db(self):
        """Cria tabelas para histórico e métricas reais."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    command TEXT,
                    exit_code INTEGER,
                    duration REAL,
                    success INTEGER,
                    error_type TEXT,
                    stdout TEXT,
                    stderr TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_executions_time ON executions(timestamp);
                CREATE INDEX IF NOT EXISTS idx_executions_success ON executions(success);

                CREATE TABLE IF NOT EXISTS strategies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    config_json TEXT
                );

                CREATE TABLE IF NOT EXISTS module_metrics (
                    module TEXT PRIMARY KEY,
                    last_success REAL,
                    last_failure REAL,
                    total_runs INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    avg_duration REAL DEFAULT 0.0
                );
            """)

    def _save_execution(self, metrics: EvolutionMetrics):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO executions 
                   (timestamp, command, exit_code, duration, success, error_type, stdout, stderr)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (metrics.timestamp, metrics.command, metrics.exit_code,
                 metrics.duration_seconds, int(metrics.success),
                 metrics.error_type, metrics.stdout[:10000], metrics.stderr[:10000])
            )

    def get_recent_failures(self, limit: int = 20) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM executions WHERE success = 0 ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    # ─── Estratégia ────────────────────────────────────────────────────────

    def _load_strategy(self) -> StrategyConfig:
        if self.strategy_file.exists():
            try:
                data = json.loads(self.strategy_file.read_text())
                return StrategyConfig(**data)
            except Exception:
                pass
        return StrategyConfig()

    def _save_strategy(self):
        self.strategy_file.write_text(
            json.dumps(asdict(self.strategy), indent=2, default=str)
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO strategies (timestamp, config_json) VALUES (?, ?)",
                (datetime.now(timezone.utc).isoformat(), json.dumps(asdict(self.strategy)))
            )

    # ─── Execução Real ────────────────────────────────────────────────────

    def _run_command(self, cmd: str, timeout: Optional[int] = None) -> EvolutionMetrics:
        """
        Executa um comando real, captura saída, mede tempo, detecta erros.
        """
        start = time.perf_counter()
        timeout = timeout or self.strategy.timeout_seconds
        env = os.environ.copy()
        env.update(self.strategy.env_vars)
        env["PYTHONUNBUFFERED"] = "1"

        logger.info(f"Executando: {cmd} (timeout={timeout}s)")

        try:
            process = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                preexec_fn=os.setsid if os.name != 'nt' else None,
            )
            try:
                stdout, stderr = process.communicate(timeout=timeout)
                exit_code = process.returncode
            except subprocess.TimeoutExpired:
                # Mata o processo e todos os filhos
                if os.name != 'nt':
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                else:
                    process.terminate()
                stdout, stderr = process.communicate()
                exit_code = -1  # timeout
                stderr = stderr + f"\n[TIMEOUT] Excedeu {timeout} segundos"
        except Exception as e:
            stdout, stderr = "", str(e)
            exit_code = -2

        duration = time.perf_counter() - start
        success = exit_code == 0

        # Classifica o tipo de erro
        error_type = self._classify_error(stderr, stdout, exit_code)

        metrics = EvolutionMetrics(
            timestamp=datetime.now(timezone.utc).isoformat(),
            command=cmd,
            exit_code=exit_code,
            duration_seconds=duration,
            stdout=stdout[:5000],
            stderr=stderr[:5000],
            error_type=error_type,
            success=success,
        )
        self._save_execution(metrics)
        logger.info(f"Comando finalizado em {duration:.2f}s | exit={exit_code} | {error_type or 'ok'}")
        return metrics

    def _classify_error(self, stderr: str, stdout: str, exit_code: int) -> Optional[str]:
        """Analisa stderr e exit code para classificar falhas reais."""
        if exit_code == 0:
            return None
        combined = (stderr + "\n" + stdout).lower()
        if "modulenotfounderror" in combined or "no module named" in combined:
            return "import_error"
        if "timeout" in combined or "timed out" in combined:
            return "timeout"
        if "apikey" in combined or "unauthorized" in combined or "403" in combined:
            return "auth_error"
        if "connection refused" in combined or "network" in combined:
            return "network_error"
        if "memoryerror" in combined or "memory" in combined:
            return "memory_error"
        if "syntaxerror" in combined or "indentationerror" in combined:
            return "syntax_error"
        if "permission denied" in combined:
            return "permission_error"
        return "unknown_error"

    # ─── Auto‑Correção ────────────────────────────────────────────────────

    def _auto_fix(self, error_type: str) -> bool:
        """Tenta corrigir automaticamente o erro."""
        if not self.strategy.auto_fix_enabled:
            return False
        logger.info(f"Tentando auto‑correção para erro: {error_type}")

        if error_type == "import_error":
            # Tenta instalar módulos faltantes (exemplo)
            missing = self._extract_missing_module()
            if missing:
                logger.info(f"Instalando módulo: {missing}")
                res = self._run_command(f"pip install {missing}", timeout=60)
                return res.success
        elif error_type == "timeout":
            # Aumenta timeout
            self.strategy.timeout_seconds += 60
            self._save_strategy()
            return True
        elif error_type == "memory_error":
            # Aumenta limite de memória
            self.strategy.memory_limit_mb += 1024
            self._save_strategy()
            return True
        elif error_type == "auth_error":
            # Sugerir ao usuário (log)
            logger.error("🔑 Erro de autenticação – verifique suas API keys.")
            return False
        return False

    def _extract_missing_module(self) -> Optional[str]:
        """Extrai nome do módulo ausente de stderr recente."""
        failures = self.get_recent_failures(limit=1)
        if not failures:
            return None
        stderr = failures[0].get("stderr", "")
        # Procura padrões: "No module named 'xxx'"
        import re
        match = re.search(r"No module named ['\"]([^'\"]+)['\"]", stderr)
        if match:
            return match.group(1)
        return None

    # ─── Evolução Dinâmica ───────────────────────────────────────────────

    def analyze_and_adapt(self):
        """Analisa falhas recentes e adapta a estratégia."""
        failures = self.get_recent_failures(limit=10)
        if not failures:
            logger.info("✅ Nenhuma falha recente. Estratégia mantida.")
            return

        # Contagem de tipos de erro
        error_counts = defaultdict(int)
        for f in failures:
            error_counts[f.get("error_type", "unknown")] += 1

        # Adaptação baseada no erro mais comum
        most_common = max(error_counts.items(), key=lambda x: x[1])
        error_type, count = most_common
        logger.info(f"🔍 Erro mais comum: {error_type} ({count} ocorrências)")

        if error_type == "timeout" and count >= 3:
            self.strategy.timeout_seconds += 120
            logger.info(f"⏱️ Aumentando timeout para {self.strategy.timeout_seconds}s")
        elif error_type == "import_error" and count >= 2:
            self.strategy.auto_fix_enabled = True
            self._auto_fix("import_error")
        elif error_type == "memory_error":
            self.strategy.memory_limit_mb += 512
            logger.info(f"🧠 Aumentando memória para {self.strategy.memory_limit_mb}MB")

        # Ajuste de retry
        if count > 5:
            self.strategy.retry_count += 1
            logger.info(f"🔄 Aumentando retry para {self.strategy.retry_count}")

        self._save_strategy()

    def execute_evolution_cycle(self, target_script: str = "main.py", args: str = "--once") -> Dict:
        """
        Executa um ciclo completo de evolução:
        - Roda o script alvo com a estratégia atual.
        - Analisa o resultado.
        - Aplica auto‑correção se falhar.
        - Adapta a estratégia para a próxima execução.
        """
        logger.info("🚀 Iniciando Ciclo de Auto-Evolução Dinâmica REAL")

        # Prepara comando com flags
        cmd = f"python {target_script} {args} {' '.join(self.strategy.flags)}"
        cmd = cmd.strip()

        # Executa com retry
        for attempt in range(1, self.strategy.retry_count + 1):
            logger.info(f"Tentativa {attempt}/{self.strategy.retry_count}")
            metrics = self._run_command(cmd, timeout=self.strategy.timeout_seconds)

            if metrics.success:
                logger.info("✅ Ciclo executado com sucesso!")
                break
            else:
                logger.warning(f"❌ Falha na tentativa {attempt}: {metrics.error_type}")
                if attempt < self.strategy.retry_count:
                    # Tenta auto‑corrigir
                    if self._auto_fix(metrics.error_type):
                        logger.info("🔧 Auto‑correção aplicada, re-tentando...")
                        continue
                    else:
                        logger.warning("⚠️ Auto‑correção não disponível ou falhou.")
                        break
                else:
                    logger.error("🚨 Todas as tentativas falharam.")

        # Análise pós‑execução
        self.analyze_and_adapt()

        # Gera relatório
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "strategy": asdict(self.strategy),
            "last_execution": {
                "success": metrics.success,
                "error_type": metrics.error_type,
                "duration": metrics.duration_seconds,
                "exit_code": metrics.exit_code,
            },
            "improvements": self._generate_improvements(metrics)
        }
        return report

    def _generate_improvements(self, last_metrics: EvolutionMetrics) -> List[str]:
        """Sugere melhorias reais baseadas no resultado."""
        improvements = []
        if not last_metrics.success:
            improvements.append(f"Corrigir erro: {last_metrics.error_type or 'desconhecido'}")
            if "timeout" in str(last_metrics.error_type):
                improvements.append("Aumentar timeout ou otimizar código")
            elif "import" in str(last_metrics.error_type):
                improvements.append("Verificar dependências e PYTHONPATH")
        else:
            if last_metrics.duration_seconds > self.strategy.timeout_seconds * 0.8:
                improvements.append("Reduzir timeout (execução está muito próxima do limite)")
            if last_metrics.exit_code == 0:
                improvements.append("Manter estratégia atual")
        return improvements

    def run_self_healing_loop(self, interval_seconds: int = 1800):
        """Loop contínuo de auto‑evolução (para execução em background)."""
        import time
        logger.info(f"🔄 Loop de auto‑evolução iniciado (intervalo {interval_seconds}s)")
        while True:
            self.execute_evolution_cycle()
            logger.info(f"⏳ Aguardando {interval_seconds}s até o próximo ciclo...")
            time.sleep(interval_seconds)


# ─── Ponto de entrada ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ATENA Real Evolution Optimizer")
    parser.add_argument("--root", default=".", help="Diretório raiz do projeto")
    parser.add_argument("--target", default="main.py", help="Script alvo para evolução")
    parser.add_argument("--args", default="--once", help="Argumentos para o script")
    parser.add_argument("--loop", action="store_true", help="Executar em loop contínuo")
    parser.add_argument("--interval", type=int, default=1800, help="Intervalo do loop (segundos)")
    args = parser.parse_args()

    optimizer = AtenaDynamicEvolutionOptimizer(args.root)
    if args.loop:
        optimizer.run_self_healing_loop(args.interval)
    else:
        result = optimizer.execute_evolution_cycle(args.target, args.args)
        print(json.dumps(result, indent=2, default=str))
