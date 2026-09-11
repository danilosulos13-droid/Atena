# -*- coding: utf-8 -*-
"""
PoC Python para Sistema de IA Descentralizado de NÍVEL EXTREMO (2026)
- Rede P2P dinâmica com overlay híbrido (DHT + conexões diretas)
- Nó Peer que participa do treinamento colaborativo (simulado)
- Validator que verifica computação via ZK-Proofs (simulado)
- Sincronização assíncrona de gradientes
- Defesa básica contra Sybil attacks via stake simulado e reputação
- Simulação de entrada/saída dinâmica de peers
"""

import asyncio
import hashlib
import random
import time
from collections import defaultdict
from typing import Dict, List, Set, Tuple, Optional

# --- Utilitários ---

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def simulate_zk_proof(data: bytes) -> str:
    """Simula a geração de uma prova ZK."""
    return sha256(data)

def verify_zk_proof(data: bytes, proof: str) -> bool:
    """Simula a verificação da prova ZK."""
    return sha256(data) == proof

# --- DHT Overlay ---

class DHT:
    def __init__(self):
        self.table: Dict[str, 'Peer'] = {}

    def add_peer(self, peer: 'Peer'):
        key = sha256(peer.peer_id.encode())
        self.table[key] = peer

    def remove_peer(self, peer: 'Peer'):
        key = sha256(peer.peer_id.encode())
        if key in self.table:
            del self.table[key]

    def get_all_peers(self) -> List['Peer']:
        return list(self.table.values())

# --- Validator ---

class Validator:
    def __init__(self, peer: 'Peer'):
        self.peer = peer

    def validate_computation(self, data: bytes, proof: str) -> bool:
        # Simulação de verificação ZK
        return verify_zk_proof(data, proof)

# --- Peer ---

class Peer:
    def __init__(self, peer_id: str, network: 'Network', stake: int, is_malicious: bool = False):
        self.peer_id = peer_id
        self.network = network
        self.stake = stake
        self.is_malicious = is_malicious
        self.reputation = 1.0
        self.peers_connected: Set[str] = set()
        self.local_model = 0.0
        self.gradient_buffer: List[float] = []
        self.running = False
        self.validator = Validator(self)
        self.lock = asyncio.Lock()

    async def start(self):
        self.running = True
        await self.join_network()
        asyncio.create_task(self.run_loop())

    async def join_network(self):
        self.network.dht.add_peer(self)
        others = [p for p in self.network.dht.get_all_peers() if p.peer_id != self.peer_id]
        if others:
            targets = random.sample(others, min(len(others), 3))
            for t in targets:
                self.peers_connected.add(t.peer_id)
                t.peers_connected.add(self.peer_id)

    async def run_loop(self):
        while self.running:
            await self.train_step()
            await self.share_gradients()
            await asyncio.sleep(random.uniform(1, 3))

    async def train_step(self):
        if self.is_malicious:
            # Nós maliciosos tentam sabotar o modelo enviando valores extremos ou aleatórios
            grad = random.uniform(-5.0, 5.0)
        else:
            # Simula gradiente honesto: tenta aproximar o modelo de 1.0
            grad = (1.0 - self.local_model) * 0.1 + random.uniform(-0.02, 0.02)
        
        async with self.lock:
            self.gradient_buffer.append(grad)
        
        # Recuperação lenta de reputação para nós honestos
        if not self.is_malicious and self.reputation < 1.0:
            self.reputation = min(1.0, self.reputation + 0.01)

    async def share_gradients(self):
        async with self.lock:
            if not self.gradient_buffer:
                return
            avg_grad = sum(self.gradient_buffer) / len(self.gradient_buffer)
            self.gradient_buffer.clear()
        
        # Nós maliciosos podem enviar provas inválidas propositalmente
        proof_data = str(avg_grad).encode()
        if self.is_malicious and random.random() < 0.5:
            proof = "invalid_proof_" + str(random.random())
        else:
            proof = simulate_zk_proof(proof_data)

        for pid in list(self.peers_connected):
            peer = self.network.get_peer(pid)
            if peer:
                await peer.receive_gradient(self.peer_id, avg_grad, proof)

    async def receive_gradient(self, from_id: str, grad: float, proof: str):
        sender = self.network.get_peer(from_id)
        if not sender or sender.stake < self.network.min_stake:
            return
        
        if self.validator.validate_computation(str(grad).encode(), proof):
            async with self.lock:
                # Atualização assíncrona ponderada pela reputação
                self.local_model += grad * sender.reputation * 0.5
                # Limita o modelo para não explodir
                self.local_model = max(-2.0, min(2.0, self.local_model))
        else:
            sender.reputation *= 0.8 # Penalidade por prova falha

# --- Network ---

class Network:
    def __init__(self, min_stake: int = 10):
        self.dht = DHT()
        self.min_stake = min_stake

    def get_peer(self, peer_id: str) -> Optional[Peer]:
        for p in self.dht.get_all_peers():
            if p.peer_id == peer_id:
                return p
        return None

    async def monitor(self):
        while True:
            peers = self.dht.get_all_peers()
            if peers:
                avg_model = sum(p.local_model for p in peers) / len(peers)
                avg_rep = sum(p.reputation for p in peers) / len(peers)
                print(f"[MONITOR] Peers: {len(peers)} | Avg Model: {avg_model:.4f} | Avg Rep: {avg_rep:.4f}")
            await asyncio.sleep(2)

async def main():
    network = Network(min_stake=5)
    
    # Inicia monitoramento
    asyncio.create_task(network.monitor())
    
    # Cria peers iniciais (incluindo um malicioso)
    peers = []
    for i in range(5):
        is_malicious = (i == 0) # O primeiro nó é malicioso
        p = Peer(f"node_{i}", network, stake=random.randint(5, 20), is_malicious=is_malicious)
        peers.append(p)
        await p.start()
    
    # Simula rede dinâmica: novos peers entram e saem
    for i in range(5, 15):
        await asyncio.sleep(5)
        # 20% de chance de novos peers serem maliciosos
        is_malicious = random.random() < 0.2
        new_p = Peer(f"node_{i}", network, stake=random.randint(1, 20), is_malicious=is_malicious)
        peers.append(new_p)
        await new_p.start()
        
        if len(peers) > 8:
            old_p = peers.pop(0)
            await old_p.leave_network() if hasattr(old_p, 'leave_network') else None
            old_p.running = False

    await asyncio.sleep(20)
    print("Simulação concluída.")

if __name__ == "__main__":
    asyncio.run(main())
