#!/usr/bin/env python3
"""Auditoria segura e somente leitura dos subsistemas da Atena.

Por padrão, este script não faz chamadas de rede, não envia Telegram, não inicia
Ollama, não grava no banco de produção e não executa ferramentas geradas.

Estados: healthy, degraded, blocked, failed, skipped.
O código de saída é 0 quando não há falha obrigatória; componentes opcionais
indisponíveis produzem degraded/blocked, mas não quebram o CI.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]

@dataclass
class Check:
    layer: str
    name: str
    status: str
    required: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0

    @property
    def passed(self) -> bool:
        return self.status in {"healthy", "skipped"} or (self.status in {"degraded", "blocked"} and not self.required)


def check(layer: str, name: str, required: bool, fn: Callable[[], tuple[str, str, dict[str, Any]]]) -> Check:
    started = time.perf_counter()
    try:
        status, message, details = fn()
    except Exception as exc:  # healthcheck nunca deve esconder o ponto de falha
        status, message, details = "failed", f"{type(exc).__name__}: {exc}", {}
    return Check(layer, name, status, required, message, details, round((time.perf_counter() - started) * 1000, 2))


def exists_check(path: Path, label: str, required: bool = True):
    def run():
        exists = path.exists()
        return ("healthy" if exists else "failed"), (f"{label} presente" if exists else f"{label} ausente"), {"path": str(path), "exists": exists}
    return run


def import_check(module: str, required: bool):
    def run():
        try:
            importlib.import_module(module)
            return "healthy", f"{module} importável", {"module": module}
        except ModuleNotFoundError as exc:
            return ("failed" if required else "degraded"), f"dependência ausente: {exc.name}", {"module": module, "missing": exc.name}
        except Exception as exc:
            return ("failed" if required else "degraded"), f"erro ao importar: {type(exc).__name__}: {exc}", {"module": module}
    return run


def sqlite_readonly_check(path: Path):
    def run():
        if not path.exists():
            return "skipped", "banco ainda não criado", {"path": str(path)}
        uri = f"file:{path.resolve()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=5) as conn:
            quick = conn.execute("PRAGMA quick_check").fetchone()[0]
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        status = "healthy" if quick == "ok" else "failed"
        return status, f"SQLite quick_check={quick}", {"path": str(path), "tables": tables, "table_count": len(tables)}
    return run


def workflow_check(path: Path, required_names: list[str]):
    def run():
        text = path.read_text(encoding="utf-8", errors="replace")
        missing = [name for name in required_names if name not in text]
        if missing:
            return "failed", f"workflow sem referências: {', '.join(missing)}", {"missing": missing}
        return "healthy", "workflow contém os pontos de integração esperados", {"required_references": required_names}
    return run


def git_check():
    def run():
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, timeout=5)
        branch = subprocess.run(["git", "branch", "--show-current"], cwd=ROOT, text=True, capture_output=True, timeout=5)
        if commit.returncode or branch.returncode:
            return "degraded", "metadados Git indisponíveis", {}
        status = subprocess.run(["git", "status", "--short"], cwd=ROOT, text=True, capture_output=True, timeout=5)
        dirty = bool(status.stdout.strip())
        return "degraded" if dirty else "healthy", ("working tree com artefatos locais" if dirty else "working tree limpo"), {"commit": commit.stdout.strip(), "branch": branch.stdout.strip(), "dirty": dirty, "status_lines": status.stdout.splitlines()[:30]}
    return run


def env_policy_check():
    def run():
        names = ["ALLOW_DEEP_SELF_MOD", "ALLOW_CHECKER_EVOLVE", "ALLOW_WORKFLOW_MUTATION", "DEPLOY_COMMAND"]
        enabled = {name: os.getenv(name, "false").lower() == "true" for name in names}
        unsafe = [name for name, value in enabled.items() if value]
        return ("failed" if unsafe else "healthy"), (f"políticas perigosas ativadas: {', '.join(unsafe)}" if unsafe else "defaults de automodificação restritivos"), {"flags": enabled}
    return run


def optional_env_check(name: str):
    def run():
        configured = bool(os.getenv(name, "").strip())
        return ("healthy" if configured else "blocked"), (f"{name} configurado" if configured else f"{name} não configurado; integração externa bloqueada"), {"variable": name, "configured": configured}
    return run


def build_checks() -> list[Check]:
    core_required = [
        "core.episodic_memory", "core.memory_store", "core.memory_retrieval", "core.memory_consolidation",
        "core.identity_state", "core.sensemaking", "core.learning_progress", "core.consequence_memory",
        "core.evolution_quality_gate", "core.atena_llm_router", "core.provider_quota", "core.agent_plan_loop",
        "core.structured_benchmark", "core.tool_broker", "core.monitoring_health", "core.semantic_dedup",
    ]
    optional = [
        "core.x_news_research", "core.audio_gateway", "core.google_calendar_client", "core.tasker_gateway",
        "core.faiss_memory", "core.atena_semantic_memory", "core.production_api",
    ]
    checks: list[Check] = []
    checks.append(check("repository", "git_state", False, git_check()))
    checks.append(check("repository", "main.py", True, exists_check(ROOT / "main.py", "main.py")))
    checks.append(check("repository", "pyproject.toml", True, exists_check(ROOT / "pyproject.toml", "pyproject.toml")))
    checks.append(check("security", "safe_defaults", True, env_policy_check()))

    for module in core_required:
        checks.append(check("core", f"import:{module}", True, import_check(module, True)))
    for module in optional:
        checks.append(check("optional", f"import:{module}", False, import_check(module, False)))

    checks.extend([
        check("learning", "scheduled_cycle", True, exists_check(ROOT / "scripts/atena_scheduled_cycle.py", "ciclo agendado")),
        check("learning", "learning_progress", True, exists_check(ROOT / "core/learning_progress.py", "progresso longitudinal")),
        check("learning", "consequence_memory", True, exists_check(ROOT / "core/consequence_memory.py", "memória de consequências")),
        check("benchmark", "rotating_runner", True, exists_check(ROOT / "scripts/run_rotating_regression_benchmark.py", "runner rotativo")),
        check("benchmark", "regression_evaluator", True, exists_check(ROOT / "scripts/evaluate_regression.py", "avaliador de regressão")),
        check("benchmark", "sandbox_validator", True, exists_check(ROOT / "scripts/run_sandbox_selfmod_validation.py", "validador de sandbox")),
        check("memory", "sqlite_readonly", False, sqlite_readonly_check(ROOT / "atena_evolution/memory.sqlite3")),
        check("telegram", "telegram_script", True, exists_check(ROOT / "scripts/atena_telegram_chat.py", "bot Telegram")),
        check("news", "news_digest", True, exists_check(ROOT / "scripts/daily_news_digest.py", "digest de notícias")),
        check("games", "store_alert", True, exists_check(ROOT / "scripts/store_discount_alert.py", "alerta de promoções")),
        check("monitoring", "health_module", True, exists_check(ROOT / "core/monitoring_health.py", "catálogo de saúde")),
        check("monitoring", "semantic_module", True, exists_check(ROOT / "core/semantic_dedup.py", "deduplicação semântica")),
        check("integrations", "telegram_credentials", False, optional_env_check("ATENA_TELEGRAM_BOT_TOKEN")),
        check("integrations", "telegram_chat", False, optional_env_check("ATENA_TELEGRAM_CHAT_ID")),
        check("integrations", "x_bearer", False, optional_env_check("ATENA_X_BEARER_TOKEN")),
        check("integrations", "ollama_url", False, optional_env_check("OLLAMA_BASE_URL")),
    ])
    workflows = {
        "atena-ci": (".github/workflows/atena-ci-and-update.yml", ["atena_scheduled_cycle.py", "atena_telegram_chat.py", "pytest"]),
        "news": (".github/workflows/daily-news-digest.yml", ["daily_news_digest.py", "--include-x"]),
        "games": (".github/workflows/steam-free-alert.yml", ["store_discount_alert.py", "0 23 * * *"]),
        "regression": (".github/workflows/rotating-regression.yml", ["run_rotating_regression_benchmark.py", "evaluate_regression.py"]),
        "selfmod": (".github/workflows/selfmod-sandbox.yml", ["run_sandbox_selfmod_validation.py"]),
    }
    for name, (relative, refs) in workflows.items():
        checks.append(check("workflows", name, True, workflow_check(ROOT / relative, refs)))
    return checks


def run_healthcheck() -> dict[str, Any]:
    results = [asdict(c) for c in build_checks()]
    counts: dict[str, int] = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    required_failures = [item for item in results if item["required"] and item["status"] == "failed"]
    return {
        "schema_version": "1.0",
        "generated_at_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "repository": str(ROOT),
        "network_calls": False,
        "external_side_effects": False,
        "decision": "failed" if required_failures else ("degraded" if counts.get("degraded", 0) or counts.get("blocked", 0) else "healthy"),
        "counts": counts,
        "required_failure_count": len(required_failures),
        "checks": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="salva o relatório JSON neste caminho")
    parser.add_argument("--strict-optional", action="store_true", help="trata integrações opcionais ausentes como falha")
    args = parser.parse_args()
    report = run_healthcheck()
    if args.strict_optional:
        optional = [x for x in report["checks"] if not x["required"] and x["status"] in {"degraded", "blocked"}]
        if optional:
            report["decision"] = "failed"
            report["strict_optional_failures"] = len(optional)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 1 if report["decision"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
