#!/usr/bin/env bash
set -u
cd /home/ubuntu/Atena-IA
export PYTHONPATH="$PWD"
python3 -u scripts/llm_cognitive_evaluation.py > /tmp/atena_llm_comparison.log 2>&1
rc=$?
printf 'COMPARISON_EXIT=%s\n' "$rc"
tail -260 /tmp/atena_llm_comparison.log
exit "$rc"
