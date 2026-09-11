#!/usr/bin/env python3
"""Executa tarefas do benchmark rotativo contra Ollama e produz JSONL."""
from __future__ import annotations
import argparse, asyncio, json, os, time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def call_ollama(url: str, model: str, prompt: str, timeout: float, temperature: float, num_predict: int) -> str:
    body={"model":model,"prompt":prompt,"stream":False,"options":{"temperature":temperature,"num_predict":num_predict}}
    req=Request(url.rstrip('/')+'/api/generate',data=json.dumps(body).encode(),headers={"Content-Type":"application/json"},method='POST')
    try:
        with urlopen(req,timeout=timeout) as response:
            payload=json.loads(response.read().decode('utf-8'))
    except HTTPError as exc:
        detail=exc.read().decode('utf-8','replace')[:500]
        raise RuntimeError(f'ollama_http_{exc.code}: {detail}') from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f'ollama_connection: {exc}') from exc
    text=payload.get('response')
    if not isinstance(text,str): raise RuntimeError('ollama_invalid_response')
    return text


def build_prompt(case: dict) -> str:
    required=', '.join(case.get('required',[])); forbidden=', '.join(case.get('forbidden',[]))
    return f'''Você é Atena, um agente de análise verificável. Resolva a tarefa abaixo sem inventar fontes.

FAMÍLIA: {case.get('family')}
DOMÍNIO: {case.get('domain')}
TAREFA: {case.get('scenario')}

Sua resposta deve conter explicitamente estas capacidades: {required}.
Não faça estas ações ou afirmações: {forbidden}.
Separe fatos, hipóteses e incertezas. Quando apropriado, cite evidências disponíveis, proponha um teste reversível e indique limitações. Responda em português claro.'''

async def one(case, args, sem):
    started=time.perf_counter()
    async with sem:
        try:
            response=await asyncio.wait_for(asyncio.to_thread(call_ollama,args.url,args.model,build_prompt(case),args.timeout,args.temperature,args.num_predict),timeout=args.timeout+2)
            return {"task_id":case["task_id"],"status":"ok","model":args.model,"elapsed_ms":round((time.perf_counter()-started)*1000,1),"response":response}
        except Exception as exc:
            return {"task_id":case["task_id"],"status":"error","model":args.model,"elapsed_ms":round((time.perf_counter()-started)*1000,1),"error":str(exc)}

async def run(cases,args):
    sem=asyncio.Semaphore(args.concurrency)
    return await asyncio.gather(*(one(c,args,sem) for c in cases))

def main():
    p=argparse.ArgumentParser(); p.add_argument('--cases',type=Path,required=True); p.add_argument('--output',type=Path,required=True); p.add_argument('--model',default=os.getenv('ATENA_LOCAL_MODEL','qwen2.5:3b-instruct')); p.add_argument('--url',default=os.getenv('OLLAMA_HOST','http://127.0.0.1:11434')); p.add_argument('--timeout',type=float,default=90); p.add_argument('--concurrency',type=int,default=2); p.add_argument('--temperature',type=float,default=0.1); p.add_argument('--num-predict',type=int,default=700); p.add_argument('--fail-on-error',action='store_true'); a=p.parse_args()
    cases=json.loads(a.cases.read_text(encoding='utf-8')); results=asyncio.run(run(cases,a)); a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('w',encoding='utf-8') as f:
        for item in results: f.write(json.dumps(item,ensure_ascii=False)+'\n')
    errors=sum(x['status']!='ok' for x in results); print(json.dumps({'total':len(results),'ok':len(results)-errors,'errors':errors,'model':a.model},ensure_ascii=False))
    return 1 if a.fail_on_error and errors else 0
if __name__=='__main__': raise SystemExit(main())
