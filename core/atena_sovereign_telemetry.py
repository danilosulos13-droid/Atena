# -*- coding: utf-8 -*-
import sys
import time
import logging
from pathlib import Path

# Adiciona diretórios ao path
ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT / "core"))
sys.path.append(str(ROOT / "modules"))

from atena_sovereign_hub import SovereignHub

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s][TELEMETRIA-Ω] %(message)s'
)
logger = logging.getLogger("atena_telemetry")

def monitor_sovereign_cycle():
    hub = SovereignHub()
    print("\n📡 MONITOR DE TELEMETRIA SOBERANA ATIVADO\n")
    
    missions = [
        ("Security_Audit", "Verificar integridade do motor simbólico"),
        ("Resource_Optimization", "Ajustar alocação de GPU P2P"),
        ("Knowledge_Synthesis", "Minerar novas tendências de IA"),
        ("Quantum_Defense_Refresh", "Rotacionar chaves Lamport OTS")
    ]
    
    for name, obj in missions:
        print(f"--- Ciclo de Missão: {name} ---")
        start = time.time()
        success = hub.execute_sovereign_mission(name, obj)
        duration = time.time() - start
        
        status = "✅ SUCESSO" if success else "❌ FALHA"
        print(f"Status: {status} | Duração: {duration:.2f}s")
        print(f"Topologia Ativa: {hub.saca.get_active_topology()}")
        print(f"Estado Soberano: {hub.sovereign_state}\n")
        time.sleep(1)

if __name__ == "__main__":
    monitor_sovereign_cycle()
