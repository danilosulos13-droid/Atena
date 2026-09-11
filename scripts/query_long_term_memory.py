#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from core.long_term_memory import LongTermMemory


def main() -> int:
    parser = argparse.ArgumentParser(description="Consulta a memória vetorial da Atena")
    parser.add_argument("query", help="expressão, tema ou pergunta para buscar")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-similarity", type=float, default=0.25)
    parser.add_argument("--storage-path", default="atena_evolution/vector_memory")
    args = parser.parse_args()
    memory = LongTermMemory(storage_path=args.storage_path)
    results = memory.recall(args.query, top_k=max(1, min(args.top_k, 20)), min_similarity=args.min_similarity)
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
