# -*- coding: utf-8 -*-
"""
ATENA Ω — SIMULADOR DE ATAQUE BIZANTINO E CONSENSO P2P (MELHORIA M17)
Objetivo: Testar a resiliência da rede contra ataques coordenados de 51% sob estresse.
"""

import asyncio
import random
import time
import hashlib
from typing import List, Dict, Set, Optional

# --- Utilitários de Segurança ---
def sha256(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()

class ByzantinePeer:
    """
    Representa um nó malicioso que tenta coordenar um ataque de consenso.
    """
    def __init__(self, peer_id: str, network: 'ExtremeNetwork', is_attacker: bool = False):
        self.peer_id = peer_id
        self.network = network
        self.is_attacker = is_attacker
        self.reputation = 1.0
        self.local_model = 0.0
        self.running = True

    async def run(self):
        while self.running:
            # Simula latência de rede extrema (Jitter)
            await asyncio.sleep(random.uniform(0.1, 2.0) * self.network.stress_level)
            
            if self.is_attacker:
                # ATAQUE COORDENADO: Tenta forçar o modelo para 999.0
                proposed_grad = 999.0
            else:
                # Comportamento Honesto: Tenta convergir para 1.0
                proposed_grad = (1.0 - self.local_model) * 0.1
            
            # Broadcast para a rede (com chance de perda de pacotes)
            if random.random() > self.network.packet_loss:
                await self.network.broadcast_gradient(self.peer_id, proposed_grad)

    async def receive_gradient(self, from_id: str, grad: float):
        sender = self.network.get_peer(from_id)
        if sender:
            # Ponderação por reputação para mitigar ataques
            weight = sender.reputation
            self.local_model = (self.local_model + grad * weight) / (1 + weight)
            
            # Detecção Simples de Anomalia (Defesa da Atena)
            if abs(grad) > 10.0: # Limiar de sanidade
                sender.reputation *= 0.5 # Penaliza severamente
                # print(f"[DEFESA] Nó {self.peer_id} detectou anomalia de {from_id}! Reputação: {sender.reputation:.2f}")

class ExtremeNetwork:
    def __init__(self, stress_level: float = 1.0, packet_loss: float = 0.1):
        self.peers: Dict[str, ByzantinePeer] = {}
        self.stress_level = stress_level
        self.packet_loss = packet_loss
        self.attack_success = False

    def get_peer(self, peer_id: str) -> Optional[ByzantinePeer]:
        return self.peers.get(peer_id)

    async def broadcast_gradient(self, from_id: str, grad: float):
        for pid, peer in self.peers.items():
            if pid != from_id:
                # Simula rede P2P (envio assíncrono)
                asyncio.create_task(peer.receive_gradient(from_id, grad))

    async def monitor(self):
        while True:
            honest_peers = [p for p in self.peers.values() if not p.is_attacker]
            attacker_peers = [p for p in self.peers.values() if p.is_attacker]
            
            if honest_peers:
                avg_model = sum(p.local_model for p in honest_peers) / len(honest_peers)
                avg_rep = sum(p.reputation for p in self.peers.values()) / len(self.peers)
                
                print(f"[MONITOR] Honest Model: {avg_model:.2f} | Avg Rep: {avg_rep:.2f} | Stress: {self.stress_level}")
                
                if avg_model > 100.0:
                    self.attack_success = True
                    print("⚠️ ALERTA: O ataque de consenso foi BEM SUCEDIDO! A rede foi dominada.")
                    break
            
            await asyncio.sleep(2)

async def main():
    # Cenário de Estresse Extremo
    # 6 atacantes vs 4 honestos (Ataque de 60% - Superando o limite de 51%)
    network = ExtremeNetwork(stress_level=3.0, packet_loss=0.3)
    
    print("🔥 Iniciando Simulação de Ataque de 60% sob Estresse de Rede...")
    
    # Criar Atacantes
    for i in range(6):
        p = ByzantinePeer(f"attacker_{i}", network, is_attacker=True)
        network.peers[p.peer_id] = p
        asyncio.create_task(p.run())
        
    # Criar Honestos
    for i in range(4):
        p = ByzantinePeer(f"honest_{i}", network, is_attacker=False)
        network.peers[p.peer_id] = p
        asyncio.create_task(p.run())
        
    # Inicia Monitoramento
    monitor_task = asyncio.create_task(network.monitor())
    
    try:
        # Aguarda 30 segundos de batalha
        await asyncio.wait_for(monitor_task, timeout=30)
    except asyncio.TimeoutError:
        print("\n✅ VITÓRIA: Os nós honestos resistiram ao ataque de 60% apesar do estresse!")
    finally:
        for p in network.peers.values():
            p.running = False
        print("Simulação encerrada.")

if __name__ == "__main__":
    asyncio.run(main())
