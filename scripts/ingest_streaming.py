#!/usr/bin/env python3
"""Ingestão bounded-memory para corpora grandes e datasets de treino da ATENA."""
from __future__ import annotations
import argparse, hashlib, json, sqlite3
from datetime import datetime, timezone
from pathlib import Path

EXTENSIONS={'.txt','.md','.jsonl','.json','.csv','.log','.py','.js','.ts','.tsx','.jsx','.java','.go','.rs','.sql','.sh','.yml','.yaml','.toml'}
IGNORED={'.git','.venv','node_modules','__pycache__','cache','tmp'}

def iter_chunks(stream, size:int, overlap:int):
    carry=''
    step=max(1,size-overlap)
    while True:
        block=stream.read(max(size, step))
        if not block: break
        carry += block
        while len(carry)>=size:
            value=carry[:size].strip()
            if value: yield value
            carry=carry[step:]
    if carry.strip(): yield carry.strip()

def file_digest(path:Path, block=1024*1024):
    digest=hashlib.sha256(); total=0
    with path.open('rb') as f:
        while data:=f.read(block): digest.update(data); total+=len(data)
    return digest.hexdigest(), total

def main():
    p=argparse.ArgumentParser()
    p.add_argument('input',type=Path)
    p.add_argument('--db',type=Path,default=Path('atena_evolution/memory.sqlite3'))
    p.add_argument('--checkpoint',type=Path,default=Path('atena_evolution/ingest_checkpoint.json'))
    p.add_argument('--dataset-output',type=Path,default=None,help='diretório de shards JSONL compatíveis com SFT')
    p.add_argument('--shard-bytes',type=int,default=256*1024*1024)
    p.add_argument('--max-file-bytes',type=int,default=1024*1024*1024)
    p.add_argument('--chunk-size',type=int,default=1800); p.add_argument('--overlap',type=int,default=200); p.add_argument('--batch-size',type=int,default=1000)
    args=p.parse_args(); args.db.parent.mkdir(parents=True,exist_ok=True)
    state=json.loads(args.checkpoint.read_text()) if args.checkpoint.exists() else {'files':{},'shards':[]}
    con=sqlite3.connect(args.db,timeout=60); con.execute('PRAGMA journal_mode=WAL'); con.execute('PRAGMA synchronous=NORMAL')
    con.execute('''CREATE TABLE IF NOT EXISTS atena_ingested_chunks(id INTEGER PRIMARY KEY AUTOINCREMENT,source_path TEXT NOT NULL,source_sha256 TEXT NOT NULL,chunk_no INTEGER NOT NULL,content TEXT NOT NULL,content_sha256 TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,approved INTEGER NOT NULL DEFAULT 0)''')
    if 'approved' not in {r[1] for r in con.execute('PRAGMA table_info(atena_ingested_chunks)')}: con.execute('ALTER TABLE atena_ingested_chunks ADD COLUMN approved INTEGER NOT NULL DEFAULT 0')
    out=args.dataset_output; shard=None; shard_bytes=0; shard_index=len(state.get('shards',[])); manifest=[]
    if out: out.mkdir(parents=True,exist_ok=True)
    if out and (out/'manifest.json').exists():
        try:
            manifest=json.loads((out/'manifest.json').read_text()).get('shards',[])
            shard_index=len(manifest)
        except (OSError, json.JSONDecodeError):
            manifest=[]
    def emit_dataset(source, no, content, digest):
        nonlocal shard,shard_bytes,shard_index
        if not out: return
        record={'messages':[{'role':'user','content':f'Analise este trecho de código/documentação da Atena e explique seu funcionamento com precisão.'},{'role':'assistant','content':content}], 'metadata':{'source':source,'chunk_no':no,'source_sha256':digest,'domain':'programming'}}
        raw=(json.dumps(record,ensure_ascii=False)+'\n').encode('utf-8')
        if shard is None or shard_bytes+len(raw)>args.shard_bytes:
            if shard: shard.close()
            path=out/f'sft-{shard_index:05d}.jsonl'; shard=path.open('ab'); shard_bytes=0; shard_index+=1; manifest.append({'path':str(path),'bytes':0,'records':0})
        shard.write(raw); shard.flush(); shard_bytes+=len(raw); manifest[-1]['bytes']+=len(raw); manifest[-1]['records']+=1
    files=sorted(x for x in (args.input.rglob('*') if args.input.is_dir() else [args.input]) if x.is_file() and not IGNORED.intersection(x.parts) and x.suffix.lower() in EXTENSIONS)
    inserted=skipped=too_large=0; batch=[]; now=datetime.now(timezone.utc).isoformat()
    for path in files:
        digest,size=file_digest(path)
        if size>args.max_file_bytes: too_large+=1; continue
        if state['files'].get(str(path))==digest: skipped+=1; continue
        with path.open('r',encoding='utf-8',errors='replace') as stream:
            for no,content in enumerate(iter_chunks(stream,args.chunk_size,args.overlap)):
                content_hash=hashlib.sha256(content.encode()).hexdigest()
                batch.append((str(path),digest,no,content,content_hash,now)); emit_dataset(str(path),no,content,digest)
                if len(batch)>=args.batch_size:
                    cur=con.executemany('INSERT OR IGNORE INTO atena_ingested_chunks(source_path,source_sha256,chunk_no,content,content_sha256,created_at) VALUES(?,?,?,?,?,?)',batch); con.commit(); inserted+=max(0,cur.rowcount); batch.clear()
        state['files'][str(path)]=digest; args.checkpoint.parent.mkdir(parents=True,exist_ok=True); args.checkpoint.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
    if batch:
        cur=con.executemany('INSERT OR IGNORE INTO atena_ingested_chunks(source_path,source_sha256,chunk_no,content,content_sha256,created_at) VALUES(?,?,?,?,?,?)',batch); con.commit(); inserted+=max(0,cur.rowcount)
    if shard: shard.close()
    if out:
        state['shards']=manifest; (out/'manifest.json').write_text(json.dumps({'format':'messages-jsonl','shards':manifest,'created_at':now},ensure_ascii=False,indent=2)+'\n')
    total=con.execute('SELECT count(*) FROM atena_ingested_chunks').fetchone()[0]; con.close()
    print(json.dumps({'files_seen':len(files),'files_skipped':skipped,'files_too_large':too_large,'chunks_attempted':inserted,'chunks_total':total,'dataset_shards':len(manifest),'dataset_output':str(out) if out else None,'database':str(args.db)},ensure_ascii=False))
if __name__=='__main__': main()
