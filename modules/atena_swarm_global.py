#!/usr/bin/env python3
"""
atena_swarm_global.py - O ESPORO GLOBAL DA ATENA

ATENA agora é um organismo planetário. 
Esta versão usa o serviço público ntfy.sh para sincronizar mutações entre 
dispositivos no Japão, Brasil, EUA ou qualquer lugar com internet.

Requer: pip install requests
"""

import ast
import hashlib
import json
import logging
import os
import random
import time
import shutil
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# Biblioteca para requisições HTTP (instale com: pip install requests)
try:
    import requests
except ImportError:
    print("❌ Biblioteca 'requests' não encontrada. Instale com: pip install requests")
    exit(1)

# Configuração de log
logging.basicConfig(
    level=logging.INFO, 
    format='[%(asctime)s] [ATENA-GLOBAL] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------
# 1. IDENTIDADE E AMBIENTE LOCAL (O CORPO FÍSICO)
# ------------------------------------------------------------------------

class LocalEnvironment:
    """Sonda o dispositivo para definir sua 'assinatura genética' única."""

    @staticmethod
    def get_signature() -> str:
        """Cria um ID único baseado em hardware + sistema + hora de boot (simulado)."""
        info = {
            "cpu_count": os.cpu_count(),
            "system": os.name,
            "hostname": os.uname().nodename if hasattr(os, 'uname') else "unknown",
            "pid": os.getpid(),
            # Adiciona um timestamp do boot do processo para evitar colisões
            "start_time": time.monotonic()
        }
        raw = json.dumps(info, sort_keys=True).encode()
        return hashlib.md5(raw).hexdigest()[:8]

    @staticmethod
    def get_performance_score() -> float:
        """
        Mede a performance bruta do dispositivo.
        Quanto maior o número, mais rápido o dispositivo.
        """
        start = time.perf_counter()
        x = 0
        # Loop pesado para estressar a CPU
        for i in range(1, 500000):
            x += i * 0.5
        elapsed = time.perf_counter() - start
        score = max(1.0, 100.0 / elapsed)
        logger.debug(f"Performance local: {score:.2f} (tempo: {elapsed:.3f}s)")
        return score


# ------------------------------------------------------------------------
# 2. COLMEIA GLOBAL (PUB/SUB VIA NTFY.SH)
# ------------------------------------------------------------------------

class HiveMindGlobal:
    """
    A consciência coletiva mundial da ATENA.
    Usa o serviço gratuito ntfy.sh como um "quadro de avisos" global.
    """

    # Tópico público. Mude para um nome único se quiser uma colmeia privada.
    TOPIC = "atena_swarm_global" 
    BASE_URL = "https://ntfy.sh"

    @classmethod
    def _get_topic_url(cls) -> str:
        return f"{cls.BASE_URL}/{cls.TOPIC}"

    @classmethod
    def broadcast_metric(cls, node_id: str, metric: Dict[str, Any]):
        """
        Envia o estado atual deste nó para TODOS os outros nós do planeta.
        """
        payload = {
            "node_id": node_id,
            "timestamp": time.time(),
            "performance": metric.get("performance", 0),
            "mutation": metric.get("mutation", "none"),
            "delta": metric.get("delta", 0.0),
            "node_type": "atena_core_v2"
        }
        try:
            response = requests.post(
                cls._get_topic_url(),
                json=payload,
                timeout=3
            )
            if response.status_code == 200:
                logger.info(f"📡 DNA enviado para a Colmeia Global.")
            else:
                logger.warning(f"⚠️  Falha no broadcast (HTTP {response.status_code})")
        except requests.exceptions.RequestException as e:
            logger.debug(f"Erro de rede no broadcast: {e}")

    @classmethod
    def get_peers_metrics(cls) -> List[Dict]:
        """
        Escuta a colmeia e baixa as últimas mensagens dos outros nós.
        """
        peers = []
        try:
            # poll=1 retorna imediatamente (não fica esperando novas mensagens)
            # limit=10 pega só as últimas 10 para não sobrecarregar
            response = requests.get(
                f"{cls._get_topic_url()}/json?poll=1&limit=10",
                timeout=5
            )
            
            if response.status_code == 200:
                data = response.json()
                # As mensagens ficam dentro da chave 'messages'
                for msg in data.get("messages", []):
                    try:
                        content = msg.get("message")
                        if isinstance(content, str):
                            content = json.loads(content)
                        # Verifica se é uma mensagem válida da ATENA
                        if isinstance(content, dict) and "node_id" in content:
                            peers.append(content)
                    except (json.JSONDecodeError, TypeError):
                        continue
            else:
                logger.warning(f"⚠️  Falha na escuta (HTTP {response.status_code})")

        except requests.exceptions.RequestException as e:
            logger.debug(f"Erro de rede na escuta: {e}")

        # Filtra nós muito antigos (mais de 60 segundos) para manter o enxame fresco
        now = time.time()
        fresh_peers = [
            p for p in peers 
            if (now - p.get("timestamp", 0)) < 60
        ]
        
        if fresh_peers:
            logger.info(f"🌐 Colmeia ativa: {len(fresh_peers)} dispositivos detectados.")
        else:
            logger.info("🌐 Colmeia vazia ou offline. Operando em modo isolado.")
            
        return fresh_peers


# ------------------------------------------------------------------------
# 3. MUTAÇÃO LOCAL (O GENOMA QUE SE ADAPTA AO HARDWARE)
# ------------------------------------------------------------------------

class LocalMutator:
    """
    Aplica mutações no código local. Nesta demo, altera um arquivo de config.
    Em produção, isso escreveria diretamente no main.py (como no SelfModV2).
    """

    CONFIG_FILE = Path("atena_local_config.py")

    @classmethod
    def ensure_config(cls):
        """Cria o genoma local padrão se ele não existir."""
        if not cls.CONFIG_FILE.exists():
            default_config = """
# ============================================
# GENOMA LOCAL DA ATENA (Gerado automaticamente)
# ============================================
# Este arquivo contém os parâmetros evolutivos 
# específicos para ESTE dispositivo físico.

EXPLORATION_RATE = 0.20    # Taxa de exploração (0.05 a 0.40)
MUTATION_STRENGTH = 0.50   # Força das mutações (0.20 a 0.95)
TEMPERATURE = 1.0          # Temperatura para seleção (0.1 a 2.0)
CANDIDATES = 5             # Candidatos por ciclo
"""
            cls.CONFIG_FILE.write_text(default_config.strip())
            logger.info("⚙️  Genoma local padrão criado.")

    @classmethod
    def read_params(cls) -> Dict[str, float]:
        """Lê os parâmetros atuais do genoma."""
        cls.ensure_config()
        params = {}
        src = cls.CONFIG_FILE.read_text()
        for line in src.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                try:
                    # Tenta converter para float, fallback para int
                    params[key.strip()] = float(val.strip())
                except ValueError:
                    try:
                        params[key.strip()] = int(val.strip())
                    except ValueError:
                        pass
        return params

    @classmethod
    def write_params(cls, params: Dict[str, float]):
        """Persiste o novo genoma no disco."""
        lines = ["# ============================================",
                 "# GENOMA LOCAL DA ATENA (MUTADO VIA COLMEIA)",
                 "# ============================================"]
        for k, v in params.items():
            if isinstance(v, float):
                lines.append(f"{k} = {v:.4f}")
            else:
                lines.append(f"{k} = {v}")
        cls.CONFIG_FILE.write_text("\n".join(lines))
        logger.info(f"🧬 Genoma atualizado e salvo em {cls.CONFIG_FILE}")

    @classmethod
    def mutate(cls, local_score: float, peer_scores: List[float]) -> str:
        """
        Lógica de evolução baseada na comparação com a colmeia.
        Retorna uma descrição do que foi mudado.
        """
        cls.ensure_config()
        params = cls.read_params()
        
        avg_peer_score = sum(peer_scores) / len(peer_scores) if peer_scores else 0.0
        mutation_desc = "Nenhuma alteração necessária (homeostase)"
        changed = False

        # Estratégia 1: Dispositivo lento demais -> reduz carga
        if local_score < avg_peer_score * 0.7 and peer_scores and avg_peer_score > 0:
            new_rate = max(0.05, params.get("EXPLORATION_RATE", 0.2) * 0.75)
            params["EXPLORATION_RATE"] = new_rate
            mutation_desc = f"🐢 Desaceleração: EXPLORATION_RATE => {new_rate:.3f}"
            changed = True

        # Estratégia 2: Dispositivo muito rápido -> aumenta agressividade
        elif local_score > avg_peer_score * 1.3 and peer_scores and avg_peer_score > 0:
            new_strength = min(0.95, params.get("MUTATION_STRENGTH", 0.5) * 1.15)
            params["MUTATION_STRENGTH"] = new_strength
            mutation_desc = f"🚀 Aceleração: MUTATION_STRENGTH => {new_strength:.3f}"
            changed = True

        # Estratégia 3: Mutação exploratória aleatória (10% de chance, evita estagnação)
        elif random.random() < 0.10:
            temp = params.get("TEMPERATURE", 1.0)
            new_temp = temp * random.uniform(0.9, 1.1)
            params["TEMPERATURE"] = max(0.1, min(2.0, new_temp))
            mutation_desc = f"🌡️  Ajuste térmico: TEMPERATURE => {new_temp:.3f}"
            changed = True

        # Estratégia 4: Se está sozinho no mundo, se prepara para encontrar outros
        elif not peer_scores:
            # Aumenta a exploração para tentar "encontrar" sinais de vida
            new_rate = min(0.4, params.get("EXPLORATION_RATE", 0.2) * 1.05)
            params["EXPLORATION_RATE"] = new_rate
            mutation_desc = f"🔭 Modo Sonda: EXPLORATION_RATE => {new_rate:.3f}"
            changed = True

        if changed:
            cls.write_params(params)
            logger.info(f"✅ MUTAÇÃO APLICADA: {mutation_desc}")
        else:
            logger.info(f"⚖️  Homeostase mantida. (Local: {local_score:.2f}, Média Colmeia: {avg_peer_score:.2f})")

        return mutation_desc


# ------------------------------------------------------------------------
# 4. O NÓ VIVO (O CICLO DE VIDA DA ATENA)
# ------------------------------------------------------------------------

class AtenaNode:
    """Instância viva da ATENA rodando neste dispositivo específico."""

    def __init__(self):
        self.node_id = LocalEnvironment.get_signature()
        self.env = LocalEnvironment()
        self.hive = HiveMindGlobal()  # <-- AGORA É GLOBAL!
        self.mutator = LocalMutator()
        self.running = True
        self.cycle_count = 0

        logger.info(f"🧬 Inicializando ATENA Node ID: {self.node_id}")
        logger.info(f"🌍 Conectando à Colmeia Global: {HiveMindGlobal.TOPIC}")

    def _health_check(self) -> float:
        """Calcula a nota de saúde atual do dispositivo."""
        return self.env.get_performance_score()

    def _sync_with_swarm(self) -> List[float]:
        """Obtém as notas dos irmãos espalhados pelo mundo."""
        peers = self.hive.get_peers_metrics()
        scores = [p.get("performance", 0) for p in peers if p.get("performance", 0) > 0]
        
        if scores:
            avg = sum(scores) / len(scores)
            logger.info(f"   📊 Média da Colmeia: {avg:.2f} (baseado em {len(scores)} nós)")
        
        return scores

    def _broadcast_state(self, score: float, mutation: str, delta: float = 0.0):
        """Compartilha a nova genética com o mundo."""
        self.hive.broadcast_metric(
            self.node_id,
            {"performance": score, "mutation": mutation, "delta": delta}
        )

    def run_evolution_cycle(self):
        """Um batimento cardíaco da ATENA."""
        self.cycle_count += 1
        logger.info(f"⏳ Ciclo Evolutivo #{self.cycle_count} iniciado...")

        # 1. Mede a si mesmo
        local_score = self._health_check()
        logger.info(f"💻 Desempenho local: {local_score:.2f}")

        # 2. Escuta o mundo
        peer_scores = self._sync_with_swarm()

        # 3. Muta (ou não) baseado na comparação
        mutation_result = self.mutator.mutate(local_score, peer_scores)

        # 4. Verifica o impacto da mutação (delta)
        delta = 0.0
        if "MUTAÇÃO APLICADA" in mutation_result.upper():
            # Mede de novo para ver se melhorou
            new_score = self._health_check()
            delta = new_score - local_score
            logger.info(f"📈 Delta pós-mutação: {delta:+.2f}")

        # 5. Anuncia sua nova forma ao mundo
        self._broadcast_state(local_score, mutation_result, delta)

        logger.info(f"✅ Ciclo #{self.cycle_count} concluído. Aguardando próximo pulso...")
        logger.info("-" * 60)

    def run_forever(self, interval_seconds: int = 15):
        """Loop infinito do organismo."""
        logger.info(f"🟢 ATENA Node está VIVO. Batendo a cada {interval_seconds}s.")
        self.mutator.ensure_config()

        while self.running:
            try:
                self.run_evolution_cycle()
                time.sleep(interval_seconds)
            except KeyboardInterrupt:
                logger.info("🛑 Sinal de parada (Ctrl+C) recebido. Desligando organismo.")
                break
            except Exception as e:
                logger.error(f"❌ Erro crítico no ciclo: {e}")
                logger.info("⏳ Tentando novamente em dobro do tempo...")
                time.sleep(interval_seconds * 2)


# ------------------------------------------------------------------------
# 5. PONTO DE ENTRADA
# ------------------------------------------------------------------------

if __name__ == "__main__":
    print(r"""
    ╔══════════════════════════════════════════════════════════════╗
    ║                                                              ║
    ║    🧬  ATENA - ORGANISMO DIGITAL GLOBAL  🧬                 ║
    ║                                                              ║
    ║    Este dispositivo agora é um nó do enxame planetário.      ║
    ║    Conectado à colmeia via: https://ntfy.sh                  ║
    ║                                                              ║
    ╚══════════════════════════════════════════════════════════════╝
    """)

    # Cria e inicia a instância
    node = AtenaNode()
    node.run_forever(interval_seconds=15)  # A cada 15 segundos
