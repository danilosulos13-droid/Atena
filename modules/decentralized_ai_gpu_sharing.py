# -*- coding: utf-8 -*-
"""
ATENA Ω — PROTOCOLO HYDRA DE ORQUESTRAÇÃO DE RECURSOS (GPU SHARING)
Módulo M12: Implementação de Resiliência Extrema (Checkpoint & Failover).
- Monitoramento de Heartbeat dos nós provedores
- Migração automática de tarefas em caso de falha de conexão
- Recuperação de estado de processamento (Checkpointing)
"""

import asyncio
import hashlib
import random
import time
from typing import Dict, List, Optional, Set

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

class GPUNode:
    def __init__(self, node_id: str, vram_gb: int, tflops: float):
        self.node_id = node_id
        self.vram_gb = vram_gb
        self.tflops = tflops
        self.available_vram = vram_gb
        self.is_busy = False
        self.is_online = True
        self.credits = 100.0

    def allocate(self, required_vram: int) -> bool:
        if self.is_online and not self.is_busy and self.available_vram >= required_vram:
            self.available_vram -= required_vram
            if self.available_vram == 0:
                self.is_busy = True
            return True
        return False

    def release(self, released_vram: int):
        self.available_vram = min(self.vram_gb, self.available_vram + released_vram)
        if self.available_vram > 0:
            self.is_busy = False

class GPUResourceMarketplace:
    def __init__(self):
        self.nodes: Dict[str, GPUNode] = {}
        self.tasks_queue: List[Dict] = []
        self.active_tasks: Dict[str, Dict] = {} # task_id -> task_info

    def register_node(self, node: GPUNode):
        self.nodes[node.node_id] = node
        print(f"[HYDRA MARKET] Nó GPU registrado: {node.node_id} ({node.vram_gb}GB VRAM, {node.tflops} TFLOPS)")

    def submit_task(self, task_id: str, required_vram: int, workload_size: float):
        task = {
            "task_id": task_id,
            "required_vram": required_vram,
            "workload_size": workload_size,
            "progress": 0.0,
            "assigned_node": None
        }
        self.tasks_queue.append(task)
        print(f"[HYDRA MARKET] Tarefa submetida: {task_id} (Requer {required_vram}GB VRAM)")

    async def orchestrate(self):
        while True:
            # 1. Verificar falhas em nós ativos (Failover)
            for task_id, task in list(self.active_tasks.items()):
                node = self.nodes.get(task["assigned_node"])
                if not node or not node.is_online:
                    print(f"[HYDRA FAILOVER] ⚠️ Falha detectada no nó {task['assigned_node']}! Migrando tarefa {task_id} (Progresso: {task['progress']:.1f}%)")
                    task["assigned_node"] = None
                    # Redimensiona requisito se for migração (fragmentação adaptativa)
                    task["required_vram"] = min(task["required_vram"], 16) # Exemplo: adapta para nós menores se necessário
                    self.tasks_queue.insert(0, task)
                    del self.active_tasks[task_id]

            # 2. Alocar tarefas
            if self.tasks_queue:
                task = self.tasks_queue.pop(0)
                assigned = False
                sorted_nodes = sorted(
                    [n for n in self.nodes.values() if n.is_online and not n.is_busy and n.available_vram >= task["required_vram"]],
                    key=lambda x: x.available_vram
                )
                if sorted_nodes:
                    node = sorted_nodes[0]
                    if node.allocate(task["required_vram"]):
                        task["assigned_node"] = node.node_id
                        self.active_tasks[task["task_id"]] = task
                        print(f"[HYDRA ORCHESTRATOR] 🚀 Tarefa {task['task_id']} alocada para {node.node_id} (VRAM: {task['required_vram']}GB | Progresso: {task['progress']:.1f}%)")
                        asyncio.create_task(self._process_task(node, task))
                        assigned = True
                
                if not assigned:
                    self.tasks_queue.append(task)
            
            await asyncio.sleep(0.5)

    async def _process_task(self, node: GPUNode, task: Dict):
        try:
            total_work = task["workload_size"]
            # Simula processamento com checkpoints
            while task["progress"] < 100.0:
                if not node.is_online:
                    return # Sai silenciosamente, o orquestrador cuidará do failover
                
                await asyncio.sleep(0.5) # Passo de processamento
                step = (node.tflops / total_work) * 5 # Incremento de progresso
                task["progress"] = min(100.0, task["progress"] + step)
                
            # Finalização
            node.release(task["required_vram"])
            node.credits += total_work * 2.5
            if task["task_id"] in self.active_tasks:
                del self.active_tasks[task["task_id"]]
            print(f"[HYDRA ORCHESTRATOR] ✅ Tarefa {task['task_id']} concluída por {node.node_id}. Créditos: {node.credits:.1f}")
        except Exception as e:
            print(f"[HYDRA ERROR] Erro no nó {node.node_id}: {e}")

async def main():
    market = GPUResourceMarketplace()
    
    # Registro de nós
    alpha = GPUNode("gpu_node_alpha", 24, 150.0)
    beta = GPUNode("gpu_node_beta", 16, 100.0)
    gamma = GPUNode("gpu_node_gamma", 8, 50.0)
    
    market.register_node(alpha)
    market.register_node(beta)
    market.register_node(gamma)
    
    orchestrator_task = asyncio.create_task(market.orchestrate())
    
    # 1. Submeter tarefa pesada para o nó Alpha
    task_id = "critical_ai_training"
    market.submit_task(task_id, required_vram=20, workload_size=50.0)
    
    # 2. Aguardar progresso parcial
    await asyncio.sleep(2)
    
    # 3. SIMULAR FALHA CRÍTICA NO NÓ ALPHA
    print(f"\n[SYSTEM TEST] 🔥 Simulando queda de conexão no nó ALPHA...")
    alpha.is_online = False
    
    # 4. Observar migração e conclusão
    await asyncio.sleep(15)
    
    # 5. Mostrar status final dos créditos
    print("\n[HYDRA STATUS] Créditos finais:")
    for nid, node in market.nodes.items():
        print(f" - {nid}: {node.credits:.1f} (Online: {node.is_online})")
    
    orchestrator_task.cancel()
    print("\n[HYDRA TEST] Teste de Resiliência concluído.")

if __name__ == "__main__":
    asyncio.run(main())
