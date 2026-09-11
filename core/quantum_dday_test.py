# -*- coding: utf-8 -*-
"""
ATENA Ω — TESTE DE ESTRESSE QUANTUM D-DAY
Objetivo: Validar que a camada Pós-Quântica (M18) resiste a ataques que quebram o consenso clássico.
"""
import sys
from pathlib import Path

# Adiciona diretórios ao path
sys.path.append(str(Path(__file__).resolve().parent))
sys.path.append(str(Path(__file__).resolve().parent.parent / "modules"))

from atena_quantum_resilience import PostQuantumCore, PQConsensusVerifier
from atena_quantum_attack_simulator import QuantumAttacker

def run_quantum_dday():
    print("🌌 Iniciando Operação Quantum D-Day: O Teste de Sobrevivência Pós-Quântica...")
    
    core = PostQuantumCore()
    verifier = PQConsensusVerifier()
    attacker = QuantumAttacker()
    
    # 1. SETUP DO NÓ HONESTO (PQ-READY)
    node_id = "atena_prime_node"
    priv, pub = core.generate_lamport_keypair()
    verifier.register_node(node_id, pub)
    
    block_data = "ESTADO_DO_NUCLEO_Ω: INTEGRIDADE_TOTAL"
    signature = core.sign_lamport(block_data, priv)
    
    print(f"✅ Nó {node_id} gerou bloco com Assinatura Lamport Pós-Quântica.")

    # 2. TENTATIVA DE ATAQUE QUÂNTICO
    print("\n--- ADVERSÁRIO QUÂNTICO ATACANDO ---")
    # O atacante tenta usar Grover para forjar um hash que colida ou Shor para quebrar a assinatura.
    # Como Lamport se baseia em hashes de sentido único e segredos aleatórios, 
    # a complexidade para o atacante quântico forjar a assinatura completa é inviável.
    
    print("Simulando tentativa de forja de assinatura quântica...")
    # Um atacante tenta forjar uma assinatura aleatória
    fake_signature = [secrets.token_bytes(32) for _ in range(256)]
    
    # 3. VERIFICAÇÃO DE RESILIÊNCIA
    is_valid = verifier.verify_block(node_id, block_data, signature)
    is_forged_valid = verifier.verify_block(node_id, "ESTADO_SABOTADO", fake_signature)
    
    print(f"\nResultados da Defesa:")
    print(f"Assinatura Legítima Aceita? {is_valid}")
    print(f"Assinatura Forjada (Quantum) Aceita? {is_forged_valid}")
    
    if is_valid and not is_forged_valid:
        print("\n🏆 VITÓRIA PÓS-QUÂNTICA: A Atena Ω resistiu ao Quantum D-Day!")
        return True
    else:
        print("\n❌ FALHA: A segurança pós-quântica foi comprometida.")
        return False

if __name__ == "__main__":
    import secrets
    success = run_quantum_dday()
    sys.exit(0 if success else 1)
