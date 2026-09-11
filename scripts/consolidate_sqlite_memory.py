#!/usr/bin/env python3
"""Consolida claims repetidos sem apagar nem reescrever episódios brutos."""
from __future__ import annotations
import argparse, hashlib, json, re, sqlite3
from pathlib import Path

STOP=set('a as o os um uma de da do das dos e em para por com sem que sobre não na no nas nos'.split())
KEYS={'insights':'insight','observations':'insight','risks':'risk','proposals':'proposal','next_cycle':'next_cycle','next_steps':'next_cycle'}

def normalize(text):
    text=re.sub(r'[^\w\s]',' ',str(text).casefold(),flags=re.UNICODE)
    words=[w for w in text.split() if w not in STOP and len(w)>2]
    return ' '.join(words)

def claim_rows(raw):
    try: obj=json.loads(raw)
    except (TypeError,json.JSONDecodeError): return []
    output=obj.get('event',{}).get('output','') if isinstance(obj,dict) else ''
    try: data=json.loads(output) if isinstance(output,str) else output
    except json.JSONDecodeError: return []
    if not isinstance(data,dict): return []
    for kind, key in KEYS.items():
        values=data.get(kind,[])
        if isinstance(values,str): values=[values]
        if isinstance(values,list):
            for value in values:
                if isinstance(value,dict): value=value.get('text') or value.get('content') or json.dumps(value,ensure_ascii=False)
                if isinstance(value,str) and normalize(value): yield kind, value

def main():
    p=argparse.ArgumentParser(); p.add_argument('--db',type=Path,required=True); p.add_argument('--min-count',type=int,default=2); p.add_argument('--report',type=Path,required=True); a=p.parse_args()
    con=sqlite3.connect(a.db); con.row_factory=sqlite3.Row
    con.executescript('''CREATE TABLE IF NOT EXISTS consolidated_claims (claim_key TEXT PRIMARY KEY, kind TEXT NOT NULL, canonical_text TEXT NOT NULL, first_episode_id TEXT NOT NULL, last_episode_id TEXT NOT NULL, seen_count INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'candidate', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP); CREATE INDEX IF NOT EXISTS idx_claims_kind_count ON consolidated_claims(kind, seen_count DESC);''')
    episodes=con.execute('SELECT id,record_json,created_at FROM episodes ORDER BY created_at,id').fetchall(); grouped={}
    for ep in episodes:
        for kind,text in claim_rows(ep['record_json']):
            norm=normalize(text); key='sha256:'+hashlib.sha256((kind+'|'+norm).encode()).hexdigest(); item=grouped.setdefault(key,{'kind':kind,'texts':[],'episodes':[]}); item['texts'].append(text); item['episodes'].append(ep['id'])
    report=[]
    with con:
        for key,item in grouped.items():
            canonical=max(item['texts'],key=len); old=con.execute('SELECT first_episode_id,last_episode_id,seen_count FROM consolidated_claims WHERE claim_key=?',(key,)).fetchone(); count=len(item['episodes'])+(int(old['seen_count']) if old else 0)
            first=(old['first_episode_id'] if old else item['episodes'][0]); last=item['episodes'][-1]
            status='repeated' if count>=a.min_count else 'candidate'
            con.execute('''INSERT INTO consolidated_claims(claim_key,kind,canonical_text,first_episode_id,last_episode_id,seen_count,status,updated_at) VALUES(?,?,?,?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(claim_key) DO UPDATE SET canonical_text=excluded.canonical_text,last_episode_id=excluded.last_episode_id,seen_count=excluded.seen_count,status=excluded.status,updated_at=CURRENT_TIMESTAMP''',(key,item['kind'],canonical,first,last,count,status))
            if count>=a.min_count: report.append({'claim_key':key,'kind':item['kind'],'canonical_text':canonical,'seen_count':count,'episode_ids':item['episodes']})
    con.close(); a.report.parent.mkdir(parents=True,exist_ok=True); a.report.write_text(json.dumps({'episodes_scanned':len(episodes),'repeated_claims':len(report),'claims':report},ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); print(f'episodes_scanned={len(episodes)} repeated_claims={len(report)}')
if __name__=='__main__': main()
