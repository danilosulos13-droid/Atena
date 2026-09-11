"""Pesquisa web pública e controlada para perguntas factuais atuais."""
from __future__ import annotations

import html
import logging
import os
import re
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup

LOG = logging.getLogger("atena.web_research")
SEARCH_URLS = (
    "https://news.google.com/rss/search?q={query}&hl=pt-BR&gl=BR&ceid=BR:pt-419",
    "https://www.bing.com/search?format=rss&q={query}",
    "https://html.duckduckgo.com/html/?q={query}",
)
USER_AGENT = "Atena-IA factual research/1.0"
ALLOWED_SCHEMES = {"http", "https"}


@dataclass(frozen=True)
class WebEvidence:
    title: str
    url: str
    snippet: str


def _valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in ALLOWED_SCHEMES and bool(parsed.netloc)


def _normalize_results(items: list[dict], limit: int) -> list[WebEvidence]:
    results: list[WebEvidence] = []
    seen: set[str] = set()
    for item in items:
        url = html.unescape(str(item.get("url", ""))).strip()
        if not _valid_url(url) or url in seen:
            continue
        results.append(WebEvidence(
            title=re.sub(r"\s+", " ", str(item.get("title", "Sem título")))[:240],
            url=url,
            snippet=re.sub(r"\s+", " ", str(item.get("snippet", "")))[:700],
        ))
        seen.add(url)
        if len(results) >= max(1, min(limit, 10)):
            break
    return results


def _tavily_search(query: str, limit: int, timeout: int) -> list[WebEvidence]:
    key = os.getenv("ATENA_TAVILY_API_KEY", "").strip()
    if not key:
        return []
    response = requests.post(
        "https://api.tavily.com/search",
        json={"api_key": key, "query": query, "search_depth": os.getenv("ATENA_TAVILY_SEARCH_DEPTH", "basic"), "max_results": min(limit, 10), "include_answer": False},
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    items = [
        {"title": item.get("title", ""), "url": item.get("url", ""), "snippet": item.get("content", item.get("snippet", ""))}
        for item in payload.get("results", [])
    ]
    return _normalize_results(items, limit)


def _google_search(query: str, limit: int, timeout: int) -> list[WebEvidence]:
    key = os.getenv("ATENA_GOOGLE_API_KEY", "").strip()
    cx = os.getenv("ATENA_GOOGLE_CSE_ID", "").strip()
    if not key or not cx:
        return []
    response = requests.get(
        "https://www.googleapis.com/customsearch/v1",
        params={"key": key, "cx": cx, "q": query, "num": min(limit, 10), "safe": "active"},
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    items = [
        {"title": item.get("title", ""), "url": item.get("link", ""), "snippet": item.get("snippet", "")}
        for item in payload.get("items", [])
    ]
    return _normalize_results(items, limit)


def _provider_search(query: str, limit: int, timeout: int) -> list[WebEvidence]:
    providers = [os.getenv("ATENA_WEB_SEARCH_PROVIDER", "tavily").strip().lower()]
    if os.getenv("ATENA_WEB_SEARCH_PROVIDER", "").strip().lower() == "auto":
        providers = ["tavily", "google"]
    for provider in providers:
        try:
            if provider == "tavily":
                results = _tavily_search(query, limit, timeout)
            elif provider in {"google", "google_cse", "customsearch"}:
                results = _google_search(query, limit, timeout)
            else:
                LOG.warning("provedor web desconhecido: %s", provider)
                continue
            if results:
                LOG.info("pesquisa web concluída via %s: %d fontes", provider, len(results))
                return results
        except (requests.RequestException, ValueError) as exc:
            LOG.warning("provedor web %s indisponível: %s", provider, exc)
    return []


def search_web(query: str, limit: int = 5, timeout: int = 20) -> list[WebEvidence]:
    """Consulta provedores configurados e só depois tenta fontes públicas sem chave."""
    query = " ".join(query.split())[:300]
    if not query:
        return []
    provider_results = _provider_search(query, limit, timeout)
    if provider_results:
        return provider_results

    response = None
    last_error: Exception | None = None
    for template in SEARCH_URLS:
        try:
            candidate = requests.get(
                template.format(query=quote_plus(query)),
                headers={"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7"},
                timeout=timeout,
            )
            candidate.raise_for_status()
            response = candidate
            break
        except requests.RequestException as exc:
            last_error = exc
            LOG.warning("fonte de busca indisponível: %s", template.split("/", 3)[2])
    if response is not None:
        soup = BeautifulSoup(response.text, "xml" if "xml" in response.headers.get("content-type", "").lower() or "rss" in response.text[:300].lower() else "html.parser")
        rss_items = soup.select("item")
        if rss_items:
            rss_payload = []
            for item in rss_items:
                link = item.select_one("link")
                # Google News places the canonical URL in <link href=...> in
                # some responses and in element text in others.
                url = (link.get("href", "") if link else "") or (link.get_text(strip=True) if link else "")
                rss_payload.append({
                    "title": item.select_one("title").get_text(" ", strip=True) if item.select_one("title") else "",
                    "url": url,
                    "snippet": item.select_one("description").get_text(" ", strip=True) if item.select_one("description") else "",
                })
            results = _normalize_results(rss_payload, limit)
            if results:
                return results
        results = _normalize_results([
            {"title": card.select_one("a.result__a").get_text(" ", strip=True), "url": card.select_one("a.result__a").get("href", ""), "snippet": card.select_one(".result__snippet").get_text(" ", strip=True) if card.select_one(".result__snippet") else ""}
            for card in soup.select(".result") if card.select_one("a.result__a[href]")
        ], limit)
        if results:
            return results
    if last_error:
        LOG.warning("nenhuma busca pública respondeu: %s", last_error)
    return _sports_fallback(query, timeout=timeout)


def _sports_fallback(query: str, timeout: int = 20) -> list[WebEvidence]:
    """Consulta calendário público da ESPN para perguntas esportivas."""
    lowered = query.casefold()
    teams = ("santos", "palmeiras", "corinthians", "são paulo", "flamengo")
    if not any(team in lowered for team in teams):
        return []
    start = date.today().strftime("%Y%m%d")
    end = (date.today() + timedelta(days=90)).strftime("%Y%m%d")
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/bra.1/scoreboard?limit=500&dates={start}-{end}"
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        LOG.warning("fallback esportivo indisponível: %s", exc)
        return []
    results: list[WebEvidence] = []
    for event in data.get("events", []):
        text = str(event)
        if not any(team in text.casefold() for team in teams):
            continue
        competition = (event.get("competitions") or [{}])[0]
        names = [item.get("team", {}).get("displayName", "") for item in competition.get("competitors", [])]
        title = " x ".join(name for name in names if name) or event.get("name", "Jogo")
        results.append(WebEvidence(title=f"{title} — calendário esportivo", url=url, snippet=f"Data/hora: {event.get('date', '')}. Competição: {competition.get('league', {}).get('name', 'futebol brasileiro')}."))
    return results[:10]


def build_context(query: str, evidence: list[WebEvidence]) -> str:
    if not evidence:
        return "Nenhuma fonte pública foi encontrada; não invente uma resposta atual."
    lines = ["Você recebeu fontes públicas para responder uma pergunta atual.", "Use somente o que estiver sustentado pelos trechos abaixo, informe a data de consulta e inclua as URLs como fontes.", "Se as fontes divergirem ou não confirmarem a data, diga isso claramente.", f"Pergunta pesquisada: {query}", ""]
    for index, item in enumerate(evidence, 1):
        lines.extend([f"Fonte {index}: {item.title}", f"URL: {item.url}", f"Trecho: {item.snippet}", ""])
    return "\n".join(lines)
