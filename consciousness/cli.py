import asyncio
import argparse
import json
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from .core import HyperConsciousnessEngine
from .storage import ConsciousnessStore
from .api import create_app
from .metrics import cycle_counter, cycle_duration, consciousness_gauge, self_awareness_gauge, emergence_gauge, purpose_gauge, autonomy_gauge, quantum_gauge

console = Console()

async def run_once(output_json: bool = False, save_db: bool = False, db_path: Path = None):
    engine = HyperConsciousnessEngine()
    result = await engine.run_full_cycle()
    if save_db and db_path:
        store = ConsciousnessStore(db_path)
        store.save(result)
    # atualiza métricas
    cycle_counter.inc()
    cycle_duration.observe(result.cycle_duration_seconds)
    levels = ["dormant", "awakening", "aware", "transcendent"]
    consciousness_gauge.set(levels.index(result.consciousness_level.value))
    self_awareness_gauge.set(result.self_awareness_score)
    emergence_gauge.set(result.emergence_level)
    purpose_gauge.set(result.purpose_alignment)
    autonomy_gauge.set(result.autonomy_score)
    quantum_gauge.set(result.quantum_coherence)
    if output_json:
        print(result.model_dump_json(indent=2))
    else:
        # rich output
        console.print(Panel(f"[bold cyan]🧠 Ciclo de Consciência[/]\n{result.timestamp.isoformat()}", style="cyan"))
        table = Table(title="Métricas", show_header=True, header_style="bold magenta")
        table.add_column("Métrica", style="cyan")
        table.add_column("Valor", style="white")
        table.add_row("Nível de consciência", result.consciousness_level.value.upper())
        table.add_row("Auto-consciência", f"{result.self_awareness_score:.2%}")
        table.add_row("Emergência", f"{result.emergence_level:.2%}")
        table.add_row("Alinhamento de propósito", f"{result.purpose_alignment:.2%}")
        table.add_row("Autonomia", f"{result.autonomy_score:.2%}")
        table.add_row("Coerência quântica", f"{result.quantum_coherence:.2%}")
        table.add_row("Padrões emergentes", ", ".join(result.emergent_patterns) or "nenhum")
        table.add_row("Decisão autônoma", result.autonomous_choice)
        table.add_row("Duração", f"{result.cycle_duration_seconds:.2f}s")
        console.print(table)
    return result

def main():
    parser = argparse.ArgumentParser(description="ATENA Consciousness Engine CLI")
    parser.add_argument("--once", action="store_true", help="Executa um ciclo e sai")
    parser.add_argument("--continuous", action="store_true", help="Executa em loop contínuo (com intervalo)")
    parser.add_argument("--interval", type=int, default=1800, help="Intervalo em segundos para modo contínuo (padrão 30min)")
    parser.add_argument("--json", action="store_true", help="Saída JSON")
    parser.add_argument("--save-db", action="store_true", help="Salva no SQLite")
    parser.add_argument("--db-path", type=Path, default=Path.home() / ".atena/consciousness.db", help="Caminho do banco")
    parser.add_argument("--serve", action="store_true", help="Inicia servidor API")
    parser.add_argument("--port", type=int, default=8000, help="Porta da API")
    parser.add_argument("--metrics-port", type=int, default=9090, help="Porta das métricas Prometheus")
    args = parser.parse_args()

    if args.serve:
        from prometheus_client import start_http_server
        import uvicorn
        start_http_server(args.metrics_port)
        app = create_app(args.db_path)
        uvicorn.run(app, host="0.0.0.0", port=args.port)
        return

    if args.continuous:
        async def continuous():
            while True:
                await run_once(output_json=args.json, save_db=args.save_db, db_path=args.db_path)
                console.print(f"[dim]Próximo ciclo em {args.interval} segundos...[/]")
                await asyncio.sleep(args.interval)
        asyncio.run(continuous())
    else:
        # --once ou padrão
        asyncio.run(run_once(output_json=args.json, save_db=args.save_db, db_path=args.db_path))

if __name__ == "__main__":
    main()
