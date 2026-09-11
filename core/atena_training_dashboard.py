import time
import random
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.console import Console
from rich.layout import Layout
from rich.progress import Progress, BarColumn, TextColumn

console = Console()

def create_dashboard(epoch, loss, lr, history):
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main")
    )
    layout["main"].split_row(
        Layout(name="metrics"),
        Layout(name="history")
    )

    # Header
    layout["header"].update(Panel("🔱 ATENA Ω - Monitor de Treinamento Neural", style="bold blue"))

    # Metrics Table
    table = Table(title="Métricas Atuais")
    table.add_column("Métrica", style="cyan")
    table.add_column("Valor", style="magenta")
    table.add_row("Época", str(epoch))
    table.add_row("Loss", f"{loss:.6f}")
    table.add_row("Learning Rate", f"{lr:.4f}")
    layout["metrics"].update(Panel(table))

    # Loss History Simulation (Visual)
    history_str = "\n".join([f"Ep {h['ep']}: Loss {h['loss']:.4f}" for h in history[-10:]])
    layout["history"].update(Panel(history_str, title="Histórico Recente"))

    return layout

def run_simulated_dashboard(steps=20):
    history = []
    loss = 0.5
    with Live(create_dashboard(0, loss, 0.01, history), refresh_per_second=4) as live:
        for i in range(1, steps + 1):
            time.sleep(0.2)
            loss *= 0.95
            history.append({"ep": i, "loss": loss})
            live.update(create_dashboard(i, loss, 0.01, history))

if __name__ == "__main__":
    import sys
    steps = 20
    if "--sim-steps" in sys.argv:
        idx = sys.argv.index("--sim-steps")
        steps = int(sys.argv[idx+1])
    run_simulated_dashboard(steps)
