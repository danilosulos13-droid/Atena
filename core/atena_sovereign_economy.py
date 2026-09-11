#!/usr/bin/env python3
"""
ATENA Ω - MÓDULO M30: Protocolo de Economia Soberana
Implementa o sistema autônomo de incentivos, ledger de recursos e recompensas para nós P2P.
"""

import sys
import os
import time
import random
import json
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

class SovereignEconomyLedger:
    def __init__(self):
        self.ledger = []
        self.node_credits = {}

    def register_node_contribution(self, node_id: str, gpu_hours: float, storage_gb: float):
        reward = (gpu_hours * 12.5) + (storage_gb * 0.5)
        self.node_credits[node_id] = self.node_credits.get(node_id, 0.0) + reward
        
        transaction = {
            "tx_id": f"TX-{random.randint(100000, 999999)}",
            "timestamp": datetime.now().isoformat(),
            "node_id": node_id,
            "gpu_contributed_hours": gpu_hours,
            "storage_contributed_gb": storage_gb,
            "reward_minted": round(reward, 2)
        }
        self.ledger.append(transaction)
        return transaction

class SovereignEconomySimulator:
    def __init__(self):
        self.economy = SovereignEconomyLedger()

    def run_simulation(self):
        print("[M30] Inicializando o Protocolo de Economia Soberana...")
        nodes = ["NODE-ALPHA-01", "NODE-BETA-04", "NODE-GAMMA-09", "EDGE-NODE-77", "IOT-NODE-99"]
        
        simulated_txs = []
        for node in nodes:
            gpu = round(random.uniform(5.0, 50.0), 2)
            storage = round(random.uniform(100.0, 1000.0), 2)
            tx = self.economy.register_node_contribution(node, gpu, storage)
            simulated_txs.append(tx)
            print(f"    [OK] Contribuição registrada para {node}: {gpu}h GPU, {storage}GB Armazenamento -> Recompensa: {tx['reward_minted']} AetherCredits")
            time.sleep(0.1)

        report = {
            "protocol": "Sovereign Economy M30",
            "timestamp": datetime.now().isoformat(),
            "total_transactions": len(simulated_txs),
            "total_credits_minted": sum(t["reward_minted"] for t in simulated_txs),
            "ledger": simulated_txs,
            "status": "ECONOMY_OPERATIONAL"
        }

        output_path = "/home/ubuntu/Atena-IA/docs/SOVEREIGN_ECONOMY_LEDGER.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=4, ensure_ascii=False)
        print(f"[OK] Ledger da Economia Soberana salvo em {output_path}")
        return report

if __name__ == "__main__":
    sim = SovereignEconomySimulator()
    sim.run_simulation()
