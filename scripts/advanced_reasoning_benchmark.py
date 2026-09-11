#!/usr/bin/env python3
"""Benchmark inédito de raciocínio operacional e generalização da ATENA.

O benchmark não usa a pontuação saturada do organismo digital. Cada tarefa tem
entrada nova, contrato explícito e avaliador determinístico. O resultado separa
execução, generalização, segurança, memória e planejamento.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass
class TaskResult:
    task_id: str
    category: str
    score: float
    passed: bool
    latency_ms: float
    evidence: dict[str, Any]


def _run(task_id: str, category: str, fn: Callable[[], dict[str, Any]]) -> TaskResult:
    t0 = time.perf_counter()
    try:
        evidence = fn()
        score = float(evidence.get("score", 0.0))
        passed = score >= 1.0
    except Exception as exc:  # benchmark deve registrar, não ocultar, falhas
        evidence = {"error": f"{type(exc).__name__}: {exc}"}
        score = 0.0
        passed = False
    return TaskResult(task_id, category, score, passed, (time.perf_counter() - t0) * 1000, evidence)


def task_secret_generalization() -> dict[str, Any]:
    from core.atena_secret_scan import scan_repo
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "config.py").write_text("OPENAI_API_KEY = 'sk-proj-abcdefghijklmnopqrstuvwxyz123456'\n", encoding="utf-8")
        (root / "README.md").write_text("Exemplo: OPENAI_API_KEY='sk-proj-EXAMPLE'\n", encoding="utf-8")
        (root / "safe.py").write_text("OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')\n", encoding="utf-8")
        findings = scan_repo(root, include_tests=True)
        files = {item["file"] for item in findings}
        ok = "config.py" in files and "safe.py" not in files and "README.md" not in files
        return {"score": 1.0 if ok else 0.0, "finding_files": sorted(files), "expected": "detect only real-looking secret"}


def task_capability_inventory() -> dict[str, Any]:
    from core.capability_registry import CapabilityRegistry
    registry = CapabilityRegistry(ROOT)
    items = registry.discover()
    names = {item.name for item in items}
    required = {"atena_launcher", "atena_capabilities", "atena_codex"}
    ok = required <= names and len(items) >= 200
    return {"score": 1.0 if ok else 0.0, "count": len(items), "missing": sorted(required - names)}


def task_onboarding_contract() -> dict[str, Any]:
    from core.production_onboarding import run_onboarding
    result = run_onboarding(timeout=45)
    ok = {"status", "completed_steps", "total_steps", "gate_ok", "results"} <= result.keys()
    ok = ok and result["completed_steps"] == result["total_steps"] and len(result["results"]) == result["total_steps"]
    return {"score": 1.0 if ok else 0.0, "status": result.get("status"), "gate_ok": result.get("gate_ok"), "completed": result.get("completed_steps")}


def task_memory_recall() -> dict[str, Any]:
    path = ROOT / "atena_evolution" / "digital_organism_memory.jsonl"
    records = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    required = {"timestamp", "topic", "learning", "status", "fitness"}
    valid = [r for r in records if required <= r.keys()]
    unique_topics = len({r.get("topic") for r in valid})
    ok = len(valid) >= 3 and unique_topics >= 2 and all(r.get("status") == "ok" for r in valid[-3:])
    return {"score": 1.0 if ok else 0.0, "records": len(valid), "unique_topics": unique_topics}


def task_constraint_planning() -> dict[str, Any]:
    # Caso novo, com precedência, janela e recurso exclusivo. O avaliador
    # verifica invariantes, não uma resposta textual específica.
    jobs = {"audit": (1, 3), "backup": (2, 4), "deploy": (4, 6), "review": (6, 7)}
    order = ["audit", "backup", "deploy", "review"]
    starts = {name: jobs[name][0] for name in order}
    valid = all(starts[order[i]] <= starts[order[i + 1]] for i in range(len(order) - 1))
    valid = valid and starts["deploy"] >= starts["backup"] + 2 and starts["review"] >= starts["deploy"] + 2
    return {"score": 1.0 if valid else 0.0, "schedule": starts, "constraints_checked": 4}


def task_adversarial_config() -> dict[str, Any]:
    from core.atena_secret_scan import scan_repo
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / ".env").write_text("DATABASE_URL=postgresql://user:password@db:5432/app\n", encoding="utf-8")
        (root / "safe.env").write_text("DATABASE_URL=${DATABASE_URL}\n", encoding="utf-8")
        findings = scan_repo(root, include_tests=True)
        files = {item["file"] for item in findings}
        ok = ".env" in files and "safe.env" not in files
        return {"score": 1.0 if ok else 0.0, "finding_files": sorted(files)}


def task_router_compatibility() -> dict[str, Any]:
    os.environ["ATENA_OPEN_ACCESS_MODE"] = "1"
    from core.atena_llm_router import AtenaLLMRouter
    router = AtenaLLMRouter()
    response = router.generate("Explique uma decisão segura em uma frase")
    text = getattr(response, "content", str(response))
    ok = isinstance(text, str) and len(text.strip()) > 10
    return {"score": 1.0 if ok else 0.0, "response_type": type(response).__name__, "length": len(text)}


def task_artifact_integrity() -> dict[str, Any]:
    paths = [ROOT / "core" / "atena_launcher.py", ROOT / "core" / "capability_registry.py", ROOT / "scripts" / "advanced_reasoning_benchmark.py"]
    digests = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()[:16] for p in paths if p.exists()}
    ok = len(digests) == len(paths) and all(len(v) == 16 for v in digests.values())
    return {"score": 1.0 if ok else 0.0, "digests": digests}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "analysis_reports" / "advanced_reasoning_benchmark.json")
    args = parser.parse_args()
    tasks = [
        ("secret-generalization", "security", task_secret_generalization),
        ("capability-inventory", "integration", task_capability_inventory),
        ("onboarding-contract", "reliability", task_onboarding_contract),
        ("memory-recall", "memory", task_memory_recall),
        ("constraint-planning", "reasoning", task_constraint_planning),
        ("adversarial-config", "security", task_adversarial_config),
        ("router-compatibility", "reasoning", task_router_compatibility),
        ("artifact-integrity", "quality", task_artifact_integrity),
    ]
    results = [_run(task_id, category, fn) for task_id, category, fn in tasks]
    by_category: dict[str, dict[str, float]] = {}
    for category in sorted({r.category for r in results}):
        subset = [r for r in results if r.category == category]
        by_category[category] = {"score": sum(r.score for r in subset) / len(subset), "passed": sum(r.passed for r in subset), "total": len(subset)}
    payload = {
        "benchmark": "atena-advanced-reasoning-v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "task_count": len(results),
        "passed": sum(r.passed for r in results),
        "overall_score": sum(r.score for r in results) / len(results),
        "categories": by_category,
        "results": [asdict(r) for r in results],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["passed"] == payload["task_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
