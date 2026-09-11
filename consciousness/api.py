from fastapi import FastAPI, HTTPException, Query
from .core import HyperConsciousnessEngine
from .storage import ConsciousnessStore
from .models import ConsciousnessCycleResult
from pathlib import Path

def create_app(db_path: Path) -> FastAPI:
    app = FastAPI(title="ATENA Consciousness API", version="4.0")
    store = ConsciousnessStore(db_path)

    @app.post("/cycle", response_model=ConsciousnessCycleResult)
    async def run_cycle():
        engine = HyperConsciousnessEngine()
        result = await engine.run_full_cycle()
        store.save(result)
        return result

    @app.get("/history")
    async def get_history(limit: int = Query(10, le=100)):
        return store.get_last_n(limit)

    return app
