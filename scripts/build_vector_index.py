#!/usr/bin/env python3
"""Build a persistent vector index from SQLite embeddings in bounded batches."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import numpy as np


def build(db_path: Path, output_dir: Path, batch_size: int = 4096) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        total, dimension = conn.execute(
            "SELECT count(*), length(embedding) / 4 FROM memory WHERE embedding IS NOT NULL"
        ).fetchone()
        total = int(total or 0)
        dimension = int(dimension or 0)
        if not total or not dimension:
            raise RuntimeError("SQLite não contém embeddings float32")
        ids_path = output_dir / "memory_ids.npy"
        vectors_path = output_dir / "vectors.f32.memmap"
        ids = np.lib.format.open_memmap(ids_path, mode="w+", dtype=np.int64, shape=(total,))
        vectors = np.memmap(vectors_path, mode="w+", dtype=np.float32, shape=(total, dimension))
        cursor = conn.execute(
            "SELECT id, embedding FROM memory WHERE embedding IS NOT NULL ORDER BY id"
        )
        offset = 0
        while offset < total:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            ids[offset:offset + len(rows)] = [row[0] for row in rows]
            vectors[offset:offset + len(rows)] = np.stack(
                [np.frombuffer(row[1], dtype=np.float32) for row in rows]
            )
            offset += len(rows)
        ids.flush()
        vectors.flush()
        manifest = {
            "database": str(db_path),
            "vectors": offset,
            "dimension": dimension,
            "dtype": "float32",
            "ids": str(ids_path),
            "vectors_memmap": str(vectors_path),
            "batch_size": batch_size,
            "faiss_available": False,
        }
        try:
            import faiss  # type: ignore
            index = faiss.IndexFlatIP(dimension)
            for start in range(0, offset, batch_size):
                index.add(np.asarray(vectors[start:start + batch_size]))
            faiss.write_index(index, str(output_dir / "vectors.faiss"))
            manifest["faiss_available"] = True
            manifest["faiss_index"] = str(output_dir / "vectors.faiss")
        except ImportError:
            pass
        (output_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        )
        return manifest
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("db", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--batch-size", type=int, default=4096)
    args = parser.parse_args()
    print(json.dumps(build(args.db, args.output_dir, args.batch_size), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
