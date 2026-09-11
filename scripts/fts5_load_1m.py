#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import resource
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path('/home/ubuntu/work/rag-load-test')
REPO = ROOT / 'repo'
DB = ROOT / 'results/synthetic-capacity/atena_synthetic_1000000.sqlite3'
OUT = ROOT / 'results/fts5_load_1m.json'
sys.path.insert(0, str(REPO))

TOTAL = 1000
WORKERS = 64
QUESTIONS = [
    'inteligencia artificial evidencias controles',
    'ciberseguranca riscos procedimentos',
    'governanca dados observabilidade',
]


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def main() -> None:
    os.environ['ATENA_LEXICAL_ENGINE'] = 'fts5'
    os.environ.setdefault('ATENA_FTS5_DB_PATH', str(ROOT / 'results/lexical-1m.sqlite3'))
    os.environ.setdefault('ATENA_FTS5_MMAP_SIZE', str(5 * 1024 * 1024 * 1024))
    os.environ['ATENA_TORCH_THREADS'] = '1'
    os.environ['ATENA_TORCH_INTEROP_THREADS'] = '1'
    from core.enterprise_memory_rag import TenantMemoryRAG

    started = time.perf_counter()
    rag = TenantMemoryRAG(DB, enable_embeddings=False)
    init_ms = (time.perf_counter() - started) * 1000
    rows = []
    wall_start = time.perf_counter()

    def one(i: int) -> dict:
        question = QUESTIONS[i % len(QUESTIONS)]
        t0 = time.perf_counter()
        try:
            result = rag.query(
                'atena-synthetic', question, top_k=5,
                min_score=0.01, use_cache=False,
                user_id=f'fts5-1m-{i}',
            )
            return {
                'ok': result.get('status') == 'ok',
                'has_results': bool(result.get('results')),
                'latency_ms': (time.perf_counter() - t0) * 1000,
                'error': None,
            }
        except Exception as exc:
            return {
                'ok': False,
                'has_results': False,
                'latency_ms': (time.perf_counter() - t0) * 1000,
                'error': f'{type(exc).__name__}: {exc}',
            }

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(one, i) for i in range(TOTAL)]
        for future in as_completed(futures):
            rows.append(future.result())
    wall_ms = (time.perf_counter() - wall_start) * 1000
    latencies = sorted(row['latency_ms'] for row in rows)

    def percentile(p: float) -> float:
        index = min(len(latencies) - 1, int(p * len(latencies)))
        return round(latencies[index], 3)

    conn = sqlite3.connect(DB)
    counts = {
        'memory_rows': conn.execute('select count(*) from memory').fetchone()[0],
        'fts_rows': conn.execute('select count(*) from memory_fts').fetchone()[0],
    }
    conn.close()
    result = {
        'database': str(DB),
        'lexical_engine': 'fts5',
        'chunks': counts['memory_rows'],
        'fts_rows': counts['fts_rows'],
        'requests': TOTAL,
        'workers': WORKERS,
        'success': sum(row['ok'] for row in rows),
        'failed': sum(not row['ok'] for row in rows),
        'with_results': sum(row.get('has_results', False) for row in rows),
        'no_results': sum(row['ok'] and not row.get('has_results', False) for row in rows),
        'init_ms': round(init_ms, 3),
        'wall_time_ms': round(wall_ms, 3),
        'throughput_rps': round(TOTAL / (wall_ms / 1000), 3),
        'p50_ms': percentile(0.50),
        'p95_ms': percentile(0.95),
        'p99_ms': percentile(0.99),
        'max_ms': round(max(latencies), 3),
        'rss_mb_after_queries': round(rss_mb(), 1),
        'errors': [row for row in rows if row['error']],
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result['failed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
