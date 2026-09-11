#!/usr/bin/env python3
import asyncio
import sys
from pathlib import Path
# Adiciona o diretório raiz ao path (assumindo que o script está em atena_evolution/scripts)
sys.path.insert(0, str(Path(__file__).parent.parent))
from atena_evolution.consciousness.cli import run_once

if __name__ == "__main__":
    # Executa um ciclo, salva no banco SQLite dentro do diretório de trabalho
    db_path = Path("consciousness_history.db")
    result = asyncio.run(run_once(output_json=False, save_db=True, db_path=db_path))
    # O resultado também é salvo em JSON separado para artefato do Actions
    import json
    with open("atena_consciousness_cycle.json", "w") as f:
        json.dump(result.model_dump(mode='json'), f, indent=2)
    sys.exit(0)
