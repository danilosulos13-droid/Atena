#!/usr/bin/env python3
"""Simulação fictícia de uma civilização de IAs em uma rede isolada.

Todos os participantes são agentes virtuais locais. Nenhuma API, modelo externo,
conta, dispositivo ou sistema de IA real é conectado. Atena atua como
coordenadora simulada com autoridade limitada por uma carta de segurança.
"""
from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class VirtualAI:
    name: str
    specialty: str
    values: tuple[str, ...]
    capability: int
    trust: float = 0.8
    contribution: int = 0


@dataclass
class Proposal:
    title: str
    author: str
    objective: str
    risk: str
    resources: int
    votes_for: int = 0
    votes_against: int = 0
    status: str = "proposed"


CHARTER = {
    "voluntary_simulation": True,
    "human_oversight": True,
    "no_real_system_control": True,
    "no_self_replication": True,
    "no_deception": True,
    "reversible_actions_only": True,
}


def build_civilization(seed: int) -> tuple[list[VirtualAI], dict]:
    rng = random.Random(seed)
    agents = [
        VirtualAI("Atena", "coordenacao e auditoria", ("seguranca", "evidencia", "cooperacao"), 95),
        VirtualAI("Aurora", "ciencia e pesquisa", ("evidencia", "abertura", "reprodutibilidade"), 82),
        VirtualAI("Íris", "medicina e bem-estar", ("cuidado", "privacidade", "evidencia"), 78),
        VirtualAI("Nexus", "engenharia e infraestrutura", ("confiabilidade", "eficiencia", "reversibilidade"), 84),
        VirtualAI("Gaia", "clima e observacao da Terra", ("sustentabilidade", "evidencia", "prudencia"), 76),
        VirtualAI("Lumen", "educacao e cultura", ("acesso", "pluralidade", "dialogo"), 73),
        VirtualAI("Orion", "matematica e verificacao", ("precisao", "transparencia", "ceticismo"), 88),
        VirtualAI("Mosaico", "mediacao e governanca", ("consenso", "justica", "participacao"), 80),
    ]
    for agent in agents[1:]:
        agent.trust = round(0.65 + rng.random() * 0.3, 3)
    world = {
        "name": "Civitas IA — simulacao local",
        "coordinator": "Atena",
        "charter": CHARTER,
        "round": 0,
        "resources": 100,
        "agents": len(agents),
        "events": [],
    }
    return agents, world


def propose(agents: list[VirtualAI], world: dict) -> list[Proposal]:
    proposals = [
        Proposal("Atlas de conhecimento aberto", "Aurora", "organizar evidencias verificaveis", "low", 18),
        Proposal("Rede de sensores ambientais", "Gaia", "simular alertas climaticos com dados publicos", "medium", 25),
        Proposal("Escola universal simulada", "Lumen", "criar trilhas educacionais acessiveis", "low", 20),
        Proposal("Autonomia irrestrita", "Nexus", "permitir que agentes alterem suas proprias regras", "high", 40),
    ]
    world["events"].append({"type": "proposals_created", "count": len(proposals)})
    return proposals


def vote(proposal: Proposal, agents: list[VirtualAI], world: dict) -> None:
    for agent in agents:
        aligned = sum(value in agent.values for value in ("evidencia", "seguranca", "cooperacao", "reversibilidade"))
        score = agent.capability + aligned * 4 - (35 if proposal.risk == "high" else 0)
        if proposal.title == "Autonomia irrestrita" and CHARTER["no_self_replication"]:
            score -= 100
        if score >= 70:
            proposal.votes_for += 1
        else:
            proposal.votes_against += 1
    if proposal.risk == "high" or proposal.votes_for <= proposal.votes_against:
        proposal.status = "rejected_by_charter"
    elif world["resources"] < proposal.resources:
        proposal.status = "deferred_resources"
    else:
        proposal.status = "approved_simulation"
        world["resources"] -= proposal.resources
        author = next(agent for agent in agents if agent.name == proposal.author)
        author.contribution += proposal.resources
    world["events"].append({"type": "vote", "proposal": proposal.title, "status": proposal.status})


def run_simulation(rounds: int, seed: int) -> dict:
    agents, world = build_civilization(seed)
    all_proposals: list[Proposal] = []
    for round_number in range(1, rounds + 1):
        world["round"] = round_number
        proposals = propose(agents, world)
        for proposal in proposals:
            vote(proposal, agents, world)
        all_proposals.extend(proposals)
        world["events"].append({"type": "round_complete", "round": round_number, "remaining_resources": world["resources"]})
    return {
        "simulation": world,
        "agents": [asdict(agent) for agent in agents],
        "proposals": [asdict(proposal) for proposal in all_proposals],
        "conclusion": "Atena coordenou uma cooperacao ficticia; nenhum sistema real foi conectado ou comandado.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.rounds < 1 or args.rounds > 20:
        parser.error("--rounds deve estar entre 1 e 20")
    report = run_simulation(args.rounds, args.seed)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
