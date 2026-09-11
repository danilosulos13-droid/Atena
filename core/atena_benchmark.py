"""Benchmark local de prontidão sem exigir modelo externo.

Se o ambiente tiver dependências opcionais, o self-test completo é executado pelo
release gate. Este benchmark mede invariantes determinísticos do produto.
"""
from __future__ import annotations
import importlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CHECKS = [
    ("knowledge_base", ROOT / "core/knowledge_base.py"),
    ("research_agent", ROOT / "core/research_agent.py"),
    ("autonomous_learning", ROOT / "core/autonomous_learning.py"),
    ("candidate_evaluator", ROOT / "core/model_candidate_evaluator.py"),
    ("web_research", ROOT / "core/web_research.py"),
    ("release_gate", ROOT / "core/atena_release_gate.py"),
]

def run() -> dict:
    results = []
    for name, module in CHECKS:
        try:
            source = Path(module).read_text(encoding="utf-8")
            compile(source, str(module), "exec")
            results.append({"id": name, "ok": True})
        except Exception as exc:
            results.append({"id": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    files = [ROOT / "atena", ROOT / "README.md", ROOT / "requirements.txt"]
    results.extend({"id": f.name, "ok": f.exists()} for f in files)
    passed = sum(r["ok"] for r in results)
    score = round(100 * passed / len(results), 2) if results else 0.0
    return {"score": score, "passed": passed, "total": len(results), "results": results}

def main() -> int:
    payload = run()
    out = ROOT / "atena_evolution" / "release_gates" / "benchmark-latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"ATENA benchmark score={payload['score']:.2f}/100 passed={payload['passed']}/{payload['total']}")
    return 0 if payload["score"] >= float(os.getenv("ATENA_BENCHMARK_MIN", "90")) else 2

if __name__ == "__main__":
    raise SystemExit(main())
