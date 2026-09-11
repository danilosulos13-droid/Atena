from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api.main import app
from core import research_orchestrator as orchestrator
from core.web_research import WebEvidence


def test_run_deep_research_saves_auditable_reports(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        orchestrator,
        "_collect_evidence",
        lambda plan, limit: [
            WebEvidence(
                "Fonte oficial",
                "https://example.gov.br/relatorio",
                "Dados públicos e verificáveis sobre o tema pesquisado.",
            ),
            WebEvidence(
                "Análise independente",
                "https://example.org/analise",
                "Uma análise contextual com metodologia descrita e resultados recentes.",
            ),
        ],
    )
    monkeypatch.setattr(orchestrator, "_enrich_sources", lambda sources: sources)

    result = orchestrator.run_deep_research(
        "qual é o estado atual do projeto",
        use_llm=False,
        output_dir=tmp_path,
    )

    assert result["status"] == "ok"
    assert result["source_count"] == 2
    assert "https://example.gov.br/relatorio" in result["markdown"]
    assert Path(result["json_path"]).exists()
    assert Path(result["markdown_path"]).exists()


def test_api_research_returns_answer_and_sources(monkeypatch, tmp_path: Path):
    expected = {
        "status": "ok",
        "answer": "Síntese [S1].",
        "sources": [{"title": "Fonte", "url": "https://example.org", "snippet": "Trecho"}],
        "source_count": 1,
        "conflicts": [],
        "synthesis_provider": None,
        "json_path": str(tmp_path / "report.json"),
        "markdown_path": str(tmp_path / "report.md"),
        "researched_at": "2026-01-01T00:00:00+00:00",
    }
    monkeypatch.setattr("api.main.run_deep_research", lambda *args, **kwargs: expected)

    with TestClient(app) as client:
        response = client.post("/api/research", json={"question": "tema", "use_llm": False})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Síntese [S1]."
    assert body["source_count"] == 1
    assert body["sources"][0]["url"] == "https://example.org"
