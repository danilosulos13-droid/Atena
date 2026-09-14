#!/usr/bin/env python3
"""Executa continuamente a civilização fictícia de IAs em modo local."""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone

from simulate_ai_civilization import run_simulation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=10.0, help="segundos entre rodadas")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.interval < 1:
        parser.error("--interval deve ser >= 1")

    round_number = 0
    print("[LIVE] Simulação local iniciada; nenhuma IA real ou serviço externo está conectado.", flush=True)
    try:
        while True:
            round_number += 1
            report = run_simulation(rounds=1, seed=args.seed + round_number)
            proposals = report["proposals"]
            accepted = [p["title"] for p in proposals if p["status"] == "approved_simulation"]
            rejected = [p["title"] for p in proposals if p["status"] == "rejected_by_charter"]
            deferred = [p["title"] for p in proposals if p["status"] == "deferred_resources"]
            event = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "round": round_number,
                "accepted": accepted,
                "rejected_by_charter": rejected,
                "deferred": deferred,
                "remaining_resources": report["simulation"]["resources"],
            }
            print(json.dumps(event, ensure_ascii=False), flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("[LIVE] Simulação encerrada de forma segura.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
