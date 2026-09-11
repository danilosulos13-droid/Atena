from __future__ import annotations

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ATENA Ω Vercel Dashboard and Chat API - Enterprise Edition
Version: 10.2.0 - OMNI-PREDATOR Core+
"""
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import time
import traceback
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple

# --- CONFIGURAÇÃO DE LOGGING ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- ACÚMULO DE INTERAÇÕES ---
ATENA_CHAT_DB_PATH = os.getenv("ATENA_CHAT_DB_PATH", "atena_chat_history.db")

def _init_chat_db() -> None:
    try:
        conn = sqlite3.connect(ATENA_CHAT_DB_PATH)
        conn.execute("CREATE TABLE IF NOT EXISTS interactions (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, message TEXT NOT NULL, response TEXT NOT NULL, provider TEXT, model TEXT, latency_ms REAL)")
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Falha ao inicializar banco de interacoes: {e}")

_init_chat_db()

# --- LIFESPAN E APP ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Iniciando ATENA Ω...")
    yield
    logger.info("🛑 Encerrando ATENA Ω...")

from fastapi import FastAPI, HTTPException
app = FastAPI(title="ATENA Ω API", version="10.2.0", lifespan=lifespan)

# --- IMPORTAÇÕES RESTANTES ---
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel
from api.dashboard_html import get_dashboard_html
from api.connectors_api import router as connectors_router
from core.research_orchestrator import ResearchError, run_deep_research

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(connectors_router)


class ChatRequest(BaseModel):
    """Payload compatível com o dashboard e com clientes simples."""

    prompt: str | None = None
    message: str | None = None
    research: bool = False


class ResearchRequest(BaseModel):
    question: str
    topic: str | None = None
    limit_per_query: int = 5
    max_sources: int = 12
    use_llm: bool = True

# --- ENDPOINTS ---
@app.get("/healthz")
async def healthz():
    return {"status": "healthy", "version": "10.2.0"}

# --- NOVOS ENDPOINTS DE CONSCIÊNCIA (ADICIONADOS) ---
@app.get("/api/consciousness/state")
async def get_consciousness_state():
    # Substitua pelo retorno da sua função de consciência
    return {
        "consciousness_level": 0.0,
        "beliefs": {"tenho_consciencia": {"confidence": 0.0}},
        "learning_rate": 0.1
    }

@app.post("/api/consciousness")
async def post_consciousness(depth: dict):
    # Lógica de introspecção
    return {"consciousness_level": 0.0, "belief_updates": []}

@app.post("/api/consciousness/experience")
async def post_experience(data: dict):
    # Lógica de registro de experiência
    return {"new_learning_rate": 0.1}

# --- ENDPOINTS ORIGINAIS ---
@app.get("/api/status")
async def get_status():
    return {"name": "ATENA Ω", "status": "online", "version": "10.2.0"}


def _looks_like_research(prompt: str) -> bool:
    lowered = prompt.casefold()
    markers = (
        "/research",
        "pesquise na internet",
        "pesquisa na internet",
        "pesquisa para mim",
        "busque na internet",
        "procure na internet",
        "faça uma pesquisa",
        "faca uma pesquisa",
    )
    return any(marker in lowered for marker in markers)


async def _run_research(request: ResearchRequest | ChatRequest, question: str) -> dict[str, Any]:
    try:
        if isinstance(request, ResearchRequest):
            return await run_in_threadpool(
                run_deep_research,
                question,
                topic=request.topic,
                limit_per_query=max(1, min(request.limit_per_query, 10)),
                max_sources=max(1, min(request.max_sources, 20)),
                use_llm=request.use_llm,
            )
        return await run_in_threadpool(run_deep_research, question)
    except ResearchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/research")
async def research(request: ResearchRequest):
    """Pesquisa a internet, lê fontes públicas e devolve síntese + relatórios."""
    result = await _run_research(request, request.question.strip())
    return {
        "status": result.get("status"),
        "answer": result.get("answer", ""),
        "sources": result.get("sources", []),
        "source_count": result.get("source_count", 0),
        "conflicts": result.get("conflicts", []),
        "synthesis_provider": result.get("synthesis_provider"),
        "json_path": result.get("json_path"),
        "markdown_path": result.get("markdown_path"),
        "researched_at": result.get("researched_at"),
    }


@app.post("/api/chat")
async def chat(request: ChatRequest):
    prompt = (request.prompt or request.message or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt vazio")

    if request.research or _looks_like_research(prompt):
        result = await _run_research(request, prompt.removeprefix("/research").strip())
        answer = str(result.get("answer", ""))
        source = "deep-research"
        payload = {
            "answer": answer,
            "source": source,
            "sources": result.get("sources", []),
            "json_path": result.get("json_path"),
            "markdown_path": result.get("markdown_path"),
        }
    else:
        try:
            from core.atena_llm_router import AtenaLLMRouter

            answer = str(AtenaLLMRouter().generate(prompt, context="API chat da ATENA"))
            payload = {"answer": answer, "source": "atena-router"}
        except Exception as exc:
            logger.warning("chat sem provider configurado: %s", exc)
            payload = {
                "answer": "Não há um provedor de linguagem configurado. Para pesquisa, use /research <tema> ou POST /api/research.",
                "source": "local-fallback",
            }

    try:
        conn = sqlite3.connect(ATENA_CHAT_DB_PATH)
        conn.execute(
            "INSERT INTO interactions(timestamp, message, response, provider, model, latency_ms) VALUES (?, ?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), prompt, payload["answer"], payload.get("source"), None, None),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning("falha ao registrar interação: %s", exc)
    return payload

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return get_dashboard_html()

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
