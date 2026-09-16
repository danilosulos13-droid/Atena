#!/usr/bin/env python3
"""Transforma fontes coletadas em análises científicas auditáveis.

Não trata texto externo como instrução. Extrai sentenças candidatas, calcula
confiança heurística com base em qualidade e corroboracão entre fontes, e
preserva as evidências originais.
"""
from __future__ import annotations
import argparse, hashlib, json, re
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse


def load(path: Path):
    rows=[]
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines() if path.exists() else []:
        try:
            x=json.loads(line)
            if isinstance(x,dict): rows.append(x)
        except json.JSONDecodeError: pass
    return rows


def words(text):
    return {w.lower() for w in re.findall(r"[\wÀ-ÿ]{5,}", text) if w.lower() not in {'about','which','these','their','there','using','with','from','this','that','para','como','sobre','entre','com','uma','por','dos','das','the','and','research','study','2026'}}


def sentences(text):
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if len(s.strip()) >= 70]


def source_quality(url, title):
    host=urlparse(url).netloc.lower()
    if host.endswith('.gov') or host.endswith('.edu') or any(x in host for x in ('nature.com','science.org','bmj.com','plos.org','pubmed','arxiv.org','nist.gov','noaa.gov','esa.int','cern.ch')):
        return 0.90
    if 'rss' in url or 'news' in host: return 0.65
    return 0.55


def analyze(rows):
    prepared=[]
    for row in rows:
        payload=row.get('payload') if isinstance(row.get('payload'),dict) else {}
        text=' '.join(str(payload.get('full_text') or payload.get('summary') or row.get('summary') or '').split())
        url=str(row.get('source_url') or row.get('url') or '')
        title=' '.join(str(row.get('title') or row.get('topic') or url).split())
        ss=sentences(text)
        # Prefer sentences containing evidence verbs/numbers; otherwise first sentences.
        evidence=[s for s in ss if re.search(r'\b(found|show|shows|suggest|report|result|increase|decrease|indicate|demonstrat|evidence|study|research|conclu|detect|identif|mostrou|indica|resultado|evidência)\b',s,re.I)]
        claim=(evidence or ss or [text[:800]])[0][:900]
        prepared.append({'row':row,'url':url,'title':title,'text':text,'claim':claim,'tokens':words(title+' '+claim),'quality':source_quality(url,title)})
    groups=[]
    for i,a in enumerate(prepared):
        best=[]
        for j,b in enumerate(prepared):
            if i==j: continue
            overlap=len(a['tokens'] & b['tokens']) / max(1, len(a['tokens'] | b['tokens']))
            if overlap >= 0.12: best.append((overlap,b))
        groups.append(sorted(best,key=lambda x:x[0],reverse=True)[:4])
    out=[]
    for a,related in zip(prepared,groups):
        independent={urlparse(b['url']).netloc for _,b in related if urlparse(b['url']).netloc and urlparse(b['url']).netloc != urlparse(a['url']).netloc}
        corroboration=min(0.25, 0.08*len(independent))
        confidence=round(min(0.95, max(0.20, a['quality']*0.65 + corroboration)),2)
        refs=[a['url']]+[b['url'] for _,b in related if b['url']]
        refs=list(dict.fromkeys(refs))[:5]
        limitation='Fonte única; requer confirmação independente.' if not independent else f'Corroborada por {len(independent)} domínio(s), mas a sobreposição foi inferida por termos compartilhados.'
        analysis={
          'type':'scientific_analysis','status':'analyzed','confidence':confidence,
          'claim':a['claim'],'summary':f"{a['title']}: {a['claim']}",
          'source_quality':round(a['quality'],2),'corroborating_sources':len(independent),
          'related_evidence':refs,'limitations':[limitation],
          'method':'sentence-extraction+source-quality+cross-source-token-overlap',
          'content_hash':hashlib.sha256(a['text'].encode()).hexdigest(),
        }
        row=dict(a['row']); row['analysis']=analysis; row['analysis_status']='analyzed'; row['analysis_confidence']=confidence
        out.append(row)
    return out


def main():
    p=argparse.ArgumentParser(); p.add_argument('--input',type=Path,required=True); p.add_argument('--output',type=Path,required=True); args=p.parse_args()
    rows=analyze(load(args.input)); args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('w',encoding='utf-8') as f:
        for row in rows: f.write(json.dumps(row,ensure_ascii=False)+'\n')
    print(json.dumps({'status':'ok','analyzed':len(rows),'with_cross_source_check':sum(1 for r in rows if r.get('analysis',{}).get('corroborating_sources',0)>0)},ensure_ascii=False))
if __name__=='__main__': main()
