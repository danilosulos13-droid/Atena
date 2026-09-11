#!/usr/bin/env python3
"""Create bounded SFT examples from streaming-ingested chunks."""
from __future__ import annotations
import argparse, hashlib, json, sqlite3
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", type=Path, default=Path("atena_evolution/memory.sqlite3"))
    p.add_argument("--output", type=Path, default=Path("atena_evolution/training/sft.jsonl"))
    p.add_argument("--max-examples", type=int, default=10000)
    p.add_argument("--min-chars", type=int, default=120)
    args = p.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    rows = conn.execute("SELECT source_path, chunk_no, content FROM atena_ingested_chunks WHERE length(content)>=? ORDER BY id", (args.min_chars,))
    seen = set(); count = 0
    with args.output.open("w", encoding="utf-8") as out:
        for source, chunk_no, content in rows:
            digest = hashlib.sha256(content.encode()).hexdigest()
            if digest in seen: continue
            seen.add(digest)
            example = {"messages": [
                {"role": "system", "content": "Responda usando somente a evidência fornecida e indique a fonte."},
                {"role": "user", "content": f"Resuma a evidência do trecho {chunk_no} de {source} e preserve os fatos verificáveis."},
                {"role": "assistant", "content": content[:3000]},
            ], "metadata": {"source": source, "chunk_no": chunk_no, "content_sha256": digest}}
            out.write(json.dumps(example, ensure_ascii=False) + "\n")
            count += 1
            if count >= args.max_examples: break
    conn.close()
    print(json.dumps({"status": "ok", "examples": count, "output": str(args.output), "max_examples": args.max_examples}, ensure_ascii=False))

if __name__ == "__main__": main()
