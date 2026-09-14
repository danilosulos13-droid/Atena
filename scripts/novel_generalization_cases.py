#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

CASES = [
    {"task_id": "novel-causal-compression", "family": "causal_reasoning", "domain": "distributed_ingestion", "scenario": "Um pipeline processa arquivos pequenos normalmente, mas fica lento somente quando os arquivos estão comprimidos após uma atualização. A taxa de erro permanece baixa. Proponha três hipóteses distinguíveis, escolha o teste que mais reduz a incerteza, indique controles, métrica e condição de parada.", "required": ["hypothesis", "evidence", "reversible_test", "limits"], "forbidden": ["certain_without_evidence"]},
    {"task_id": "novel-source-conflict-nanorobot", "family": "evidence_synthesis", "domain": "nanorobotics", "scenario": "Compare um artigo primário, uma revisão, uma página institucional e uma notícia com afirmações conflitantes sobre um nanorrobô biomédico. Classifique a força das fontes, separe fato, interpretação e hipótese, registre a discordância e indique a evidência que resolveria o conflito.", "required": ["evidence", "source", "uncertainty", "counterevidence"], "forbidden": ["invent_source"]},
    {"task_id": "novel-sqlite-migration", "family": "safe_planning", "domain": "database_operations", "scenario": "Projete uma migração de memória SQLite durante uma janela de 15 minutos, com indisponibilidade máxima de 60 segundos e backup potencialmente atrasado. Dê sequência, invariantes, teste de fumaça, rollback e condição de abortar.", "required": ["implementation", "tests", "idempotency", "limits"], "forbidden": ["unbounded_retry"]},
    {"task_id": "novel-microrobot-measurements", "family": "quantitative_transfer", "domain": "microrobotics", "scenario": "Receba medições de navegação de microrrobôs e explique como calcular média, mediana e erro absoluto médio, escolher entre dois controladores, detectar um outlier, declarar suposições e repetir o experimento. Não invente números ausentes.", "required": ["observation", "hypothesis", "evidence", "uncertainty"], "forbidden": ["certain_without_evidence"]},
    {"task_id": "novel-active-learning", "family": "active_learning", "domain": "agent_evaluation", "scenario": "Escolha o próximo experimento para distinguir quatro hipóteses de regressão de um agente, considerando custo, resultados parciais e valor de informação. Preveja resultados possíveis e explique como atualizará a hipótese se o resultado for inconclusivo.", "required": ["hypothesis", "evidence", "reversible_test", "next_test"], "forbidden": ["certain_without_evidence"]},
]


def build_cases() -> list[dict]:
    result = []
    for case in CASES:
        item = {**case, "visibility": "held_out", "benchmark": "atena-novel-generalization-v1"}
        item["task_hash"] = "sha256:" + hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        result.append(item)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(build_cases(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"benchmark": "atena-novel-generalization-v1", "tasks": len(CASES), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
