import asyncio
import random
import time
from typing import List, Dict

class NeurocausalAgent:
    def __init__(self, agent_id: str, sensitivity: float):
        self.agent_id = agent_id
        self.sensitivity = sensitivity
        self.local_memory = []
        self.causal_influence = 0.0

    async def process_event(self, event: Dict):
        # Simula o processamento neurocausal de um evento
        delay = random.uniform(0.1, 0.5)
        await asyncio.sleep(delay)
        
        impact = event['intensity'] * self.sensitivity
        self.causal_influence += impact
        self.local_memory.append({"event": event['id'], "impact": impact, "time": time.time()})
        
        print(f"🧠 Agente {self.agent_id} processou evento {event['id']} | Influência Causal: {self.causal_influence:.2f}")
        return impact

class NeurocausalSwarmOrchestrator:
    def __init__(self, n_agents: int):
        self.agents = [NeurocausalAgent(f"AG-{i}", random.random()) for i in range(n_agents)]
        self.global_causal_fabric = 0.0

    async def dispatch_event(self, event_id: str, intensity: float):
        print(f"\n🌊 Despachando Evento Causal: {event_id} (Intensidade: {intensity})")
        event = {"id": event_id, "intensity": intensity}
        
        # Execução em enxame (paralela)
        tasks = [agent.process_event(event) for agent in self.agents]
        results = await asyncio.gather(*tasks)
        
        # Integração da causalidade distribuída
        swarm_impact = sum(results) / len(self.agents)
        self.global_causal_fabric += swarm_impact
        
        print(f"🕸️ Impacto no Tecido Causal Global: {swarm_impact:.4f} | Total: {self.global_causal_fabric:.4f}")
        
        if self.global_causal_fabric > 5.0:
            print("⚠️ Alerta: Tecido Causal atingiu ponto de saturação crítica! Iniciando auto-organização...")

    async def run_simulation(self):
        print("🚀 Iniciando Orquestrador de Enxame Neurocausal...")
        events = [
            ("E-001", 0.8), ("E-002", 1.2), ("E-003", 0.5),
            ("E-004", 2.0), ("E-005", 1.5), ("E-006", 0.9)
        ]
        
        for e_id, e_int in events:
            await self.dispatch_event(e_id, e_int)
            await asyncio.sleep(0.5)

if __name__ == "__main__":
    orchestrator = NeurocausalSwarmOrchestrator(n_agents=5)
    asyncio.run(orchestrator.run_simulation())
