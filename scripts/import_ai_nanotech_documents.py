#!/usr/bin/env python3
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / 'config' / 'ai_nanotech_training_documents.json'
DEFAULT_MEMORY = ROOT / 'atena_evolution' / 'learning_memory.jsonl'

def main() -> int:
    parser = argparse.ArgumentParser(description='Importa documentos curados de IA/nanotecnologia na memória de aprendizagem.')
    parser.add_argument('--input', type=Path, default=DEFAULT_INPUT)
    parser.add_argument('--memory', type=Path, default=DEFAULT_MEMORY)
    args = parser.parse_args()
    bundle = json.loads(args.input.read_text(encoding='utf-8'))
    docs = bundle.get('documents', [])
    args.memory.parent.mkdir(parents=True, exist_ok=True)
    existing_urls: set[str] = set()
    existing_hashes: set[str] = set()
    if args.memory.exists():
        for line in args.memory.read_text(encoding='utf-8', errors='replace').splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            existing_urls.add(str(row.get('source_url') or '').split('#', 1)[0])
            existing_hashes.add(str(row.get('content_hash') or ''))
    added = 0
    skipped = 0
    with args.memory.open('a', encoding='utf-8') as handle:
        for doc in docs:
            url = str(doc.get('url') or doc.get('canonical_url') or '').strip().split('#', 1)[0]
            content = str(doc.get('content') or '').strip()
            if not url or not content:
                skipped += 1
                continue
            digest = str(doc.get('content_hash') or hashlib.sha256(content.encode('utf-8', errors='replace')).hexdigest())
            if url in existing_urls or digest in existing_hashes:
                skipped += 1
                continue
            row = {
                'kind': 'internet_research',
                'topic': doc.get('topic') or 'artificial_intelligence_nanotechnology',
                'source_url': url,
                'source_feed': 'curated_ai_nanotech_collection',
                'title': doc.get('title') or url,
                'published_at': doc.get('fetched_at'),
                'content_hash': digest,
                'page_status': 'curated_indexed',
                'payload': {'summary': content[:2000], 'full_text': content},
            }
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
            existing_urls.add(url)
            existing_hashes.add(digest)
            added += 1
    print(json.dumps({'status':'ok','input_documents':len(docs),'added':added,'skipped':skipped,'memory':str(args.memory)},ensure_ascii=False,indent=2))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
