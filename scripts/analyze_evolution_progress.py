from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.learning_progress import LearningProgress

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "analysis_reports"
EVOLUTION = ROOT / "atena_evolution"


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_error": f"{type(exc).__name__}: {exc}"}


def summarize_eval(path: Path, data: dict) -> dict:
    results = data.get("results", []) if isinstance(data, dict) else []
    scores = [r.get("score") for r in results if isinstance(r, dict) and isinstance(r.get("score"), (int, float))]
    passed = sum(bool(r.get("passed")) for r in results if isinstance(r, dict))
    models = sorted({str(r.get("model")) for r in results if isinstance(r, dict) and r.get("model")})
    categories = {}
    for r in results:
        if not isinstance(r, dict):
            continue
        cat = str(r.get("category", "unknown"))
        if isinstance(r.get("score"), (int, float)):
            categories.setdefault(cat, []).append(float(r["score"]))
    return {
        "file": str(path.relative_to(ROOT)),
        "benchmark": data.get("benchmark") or data.get("name"),
        "models": models,
        "tasks": len(results),
        "passed": passed,
        "mean_score": round(mean(scores), 4) if scores else None,
        "categories": {k: {"n": len(v), "mean": round(mean(v), 4)} for k, v in sorted(categories.items())},
        "errors": sum(1 for r in results if isinstance(r, dict) and r.get("error")),
    }


def sqlite_summary(path: Path) -> dict:
    if not path.exists():
        return {"exists": False}
    out = {"exists": True, "tables": {}}
    try:
        con = sqlite3.connect(path)
        tables = [row[0] for row in con.execute("select name from sqlite_master where type='table' order by name")]
        for table in tables:
            safe = table.replace('"', '""')
            count = con.execute(f'SELECT count(*) FROM "{safe}"').fetchone()[0]
            out["tables"][table] = count
        con.close()
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def main() -> None:
    evaluations = []
    for path in sorted(REPORT_DIR.glob("*.json")):
        data = load_json(path)
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            evaluations.append(summarize_eval(path, data))
    cycles = sorted(EVOLUTION.glob("**/cycle-*.json"))
    proposals = sorted((EVOLUTION / "proposals").glob("*.json")) if (EVOLUTION / "proposals").exists() else []
    memory_db = EVOLUTION / "memory.sqlite3"
    learning_trend = {}
    if memory_db.exists():
        with LearningProgress(memory_db) as progress:
            rows = progress.connection.execute(
                "SELECT DISTINCT benchmark_version FROM learning_progress WHERE benchmark_version IS NOT NULL ORDER BY benchmark_version"
            ).fetchall()
            for (benchmark_version,) in rows:
                learning_trend[benchmark_version] = progress.benchmark_summary(benchmark_version)

    output = {
        "evaluation_reports": evaluations,
        "cycle_files": len(cycles),
        "proposal_files": len(proposals),
        "learning_trend": learning_trend,
        "memory_databases": {
            "memory.sqlite3": sqlite_summary(EVOLUTION / "memory.sqlite3"),
            "provider_quota.sqlite3": sqlite_summary(EVOLUTION / "provider_quota.sqlite3"),
        },
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
