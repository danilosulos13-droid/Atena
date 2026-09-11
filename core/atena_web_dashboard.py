#!/usr/bin/env python3
"""
core/atena_web_dashboard.py

Servidor FastAPI avançado que:
- Serve página HTML com gráficos Plotly (Loss e Índice de Sharpe em tempo real)
- Lista modelos do Memory Vault
- Exibe lições aprendidas da Memória Semântica

Inclui:
- Simulação sofisticada de evolução com algoritmo evolutivo
- Endpoint WebSocket para atualização em tempo real
- Salvamento periódico em JSON/CSV
- Testes inline via pytest
- Relatório detalhado ao final da execução (modo script)

Requisitos:
fastapi, uvicorn, plotly, pandas, numpy, websockets, pytest

Execute com:
uvicorn core.atena_web_dashboard:app --reload

"""

import asyncio
import json
import csv
import logging
import os
import random
from datetime import datetime
from typing import List, Dict, Any

import numpy as np
import pandas as pd
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import plotly.graph_objs as go
from plotly.subplots import make_subplots

# Configuração de logging para relatório final
logging.basicConfig(
    level=logging.DEBUG,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("atena_web_dashboard.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("AtenaWebDashboard")

app = FastAPI(title="Atena Web Dashboard")

# Serve assets estáticos (ex: CSS, JS se necessário)
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

# Diretórios para salvar dados
DATA_DIR = "./data"
os.makedirs(DATA_DIR, exist_ok=True)

# Memória Semântica (exemplo fictício)
MEMORIA_SEMANTICA = [
    "Ajustar taxa de mutação para evitar overfitting.",
    "Incluir regularização L2 melhorou estabilidade.",
    "Sharpe ratio melhorou com seleção de features PCA.",
    "Early stopping preveniu perda de generalização.",
    "Batch normalization acelerou convergência.",
]

# Memory Vault com modelos simulados
MEMORY_VAULT = [
    {"id": "model_001", "name": "Evolutivo Alpha", "params": {"pop": 50, "mut": 0.05}},
    {"id": "model_002", "name": "Monte Carlo Beta", "params": {"simulations": 1000}},
    {"id": "model_003", "name": "Otimização Gamma", "params": {"method": "BFGS"}},
]

# Estado compartilhado para evolução simulada (thread-safe com asyncio.Lock)
class EvolutionState:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.timestamps = []  # datetime ISO strings
        self.loss_values = []  # float
        self.sharpe_values = []  # float
        self.iteration = 0

evolution_state = EvolutionState()

# Algoritmo evolutivo sofisticado simplificado para simulação
def simulate_evolution_step(prev_loss: float, prev_sharpe: float) -> (float, float):
    """
    Simula um passo da evolução usando algoritmo evolutivo simplificado.

    - Loss tende a decrescer com ruído gaussiano.
    - Sharpe tende a aumentar com ruído gaussiano.
    - Introduz salto adaptativo para simular evolução realista.

    Args:
        prev_loss (float): valor de loss anterior
        prev_sharpe (float): valor de sharpe anterior

    Returns:
        (float, float): nova loss e sharpe
    """
    # Decaimento exponencial com ruído
    loss_decay = prev_loss * (0.95 + np.random.normal(0, 0.01))
    loss_noise = np.random.normal(0, 0.005)
    new_loss = max(loss_decay + loss_noise, 0.01)  # loss sempre positivo

    # Sharpe melhora com ruído e pequenos saltos
    sharpe_trend = prev_sharpe + np.random.normal(0.01, 0.02)
    if random.random() < 0.1:
        # salto evolutivo para cima
        sharpe_trend += random.uniform(0.05, 0.15)
    new_sharpe = max(sharpe_trend, 0.0)  # Sharpe não negativo

    return new_loss, new_sharpe


# Salva dados evolutivos em JSON e CSV
def save_evolution_data(timestamps: List[str], loss_values: List[float], sharpe_values: List[float]):
    """
    Salva os dados de evolução em arquivos JSON e CSV.

    Args:
        timestamps (List[str]): lista de timestamps ISO
        loss_values (List[float]): lista de valores de loss
        sharpe_values (List[float]): lista de valores de sharpe
    """
    data = [{"timestamp": ts, "loss": loss, "sharpe": sharpe}
            for ts, loss, sharpe in zip(timestamps, loss_values, sharpe_values)]
    json_path = os.path.join(DATA_DIR, "evolution_data.json")
    csv_path = os.path.join(DATA_DIR, "evolution_data.csv")

    # Salva JSON
    try:
        with open(json_path, "w") as jf:
            json.dump(data, jf, indent=2)
        logger.debug(f"Dados de evolução salvos em JSON: {json_path}")
    except Exception as e:
        logger.error(f"Erro ao salvar JSON: {e}")

    # Salva CSV
    try:
        with open(csv_path, "w", newline='') as cf:
            writer = csv.DictWriter(cf, fieldnames=["timestamp", "loss", "sharpe"])
            writer.writeheader()
            for row in data:
                writer.writerow(row)
        logger.debug(f"Dados de evolução salvos em CSV: {csv_path}")
    except Exception as e:
        logger.error(f"Erro ao salvar CSV: {e}")

# Gera HTML com gráficos Plotly embutidos
def generate_plotly_html(timestamps: List[str], loss_values: List[float], sharpe_values: List[float]) -> str:
    """
    Gera HTML contendo gráficos Plotly da evolução Loss e Sharpe.

    Args:
        timestamps (List[str]): timestamps ISO
        loss_values (List[float]): valores de loss
        sharpe_values (List[float]): valores de sharpe

    Returns:
        str: HTML com gráficos embutidos
    """
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        subplot_titles=("Evolução da Loss", "Evolução do Índice de Sharpe"))

    fig.add_trace(go.Scatter(x=timestamps, y=loss_values, mode='lines+markers', name='Loss'),
                  row=1, col=1)
    fig.add_trace(go.Scatter(x=timestamps, y=sharpe_values, mode='lines+markers', name='Sharpe'),
                  row=2, col=1)

    fig.update_layout(height=600, margin=dict(t=50, b=50))

    html_str = fig.to_html(full_html=False, include_plotlyjs='cdn')
    return html_str

# HTML Template inline para simplicidade (alternativamente usar templates Jinja2)
HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<title>Atena Web Dashboard - Evolução em Tempo Real</title>
<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
<style>
body { font-family: Arial, sans-serif; margin: 20px; background: #f7f9fc; }
h1 { color: #2c3e50; }
#plots { width: 90vw; margin: auto; }
#models, #lessons { margin-top: 40px; }
section { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
ul { list-style-type: none; padding-left: 0; }
li { padding: 5px 0; }
</style>
</head>
<body>
<h1>Atena Web Dashboard - Evolução em Tempo Real</h1>
<div id="plots">
    <div id="plotly-div"></div>
</div>

<section id="models">
<h2>Modelos do Memory Vault</h2>
<ul id="model-list"></ul>
</section>

<section id="lessons">
<h2>Lições Aprendidas da Memória Semântica</h2>
<ul id="lesson-list"></ul>
</section>

<script>
const ws = new WebSocket(`ws://${location.host}/ws/evolution`);
const timestamps = [];
const loss_values = [];
const sharpe_values = [];

const plotDiv = document.getElementById('plotly-div');

ws.onmessage = event => {
    const data = JSON.parse(event.data);
    if(data.type === 'evolution_update'){
        timestamps.push(data.timestamp);
        loss_values.push(data.loss);
        sharpe_values.push(data.sharpe);
        updatePlot();
    } else if(data.type === 'memory_vault'){
        updateModels(data.models);
    } else if(data.type === 'semantic_memory'){
        updateLessons(data.lessons);
    }
};

ws.onopen = () => {
    console.log("WebSocket conectado");
};

ws.onclose = () => {
    console.log("WebSocket desconectado");
};

function updatePlot(){
    const trace1 = {x: timestamps, y: loss_values, type: 'scatter', mode: 'lines+markers', name: 'Loss'};
    const trace2 = {x: timestamps, y: sharpe_values, type: 'scatter', mode: 'lines+markers', name: 'Sharpe', yaxis: 'y2'};

    const layout = {
        title: 'Evolução da Loss e Índice de Sharpe',
        yaxis: {title: 'Loss', side: 'left'},
        yaxis2: {title: 'Sharpe', overlaying: 'y', side: 'right'},
        margin: {t: 50}
    };

    Plotly.newPlot(plotDiv, [trace1, trace2], layout, {responsive: true});
}

function updateModels(models){
    const ul = document.getElementById('model-list');
    ul.innerHTML = '';
    models.forEach(m => {
        const li = document.createElement('li');
        li.textContent = `${m.id} - ${m.name} | Params: ${JSON.stringify(m.params)}`;
        ul.appendChild(li);
    });
}

function updateLessons(lessons){
    const ul = document.getElementById('lesson-list');
    ul.innerHTML = '';
    lessons.forEach(lesson => {
        const li = document.createElement('li');
        li.textContent = lesson;
        ul.appendChild(li);
    });
}
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def root():
    """
    Retorna a página HTML principal com dashboard.
    """
    return HTML_PAGE


@app.websocket("/ws/evolution")
async def websocket_evolution(websocket: WebSocket):
    """
    WebSocket para enviar atualizações da evolução em tempo real,
    além de dados do Memory Vault e Memória Semântica.
    """
    await websocket.accept()
    logger.info("Cliente WebSocket conectado para evolução")

    # Enviar dados fixos de Memory Vault e Memória Semântica inicialmente
    try:
        await websocket.send_json({"type": "memory_vault", "models": MEMORY_VAULT})
        await websocket.send_json({"type": "semantic_memory", "lessons": MEMORIA_SEMANTICA})
    except Exception as e:
        logger.error(f"Erro ao enviar dados iniciais via WebSocket: {e}")

    try:
        while True:
            async with evolution_state.lock:
                if evolution_state.timestamps:
                    idx = evolution_state.iteration
                    if idx < len(evolution_state.timestamps):
                        data = {
                            "type": "evolution_update",
                            "timestamp": evolution_state.timestamps[idx],
                            "loss": evolution_state.loss_values[idx],
                            "sharpe": evolution_state.sharpe_values[idx]
                        }
                        evolution_state.iteration += 1
                    else:
                        # Aguarda novos dados
                        data = None
                else:
                    data = None

            if data:
                await websocket.send_json(data)

            await asyncio.sleep(1)  # frequência de atualização 1s

    except WebSocketDisconnect:
        logger.info("Cliente WebSocket desconectado")
    except Exception as e:
        logger.error(f"Erro no WebSocket: {e}")


async def evolve_simulation_task():
    """
    Tarefa assíncrona que simula evolução do Loss e Sharpe em background.
    Atualiza evolution_state periodicamente.
    """
    logger.info("Tarefa de simulação de evolução iniciada")
    prev_loss = 1.0
    prev_sharpe = 0.0

    while True:
        new_loss, new_sharpe = simulate_evolution_step(prev_loss, prev_sharpe)
        now_iso = datetime.utcnow().isoformat()

        async with evolution_state.lock:
            evolution_state.timestamps.append(now_iso)
            evolution_state.loss_values.append(new_loss)
            evolution_state.sharpe_values.append(new_sharpe)

        # Salva a cada 10 atualizações
        if len(evolution_state.timestamps) % 10 == 0:
            async with evolution_state.lock:
                save_evolution_data(evolution_state.timestamps, evolution_state.loss_values, evolution_state.sharpe_values)

        prev_loss = new_loss
        prev_sharpe = new_sharpe

        await asyncio.sleep(2)  # passo da simulação a cada 2 segundos


@app.on_event("startup")
async def startup_event():
    """
    Evento de startup para iniciar a tarefa de simulação.
    """
    logger.info("Iniciando servidor Atena Web Dashboard...")
    asyncio.create_task(evolve_simulation_task())


# --- TESTES INLINE ---

def test_simulate_evolution_step():
    """
    Testa a função simulate_evolution_step garantindo que:
    - Loss decresce e é positiva
    - Sharpe é não negativo e pode aumentar
    """
    loss, sharpe = 1.0, 0.0
    for _ in range(50):
        loss_new, sharpe_new = simulate_evolution_step(loss, sharpe)
        assert loss_new > 0, "Loss deve ser positiva"
        assert sharpe_new >= 0, "Sharpe deve ser não negativa"
        assert loss_new <= loss * 1.1, "Loss não deve aumentar muito"
        loss, sharpe = loss_new, sharpe_new

def test_save_and_load_evolution_data(tmp_path):
    """
    Testa se os dados são salvos corretamente em JSON e CSV.
    """
    timestamps = [datetime.utcnow().isoformat() for _ in range(5)]
    loss = [0.5, 0.4, 0.35, 0.3, 0.25]
    sharpe = [0.1, 0.12, 0.15, 0.2, 0.3]

    json_path = tmp_path / "evolution_data.json"
    csv_path = tmp_path / "evolution_data.csv"
    # Redireciona DATA_DIR temporariamente
    global DATA_DIR
    old_data_dir = DATA_DIR
    DATA_DIR = str(tmp_path)

    save_evolution_data(timestamps, loss, sharpe)

    # Verifica JSON
    with open(json_path) as jf:
        data = json.load(jf)
        assert len(data) == 5
        assert data[0]["loss"] == 0.5

    # Verifica CSV
    with open(csv_path) as cf:
        reader = csv.DictReader(cf)
        rows = list(reader)
        assert len(rows) == 5
        assert float(rows[0]["loss"]) == 0.5

    # Restaura DATA_DIR
    DATA_DIR = old_data_dir

def test_generate_plotly_html():
    timestamps = [datetime.utcnow().isoformat() for _ in range(3)]
    loss = [0.5, 0.4, 0.3]
    sharpe = [0.2, 0.25, 0.3]

    html = generate_plotly_html(timestamps, loss, sharpe)
    assert "plotly" in html.lower()
    assert timestamps[0] in html

def test_websocket_connection():
    """
    Testa se a rota WebSocket aceita conexões.
    """
    import websockets
    import threading

    async def ws_client():
        uri = "ws://localhost:8000/ws/evolution"
        try:
            async with websockets.connect(uri) as websocket:
                # Recebe dados iniciais
                memory_vault_msg = await websocket.recv()
                semantic_memory_msg = await websocket.recv()
                # Recebe updates de evolução (pelo menos 1)
                evolution_msg = await websocket.recv()
                assert "evolution_update" in evolution_msg
        except Exception as e:
            assert False, f"Falha na conexão WebSocket: {e}"

    def start_uvicorn():
        import uvicorn
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="error")

    # Roda servidor e cliente em threads para teste rápido
    server_thread = threading.Thread(target=start_uvicorn, daemon=True)
    server_thread.start()
    import time
    time.sleep(2)  # aguarda servidor iniciar

    asyncio.run(ws_client())

# Executa testes se rodar diretamente
if __name__ == "__main__":
    import sys
    import pytest

    logger.info("Executando testes inline para Atena Web Dashboard...")
    results = pytest.main([__file__, "-v", "-s"])
    if results == 0:
        logger.info("Todos os testes passaram com sucesso!")
    else:
        logger.error("Alguns testes falharam!")

    # Imprime relatório detalhado de evolução simulada
    if evolution_state.timestamps:
        logger.info(f"Total de iterações simuladas: {len(evolution_state.timestamps)}")
        logger.info(f"Últimos valores - Loss: {evolution_state.loss_values[-1]:.4f}, Sharpe: {evolution_state.sharpe_values[-1]:.4f}")

