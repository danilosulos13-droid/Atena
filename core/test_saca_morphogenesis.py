# -*- coding: utf-8 -*-
import sys
from pathlib import Path

# Adiciona o diretório core ao path
sys.path.append(str(Path(__file__).resolve().parent))

from atena_saca_core import SACACore

def test_saca_morphogenesis():
    print("🚀 Iniciando Teste de Metamorfose Cognitiva (SACA)...")
    saca = SACACore()
    
    # Teste 1: Missão de Segurança
    print("\n--- Teste 1: Missão Crítica de Segurança ---")
    saca.morph("security_critical")
    topology = saca.get_active_topology()
    print(f"Topologia Ativa: {topology}")
    assert "SelfPreservation" in topology
    assert "NeuroSymbolic" in topology
    assert topology[0] == "SelfPreservation"
    
    # Teste 2: Missão de Computação
    print("\n--- Teste 2: Missão de Computação Intensiva ---")
    saca.morph("compute_intensive")
    topology = saca.get_active_topology()
    print(f"Topologia Ativa: {topology}")
    assert "GPUSharing" in topology
    assert "DeepLearning" in topology
    assert topology[0] == "GPUSharing"
    
    # Teste 3: Missão de Inovação
    print("\n--- Teste 3: Missão de Descoberta e Inovação ---")
    saca.morph("innovation_discovery")
    topology = saca.get_active_topology()
    print(f"Topologia Ativa: {topology}")
    assert "BrowserAgent" in topology
    assert "CreativeSynthesis" in topology
    
    print("\n✅ ATENA Ω: Arquitetura SACA Validada com Sucesso!")

if __name__ == "__main__":
    try:
        test_saca_morphogenesis()
    except Exception as e:
        print(f"❌ Erro na validação SACA: {e}")
        sys.exit(1)
