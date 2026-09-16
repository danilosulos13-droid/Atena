#!/usr/bin/env python3
"""Integra evidências web persistidas com memória episódica e dataset de treino.

O comando é determinístico e idempotente por ``content_hash``/URL. Nunca marca
uma fonte como verificada sem URL e texto suficiente, e não altera pesos de
modelo: treino e promoção são gates separados no workflow.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.memory_store import MemoryStore

SYSTEM_VERSION = "unified-learning-pipeline-v2-analysis"


def clean(value: Any, limit: int = 12000) -> str:
    return " ".join(str(value or "").split())[:limit]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def research_text(item: dict[str, Any]) -> str:
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    return clean(payload.get("full_text") or payload.get("summary") or item.get("summary"), 12000)


def source_url(item: dict[str, Any]) -> str:
    return clean(item.get("source_url") or item.get("url"), 2000)


def append_experience(path: Path, row: dict[str, Any]) -> None:
    existing = {str(item.get("example_id")) for item in load_jsonl(path)}
    if row["example_id"] in existing:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def ingest(args: argparse.Namespace) -> int:
    rows = load_jsonl(args.input)
    report: dict[str, Any] = {
        "status": "ok",
        "pipeline_version": SYSTEM_VERSION,
        "input": str(args.input),
        "episodes_created": 0,
        "episodes_existing": 0,
        "examples_created": 0,
        "rejected": 0,
        "memory_ids": [],
        "sources": [],
    }
    with MemoryStore(args.db) as store:
        for item in rows:
            url = source_url(item)
            text = research_text(item)
            if not (url.startswith(("http://", "https://")) and len(text) >= 80):
                report["rejected"] += 1
                continue
            content_hash = clean(item.get("content_hash"), 128) or hashlib.sha256(text.encode()).hexdigest()
            title = clean(item.get("title") or item.get("topic") or url, 240)
            analysis = item.get("analysis") if isinstance(item.get("analysis"), dict) else {}
            if item.get("analysis_status") != "analyzed" or not analysis.get("claim"):
                report["rejected"] += 1
                continue
            confidence = float(analysis.get("confidence", 0.2) or 0.2)
            evidence_refs = list(dict.fromkeys([url] + [str(x) for x in analysis.get("related_evidence", []) if str(x)]))[:5]
            source_id = f"web:{content_hash}"
            found = store.connection.execute(
                "SELECT episode_id FROM provenance WHERE source_id=? AND source_url=? LIMIT 1",
                (source_id, url),
            ).fetchone()
            if found:
                memory_id = str(found[0])
                report["episodes_existing"] += 1
            elif args.dry_run:
                memory_id = f"dry-{content_hash[:12]}"
            else:
                now = dt.datetime.now(dt.timezone.utc).isoformat()
                record = {
                    "memory_id": "", "record_type": "observation", "created_at": now,
                    "provenance": {"source_type": "web", "source_id": source_id, "source_url": url,
                                   "model": None, "system_version": SYSTEM_VERSION,
                                   "parent_memory_ids": [], "previous_record_hash": None},
                    "subject": {"task_id": "unified-research", "domain": clean(item.get("topic") or "general", 160),
                                "benchmark_version": None, "capability": None},
                    "event": {"input_digest": hashlib.sha256(url.encode()).hexdigest(),
                              "output": clean(analysis.get("summary") or f"{title}: {text}"), "output_redacted": False, "environment": {},
                              "source_title": title, "analysis": analysis},
                    "evidence": {"status": "supported" if confidence >= 0.6 else "unverified", "confidence": confidence, "refs": evidence_refs,
                                 "counterevidence_refs": [], "verification_method": analysis.get("method", "scientific_analysis")},
                    "lifecycle": {"state": "active", "retention_class": "raw", "supersedes": None},
                    "privacy": {"redactions": [], "contains_secret": False},
                }
                from core.episodic_memory import build_episode
                record = build_episode(record_type=record["record_type"], task_id=record["subject"]["task_id"],
                                       domain=record["subject"]["domain"], output=record["event"]["output"],
                                       source_type="external_source", source_id=source_id, system_version=SYSTEM_VERSION,
                                       source_url=url, confidence=confidence, status="supported" if confidence >= 0.6 else "unverified",
                                       evidence_refs=evidence_refs, event_extra={"source_title": title, "analysis": analysis})
                memory_id = store.append(record)
                report["episodes_created"] += 1
            example_id = hashlib.sha256((url + "\n" + text).encode()).hexdigest()[:24]
            example = {"example_id": example_id, "prompt": f"Analise criticamente a evidência sobre: {title}",
                       "response": analysis.get("summary", text), "evidence": evidence_refs, "source_url": url,
                       "topic": clean(item.get("topic") or title, 160), "domain": "web-research",
                       "memory_id": memory_id, "analysis": analysis}
            before = len(load_jsonl(args.experiences))
            append_experience(args.experiences, example)
            if len(load_jsonl(args.experiences)) > before:
                report["examples_created"] += 1
            report["memory_ids"].append(memory_id)
            report["sources"].append({"title": title, "url": url, "memory_id": memory_id,
                                       "analysis_status": "analyzed", "confidence": confidence,
                                       "corroborating_sources": analysis.get("corroborating_sources", 0),
                                       "limitations": analysis.get("limitations", [])})
        if not args.dry_run:
            store.verify_integrity()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ingest", choices=["ingest"])
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--db", type=Path, default=ROOT / "atena_evolution/memory.sqlite3")
    parser.add_argument("--experiences", type=Path, default=ROOT / "atena_evolution/training/experiences.jsonl")
    parser.add_argument("--report", type=Path, default=ROOT / "atena_evolution/training/unified_ingest_report.json")
    parser.add_argument("--dry-run", action="store_true")
    return ingest(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
