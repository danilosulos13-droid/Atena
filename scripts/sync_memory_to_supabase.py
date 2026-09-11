#!/usr/bin/env python3
"""Sync approved ATENA memory rows to Supabase in bounded batches."""
from __future__ import annotations
import argparse, json, os, sqlite3
from pathlib import Path
from urllib.request import Request, urlopen


def main():
    p=argparse.ArgumentParser(); p.add_argument('--db',type=Path,default=Path('atena_evolution/memory.sqlite3')); p.add_argument('--batch-size',type=int,default=100); p.add_argument('--limit',type=int,default=0); args=p.parse_args()
    url=os.environ.get('SUPABASE_URL','').rstrip('/'); key=os.environ.get('SUPABASE_SERVICE_ROLE_KEY','')
    if not url or not key: raise SystemExit('Configure SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY; nunca use a chave service_role no Git.')
    con=sqlite3.connect(args.db)
    sql="select content_hash,source,content,tenant_id,embedding,metadata_json,created_at,updated_at from memory where content_hash is not null order by id" + (' limit ?' if args.limit else '')
    rows=con.execute(sql,(args.limit,) if args.limit else ()).fetchall(); con.close()
    total=0
    for start in range(0,len(rows),args.batch_size):
        payload=[]
        for h,source,content,tenant,embedding,metadata,created,updated in rows[start:start+args.batch_size]:
            vector=None
            if embedding:
                import struct
                vector=list(struct.unpack('<'+'f'*(len(embedding)//4),embedding))
            payload.append({'content_hash':h,'source_path':source or 'unknown','source_sha256':h,'chunk_no':0,'content':content,'tenant_id':tenant,'approved':True,'embedding_model':'all-MiniLM-L6-v2' if vector else None,'embedding':vector,'metadata':json.loads(metadata or '{}'),'created_at':created,'updated_at':updated})
        body=json.dumps(payload,ensure_ascii=False).encode()
        req=Request(f'{url}/rest/v1/atena_memory_chunks?on_conflict=content_hash',data=body,method='POST',headers={'apikey':key,'Authorization':f'Bearer {key}','Content-Type':'application/json','Prefer':'resolution=merge-duplicates,return=minimal'})
        with urlopen(req,timeout=60) as response:
            if response.status not in (200,201,204): raise RuntimeError(f'Supabase HTTP {response.status}')
        total+=len(payload); print(json.dumps({'synced':total,'batch_size':len(payload)}),flush=True)
    print(json.dumps({'status':'ok','rows_available':len(rows),'rows_synced':total,'table':'atena_memory_chunks'}))

if __name__=='__main__': main()
