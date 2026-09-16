#!/usr/bin/env python3
"""Sync ATENA episodic memory and provenance to Supabase in bounded batches."""
from __future__ import annotations
import argparse, json, os, sqlite3
from pathlib import Path
from urllib.request import Request, urlopen


def main():
    p=argparse.ArgumentParser(); p.add_argument('--db',type=Path,default=Path('atena_evolution/memory.sqlite3')); p.add_argument('--batch-size',type=int,default=100); p.add_argument('--limit',type=int,default=0); p.add_argument('--table',default='atena_memory_chunks'); p.add_argument('--tenant-id',default=os.environ.get('ATENA_TENANT_ID','atena-programming')); args=p.parse_args()
    url=os.environ.get('SUPABASE_URL','').rstrip('/'); key=os.environ.get('SUPABASE_SERVICE_ROLE_KEY','')
    if not url or not key: raise SystemExit('Configure SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY; nunca use a chave service_role fora dos secrets.')
    con=sqlite3.connect(args.db)
    sql="""select e.id,e.sequence,e.record_type,e.task_id,e.domain,e.created_at,e.content_hash,e.status,e.confidence,e.record_json,
                    p.source_type,p.source_id,p.source_url,p.model,p.model_digest,p.system_version,p.workflow_run_id,p.verification_method
             from episodes e left join provenance p on p.episode_id=e.id
             order by e.sequence""" + (' limit ?' if args.limit else '')
    rows=con.execute(sql,(args.limit,) if args.limit else ()).fetchall(); con.close()
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise SystemExit('Instale sentence-transformers para gerar embeddings.') from exc
    embedding_model_name = os.environ.get('ATENA_EMBEDDING_MODEL', 'sentence-transformers/all-MiniLM-L6-v2')
    encoder = SentenceTransformer(embedding_model_name)
    texts = [row[9] or '' for row in rows]
    vectors = encoder.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    if getattr(vectors, 'shape', (0, 0))[1] != 384:
        raise SystemExit(f'Embedding com dimensão inesperada: {getattr(vectors, "shape", None)}; esperado 384.')
    total=0
    for start in range(0,len(rows),args.batch_size):
        payload=[]
        for offset, row in enumerate(rows[start:start+args.batch_size]):
            (memory_id,sequence,record_type,task_id,domain,created_at,content_hash,status,confidence,record_json,
             source_type,source_id,source_url,model,model_digest,system_version,workflow_run_id,verification_method)=row
            payload.append({'content_hash':content_hash,'source_path':source_url or source_id or 'atena://episodic-memory',
                            'source_sha256':content_hash,'chunk_no':0,'content':record_json,
                            'tenant_id':args.tenant_id,'approved':status == 'supported',
                            'embedding_model':embedding_model_name,'embedding':vectors[start+offset].tolist(),
                            'metadata':{'memory_id':memory_id,'sequence':sequence,'record_type':record_type,
                                        'task_id':task_id,'domain':domain,'status':status,'confidence':confidence,
                                        'source_type':source_type,'model':model,'model_digest':model_digest,
                                        'system_version':system_version,'workflow_run_id':workflow_run_id,
                                        'verification_method':verification_method},
                            'created_at':created_at})
        body=json.dumps(payload,ensure_ascii=False).encode()
        conflict_key = 'tenant_id,content_hash' if args.table == 'atena_memory_chunks' else 'memory_id'
        req=Request(f'{url}/rest/v1/{args.table}?on_conflict={conflict_key}',data=body,method='POST',headers={'apikey':key,'Authorization':f'Bearer {key}','Content-Type':'application/json','Prefer':'resolution=merge-duplicates,return=minimal'})
        with urlopen(req,timeout=60) as response:
            if response.status not in (200,201,204): raise RuntimeError(f'Supabase HTTP {response.status}')
        total+=len(payload); print(json.dumps({'synced':total,'batch_size':len(payload)}),flush=True)
    print(json.dumps({'status':'ok','rows_available':len(rows),'rows_synced':total,'table':args.table}))

if __name__=='__main__': main()
