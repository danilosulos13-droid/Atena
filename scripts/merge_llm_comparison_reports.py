#!/usr/bin/env python3
import json
from pathlib import Path

root = Path('/home/ubuntu/Atena-IA')
log = Path('/tmp/atena_qwen_retry.log').read_text(encoding='utf-8', errors='replace')
start = log.rfind('\n{')
if start < 0:
    start = log.find('{')
qwen = json.loads(log[start + (1 if log[start] == '\n' else 0):])
llama = json.loads((root / 'analysis_reports/llama3.2_evaluation.json').read_text(encoding='utf-8'))
merged = {
    'benchmark': 'atena-llm-cognitive-comparison-v2',
    'endpoint': qwen.get('endpoint'),
    'models': {**qwen['models'], **llama['models']},
    'mitigations': qwen.get('mitigations', {}),
    'evaluations': qwen.get('evaluations', []) + llama.get('evaluations', []),
}
out = root / 'analysis_reports/llm_cognitive_comparison.json'
out.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(merged['models'], ensure_ascii=False, indent=2))
print('errors=', [(e['model'], e['task_id'], e['error']) for e in merged['evaluations'] if e.get('error')])
