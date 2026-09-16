#!/usr/bin/env python3
"""Reporta a capacidade de conhecimento preservado sem confundir memória com pesos."""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def count_jsonl(path: Path) -> tuple[int, int, int, Counter[str]]:
    rows = 0
    bytes_read = 0
    chars = 0
    sources: Counter[str] = Counter()
    if not path.exists():
        return rows, bytes_read, chars, sources
    for raw in path.read_bytes().splitlines():
        bytes_read += len(raw) + 1
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        rows += 1
        text = json.dumps(item, ensure_ascii=False)
        chars += len(text)
        for key in ("source", "url", "source_url", "evidence", "evidence_refs", "sources"):
            value = item.get(key) if isinstance(item, dict) else None
            values = value if isinstance(value, list) else [value]
            for source in values:
                if isinstance(source, str) and source.startswith(("http://", "https://")):
                    sources[source] += 1
    return rows, bytes_read, chars, sources


def sqlite_stats(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False}
    result: dict[str, Any] = {"exists": True, "bytes": path.stat().st_size}
    try:
        with sqlite3.connect(path) as conn:
            tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            result["tables"] = tables
            for table in tables:
                safe = '"' + table.replace('"', '""') + '"'
                result[f"rows_{table}"] = conn.execute(f"SELECT COUNT(*) FROM {safe}").fetchone()[0]
    except sqlite3.Error as exc:
        result["error"] = str(exc)
    return result


def build_report(root: Path) -> dict[str, Any]:
    jsonl_paths = sorted((root / "atena_evolution").glob("**/*.jsonl"))
    files = []
    total_rows = total_bytes = total_chars = 0
    sources: Counter[str] = Counter()
    for path in jsonl_paths:
        rows, size, chars, file_sources = count_jsonl(path)
        total_rows += rows
        total_bytes += size
        total_chars += chars
        sources.update(file_sources)
        files.append({"path": str(path.relative_to(root)), "rows": rows, "bytes": size, "approx_tokens": round(chars / 4)})
    knowledge_dir = root / "atena_evolution"
    knowledge_bytes = sum(p.stat().st_size for p in knowledge_dir.rglob("*") if p.is_file()) if knowledge_dir.exists() else 0
    report = {
        "report": "atena-knowledge-capacity-v1",
        "memory": {
            "jsonl_files": files,
            "jsonl_rows": total_rows,
            "jsonl_bytes": total_bytes,
            "jsonl_approx_tokens": round(total_chars / 4),
            "unique_source_urls": len(sources),
            "top_sources": sources.most_common(20),
            "atena_evolution_bytes": knowledge_bytes,
            "atena_evolution_gib": round(knowledge_bytes / (1024**3), 9),
        },
        "sqlite": {
            "memory": sqlite_stats(root / "atena_evolution" / "memory.sqlite3"),
            "knowledge": sqlite_stats(root / "atena_evolution" / "knowledge" / "knowledge.db"),
        },
        "weights": {
            "tracked_local_model_files": 0,
            "note": "Adaptadores LoRA promovidos vivem nos artefatos do GitHub; memória/dataset não é peso neural.",
        },
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_report(ROOT)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
