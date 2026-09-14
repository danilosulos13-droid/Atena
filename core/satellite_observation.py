"""Pesquisa somente leitura de catálogos de observação da Terra.

A capacidade retorna metadados e links de ativos; não baixa imagens, não opera
satélites e não executa comandos remotos. O chamador pode usar os resultados
como evidência para uma análise posterior.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "satellite_sources.json"


def load_sources(path: str | Path = DEFAULT_CONFIG) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [item for item in data.get("sources", []) if item.get("enabled") and item.get("read_only")]


def _get_json(url: str, *, timeout: float = 15.0) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "Atena-EarthObservation/1.0"})
    with urlopen(request, timeout=max(1.0, min(timeout, 60.0))) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("resposta JSON de catálogo inválida")
    return payload


def build_stac_search(
    *,
    bbox: tuple[float, float, float, float],
    datetime_range: str,
    collections: list[str] | None = None,
    limit: int = 10,
    endpoint: str = "https://earth-search.aws.element84.com/v1/search",
) -> tuple[str, dict[str, Any]]:
    """Constrói uma requisição STAC determinística sem executá-la."""
    if len(bbox) != 4 or not (-180 <= bbox[0] <= bbox[2] <= 180 and -90 <= bbox[1] <= bbox[3] <= 90):
        raise ValueError("bbox inválido; esperado min_lon,min_lat,max_lon,max_lat")
    payload: dict[str, Any] = {"bbox": list(bbox), "datetime": datetime_range, "limit": max(1, min(int(limit), 100))}
    if collections:
        payload["collections"] = collections[:20]
    return endpoint.rstrip("/"), payload


def search_stac(**kwargs: Any) -> dict[str, Any]:
    endpoint, payload = build_stac_search(**kwargs)
    request = Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers={"Accept": "application/geo+json, application/json", "Content-Type": "application/json", "User-Agent": "Atena-EarthObservation/1.0"}, method="POST")
    with urlopen(request, timeout=15.0) as response:
        result = json.loads(response.read().decode("utf-8"))
    features = result.get("features", []) if isinstance(result, dict) else []
    return {"source": endpoint, "query": payload, "features": features[:100], "read_only": True, "provenance_required": True}


def search_nasa_cmr(*, keyword: str, page_size: int = 10, timeout: float = 15.0) -> dict[str, Any]:
    params = urlencode({"keyword": keyword[:200], "page_size": max(1, min(int(page_size), 100)), "format": "json"})
    url = "https://cmr.earthdata.nasa.gov/search/granules.json?" + params
    payload = _get_json(url, timeout=timeout)
    entries = payload.get("feed", {}).get("entry", []) if isinstance(payload.get("feed"), dict) else []
    return {"source": url, "query": {"keyword": keyword[:200]}, "granules": entries[:100], "read_only": True, "provenance_required": True}


def satellite_capability(question: str) -> dict[str, Any]:
    """Retorna um plano seguro de pesquisa, sem fazer chamada externa."""
    return {
        "capability": "earth_observation",
        "question": question[:500],
        "tools": ["stac_catalog_search", "nasa_cmr_search", "metadata_provenance"],
        "sources": load_sources(),
        "read_only": True,
        "limits": ["não controla satélites", "não envia comandos", "não interpreta imagem sem dados e validação", "não baixa arquivos por padrão"],
    }


__all__ = ["build_stac_search", "load_sources", "satellite_capability", "search_nasa_cmr", "search_stac"]
