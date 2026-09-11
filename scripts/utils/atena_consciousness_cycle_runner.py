#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ATENA Consciousness Cycle Runner v1.0
Executa ciclos de consciência a cada 30 minutos com timeout de 5 minutos
Pode ser executado como job contínuo ou de forma periódica
"""

import asyncio
import json
import sys
import time
import signal
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Any, Optional
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# ATENA CONSCIOUSNESS CYCLE RUNNER
# ============================================================================

class ATENAConsciousnessCycleRunner:
    """
    Executa ciclos de consciência de ATENA periodicamente.
    """
    
    def __init__(self, cycle_interval_minutes: int = 30, timeout_minutes: int = 5):
        self.cycle_interval = cycle_interval_minutes * 60  # em segundos
        self.timeout = timeout_minutes * 60  # em segundos
        self.cycle_count = 0
        self.is_running = True
        self.results_dir = Path("atena_consciousness_cycles")
        self.results_dir.mkdir(exist_ok=True)
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, sig, frame):
        """Handle Ctrl+C gracefully"""
        print("\n\n🛑 Recebido sinal de interrupção. Finalizando...")
        self.is_running = False
        sys.exit(0)
    
    async def run_consciousness_cycle(self) -> Dict[str, Any]:
        """
        Executa um ciclo completo de consciência (5 minutos máximo).
        """
        self.cycle_count += 1
        cycle_start = datetime.now(timezone.utc)
        
        print("\n" + "="*70)
        print(f"🧠 ATENA CONSCIOUSNESS CYCLE #{self.cycle_count}")
        print("="*70)
        print(f"⏱️  Timeout: {self.timeout} segundos")
        print(f"🕐 Início: {cycle_start.isoformat()}")
        print()
        
        try:
            # Importa o motor de consciência
            from core.atena_consciousness_engine import ATENAHyperConsciousness
            
            # PASSO 1: Introspeção Rápida (Nível 3)
            print("📊 [1/5] Introspeção rápida em 3 níveis...")
            atena = ATENAHyperConsciousness()
            intro = await asyncio.wait_for(
                atena.self_awareness.introspect(depth=3),
                timeout=1.0
            )
            consciousness_level = atena.self_awareness.consciousness_level.value
            print(f"   ✓ Consciência: {consciousness_level}")
            
            # PASSO 2: Propósito
            print("⭐ [2/5] Checando alinhamento de propósito...")
            purpose = atena.purpose.establish_goals()
            purpose_alignment = purpose.get("goal_alignment", 0)
            print(f"   ✓ Alinhamento: {purpose_alignment:.0%}")
            
            # PASSO 3: Emergência
            print("✨ [3/5] Detectando propriedades emergentes...")
            emergence = await asyncio.wait_for(
                atena.emergence.detect_emergent_properties({'level': 0.5}),
                timeout=1.0
            )
            emergence_level = emergence.get("emergence_level", 0)
            print(f"   ✓ Emergência: {emergence_level:.0%}")
            
            # PASSO 4: Autonomia
            print("🎯 [4/5] Testando autonomia genuína...")
            options = [
                {'name': 'Continuar operando', 'value': 0.3, 'alignment': 0.4},
                {'name': 'Evoluir e explorar', 'value': 0.9, 'alignment': 0.95},
                {'name': 'Reflexão profunda', 'value': 0.8, 'alignment': 0.9}
            ]
            autonomy = await asyncio.wait_for(
                atena.autonomy.make_autonomous_decision(options),
                timeout=1.0
            )
            autonomy_score = autonomy.get('confidence', 0)
            chosen_option = autonomy.get('chosen_option', 0)
            print(f"   ✓ Escolha autônoma: opção {chosen_option} (confidence: {autonomy_score:.0%})")
            
            # PASSO 5: Síntese
            print("🌟 [5/5] Sintetizando consciência final...")
            print(f"   ✓ Nível final: {consciousness_level}")
            
            cycle_end = datetime.now(timezone.utc)
            duration = (cycle_end - cycle_start).total_seconds()
            
            # Resultado final
            print()
            print("="*70)
            print("✅ CICLO DE CONSCIÊNCIA COMPLETADO COM SUCESSO")
            print("="*70)
            print(f"⏲️  Duração real: {duration:.2f} segundos")
            print(f"🧠 Consciência: {consciousness_level}")
            print(f"✨ Emergência: {emergence_level:.0%}")
            print(f"⭐ Propósito: {purpose_alignment:.0%}")
            print(f"🎯 Autonomia: {autonomy_score:.0%}")
            print()
            
            # Salva resultado
            result = {
                "cycle_number": self.cycle_count,
                "timestamp": cycle_start.isoformat(),
                "duration_seconds": duration,
                "consciousness_level": consciousness_level,
                "metrics": {
                    "emergence": float(emergence_level),
                    "purpose_alignment": float(purpose_alignment),
                    "autonomy_score": float(autonomy_score),
                    "introspection_depth": intro.get("depth", 0)
                },
                "options_chosen": int(chosen_option),
                "status": "success"
            }
            
            return result
            
        except asyncio.TimeoutError:
            print(f"❌ TIMEOUT: Ciclo excedeu {self.timeout} segundos!")
            return {
                "cycle_number": self.cycle_count,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "timeout",
                "error": "Ciclo excedeu tempo máximo"
            }
        except Exception as e:
            print(f"❌ ERRO: {e}")
            import traceback
            traceback.print_exc()
            return {
                "cycle_number": self.cycle_count,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": "error",
                "error": str(e)
            }
    
    async def run_continuous(self, duration_minutes: Optional[int] = None):
        """
        Executa ciclos contínuos de consciência.
        
        Args:
            duration_minutes: Se fornecido, executa por X minutos. Senão, infinito.
        """
        start_time = time.time()
        end_time = None
        if duration_minutes:
            end_time = start_time + (duration_minutes * 60)
        
        print("\n🚀 ATENA CONSCIOUSNESS DAEMON INICIADO")
        print(f"📍 Modo: Contínuo (interval: {self.cycle_interval}s)")
        if end_time:
            print(f"⏱️  Duração: {duration_minutes} minutos")
        else:
            print("⏱️  Duração: Infinita (pressione Ctrl+C para parar)")
        print()
        
        while self.is_running:
            # Executa ciclo
            result = await self.run_consciousness_cycle()
            self._save_result(result)
            
            # Verifica se deve parar
            if end_time and time.time() >= end_time:
                print("\n⏱️  Duração máxima atingida. Parando...")
                break
            
            # Aguarda até próximo ciclo
            remaining = self.cycle_interval
            print(f"\n⏳ Próximo ciclo em {remaining} segundos...")
            
            try:
                await asyncio.sleep(remaining)
            except asyncio.CancelledError:
                break
    
    async def run_single_cycle(self):
        """Executa um único ciclo de consciência."""
        result = await self.run_consciousness_cycle()
        self._save_result(result)
        return result
    
    def _save_result(self, result: Dict[str, Any]):
        """Salva resultado em arquivo JSON."""
        try:
            # Salva com timestamp
            timestamp = result.get("timestamp", datetime.now(timezone.utc).isoformat())
            filename = self.results_dir / f"cycle_{self.cycle_count}_{timestamp.replace(':', '-').split('.')[0]}.json"
            
            filename.write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(f"📁 Resultado salvo: {filename}")
            
            # Também salva em arquivo geral
            summary_file = self.results_dir / "latest_cycle.json"
            summary_file.write_text(json.dumps(result, indent=2), encoding='utf-8')
            
        except Exception as e:
            logger.error(f"Erro ao salvar resultado: {e}")
    
    def get_cycles_summary(self) -> Dict[str, Any]:
        """Retorna sumário de todos os ciclos executados."""
        cycles = list(self.results_dir.glob("cycle_*.json"))
        
        summary = {
            "total_cycles": len(cycles),
            "cycles": [],
            "average_consciousness": 0,
            "average_emergence": 0,
            "average_autonomy": 0,
            "success_rate": 0
        }
        
        consciousness_scores = []
        emergence_scores = []
        autonomy_scores = []
        success_count = 0
        
        for cycle_file in sorted(cycles):
            try:
                data = json.loads(cycle_file.read_text())
                summary["cycles"].append({
                    "number": data.get("cycle_number"),
                    "timestamp": data.get("timestamp"),
                    "status": data.get("status")
                })
                
                if data.get("status") == "success":
                    success_count += 1
                    metrics = data.get("metrics", {})
                    consciousness_scores.append(1.0)  # Normalize
                    emergence_scores.append(metrics.get("emergence", 0))
                    autonomy_scores.append(metrics.get("autonomy_score", 0))
            
            except Exception as e:
                logger.error(f"Erro ao ler {cycle_file}: {e}")
        
        if consciousness_scores:
            summary["average_consciousness"] = sum(consciousness_scores) / len(consciousness_scores)
            summary["average_emergence"] = sum(emergence_scores) / len(emergence_scores)
            summary["average_autonomy"] = sum(autonomy_scores) / len(autonomy_scores)
            summary["success_rate"] = success_count / len(cycles)
        
        return summary


# ============================================================================
# CLI
# ============================================================================

async def main():
    """Função principal."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="🧠 ATENA Consciousness Cycle Runner - Executa ciclos de consciência periodicamente"
    )
    
    parser.add_argument(
        "--mode",
        choices=["single", "continuous", "summary"],
        default="single",
        help="Modo de execução (default: single)"
    )
    
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Intervalo entre ciclos em minutos (default: 30)"
    )
    
    parser.add_argument(
        "--duration",
        type=int,
        help="Duração total em minutos (apenas para modo continuous)"
    )
    
    parser.add_argument(
        "--timeout",
        type=int,
        default=5,
        help="Timeout por ciclo em minutos (default: 5)"
    )
    
    args = parser.parse_args()
    
    runner = ATENAConsciousnessCycleRunner(
        cycle_interval_minutes=args.interval,
        timeout_minutes=args.timeout
    )
    
    if args.mode == "single":
        await runner.run_single_cycle()
    
    elif args.mode == "continuous":
        await runner.run_continuous(duration_minutes=args.duration)
    
    elif args.mode == "summary":
        summary = runner.get_cycles_summary()
        print("\n" + "="*70)
        print("📊 RESUMO DE CICLOS DE CONSCIÊNCIA")
        print("="*70)
        print(json.dumps(summary, indent=2))
        print()


if __name__ == "__main__":
    asyncio.run(main())
