#!/usr/bin/env python3
"""Promote approved staging chunks to RAG memory with bounded MiniLM batches."""
from __future__ import annotations
import argparse, hashlib, json, sqlite3
from datetime import datetime, timezone
from pathlib import Path


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--db", type=Path, default=Path("atena_evolution/memory.sqlite3"))
    p.add_argument("--tenant", default="atena-ingested")
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--model", default="all-MiniLM-L6-v2")
    args=p.parse_args()
    con=sqlite3.connect(args.db, timeout=60)
    cols={r[1] for r in con.execute("pragma table_info(atena_ingested_chunks)")}
    if "approved" not in cols:
        con.close(); print(json.dumps({"status":"blocked","reason":"staging sem coluna approved; nada foi promovido"})); return
    rows=con.execute("select id,source_path,content,content_sha256 from atena_ingested_chunks where approved=1 order by id" + (" limit ?" if args.limit else ""), ((args.limit,) if args.limit else ())).fetchall()
    if not rows:
        con.close(); print(json.dumps({"status":"ok","approved":0,"promoted":0,"reason":"nenhum chunk aprovado"})); return
    try:
        from sentence_transformers import SentenceTransformer
        model=SentenceTransformer(args.model)
    except Exception as exc:
        con.close(); raise SystemExit(f"MiniLM indisponível: {exc}")
    con.executescript("""CREATE TABLE IF NOT EXISTS memory(
      id INTEGER PRIMARY KEY AUTOINCREMENT, tenant_id TEXT NOT NULL, content TEXT NOT NULL,
      citation TEXT NOT NULL, classification TEXT NOT NULL, tags_json TEXT NOT NULL,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL, access_count INTEGER DEFAULT 0,
      last_accessed TEXT, source TEXT, embedding BLOB, metadata_json TEXT,
      content_hash TEXT UNIQUE);
    CREATE INDEX IF NOT EXISTS idx_memory_tenant ON memory(tenant_id);
    """)
    now=datetime.now(timezone.utc).isoformat(); promoted=0
    for start in range(0,len(rows),args.batch_size):
        batch=rows[start:start+args.batch_size]
        vectors=model.encode([r[2] for r in batch], batch_size=args.batch_size, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
        for row, vector in zip(batch,vectors):
            con.execute("""INSERT OR IGNORE INTO memory(tenant_id,content,citation,classification,tags_json,created_at,updated_at,source,embedding,metadata_json,content_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",(args.tenant,row[2],f"file://{row[1]}#chunk-{row[0]}","internal","[]",now,now,row[1],vector.astype('float32').tobytes(),json.dumps({'staging_id':row[0]},ensure_ascii=False),row[3]))
        con.commit(); promoted += len(batch)
    con.close(); print(json.dumps({"status":"ok","approved":len(rows),"promoted_attempted":promoted,"batch_size":args.batch_size,"model":args.model},ensure_ascii=False))

if __name__ == '__main__': main()
