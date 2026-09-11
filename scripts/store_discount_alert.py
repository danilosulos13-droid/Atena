"""Monitor de descontos da Atena para Steam, Epic, GOG, Nuuvem e Humble Bundle.

O script possui dois usos principais:

1. `run`: consulta as lojas, confirma as ofertas, grava apenas alertas novos no
   SQLite e envia mensagens Telegram.
2. `best_deals`: consulta as ofertas atuais e devolve as melhores promoções,
   sem gravar nem enviar alertas.

As páginas das lojas são fontes públicas sujeitas a mudanças de layout. O
monitor falha de forma conservadora: uma página vazia ou alterada gera erro,
mas não encerra ofertas antigas no banco.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.monitoring_health import MonitoringHealth
from core.semantic_dedup import MonitoredItem, SemanticDeduplicator

USER_AGENT = os.getenv("ATENA_STORE_USER_AGENT", "Atena-IA store discount monitor/1.0")
LOG = logging.getLogger("atena.store_discount_alert")

EPIC_FREE_API = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions?locale=pt-BR&country=BR&allowCountries=BR"

URLS = {
    "steam": "https://store.steampowered.com/search/?specials=1&cc=br&l=portuguese",
    "epic": "https://store.epicgames.com/pt-BR/sales-and-specials",
    "gog": "https://www.gog.com/en/games?discounted=true",
    "nuuvem": "https://www.nuuvem.com/br-pt/promo/ofertas-nuuvem",
    "humble": "https://www.humblebundle.com/store",
}

# Mantemos as fontes de gratuidade já validadas pelo monitor anterior.
FREE_GAME_SCRIPT = ROOT / "scripts" / "steam_free_alert.py"


@dataclass(frozen=True)
class Deal:
    store: str
    product_id: str
    title: str
    product_url: str
    source_url: str
    discount_percent: float
    current_price: str | None = None
    original_price: str | None = None
    currency: str | None = None
    expires_at: str | None = None
    offer_type: str = "discount"

    @property
    def key(self) -> str:
        raw = "|".join(
            [
                self.store,
                self.product_id,
                self.offer_type,
                str(self.discount_percent),
                self.current_price or "",
                self.expires_at or "unknown",
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def http_get(session: requests.Session, url: str, timeout: int = 30) -> requests.Response:
    response = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    return response


def clean_title(value: str, fallback: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"(?:save|saved|comprar|buy)\s*$", "", value, flags=re.I).strip()
    return value or fallback


def parse_discount(text: str) -> float | None:
    match = re.search(r"(?:-|−)\s*(\d{1,3})(?:[,.]0+)?\s*%", text, flags=re.I)
    if not match:
        match = re.search(r"(\d{1,3})(?:[,.]0+)?\s*%\s*(?:off|desconto)", text, flags=re.I)
    if not match:
        return None
    value = float(match.group(1))
    return value if 0 < value <= 100 else None


def price_pair(text: str) -> tuple[str | None, str | None]:
    # Mantém a moeda e a representação original para não converter valores
    # regionais de forma incorreta.
    prices = re.findall(r"(?:R\$|US\$|€|£|[$₺])\s*[\d.,]+", text)
    if not prices:
        return None, None
    # Nas listagens observadas, o preço original aparece antes do preço atual.
    # Usar o último valor como atual evita notificar o valor cheio como promoção.
    if len(prices) == 1:
        return prices[0], None
    return prices[-1], prices[-2]


def extract_link_deals(store: str, html: str, source_url: str, minimum_discount: float) -> list[Deal]:
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, Deal] = {}
    for link in soup.select("a[href]"):
        href = urljoin(source_url, link.get("href", ""))
        if not href.startswith("http"):
            continue
        if store == "steam" and not re.search(r"/app/\d+", href):
            continue
        if store == "epic" and "/p/" not in href and "/game/" not in href:
            continue
        if store == "gog" and "/game/" not in href:
            continue
        if store == "nuuvem" and not re.search(r"/(?:item|product)/", href):
            continue
        if store == "humble" and "/store/" not in href:
            continue

        container = link
        # O desconto normalmente está no cartão pai; subir poucos níveis
        # evita capturar o texto de toda a página.
        for _ in range(4):
            text = container.get_text(" ", strip=True)
            if parse_discount(text) is not None:
                break
            container = container.parent or container
        text = container.get_text(" ", strip=True)
        discount = parse_discount(text)
        if discount is None or discount < minimum_discount:
            continue

        match = re.search(r"/(?:app|game|p|item|product|store)/([^/?#]+)", href)
        if not match:
            continue
        product_id = match.group(1)
        title = clean_title(link.get_text(" ", strip=True), product_id.replace("-", " ").title())
        current, original = price_pair(text)
        deal = Deal(
            store=store,
            product_id=product_id,
            title=title,
            product_url=href,
            source_url=source_url,
            discount_percent=discount,
            current_price=current,
            original_price=original,
        )
        result[deal.product_id] = deal
    return list(result.values())


def discover_steam(session: requests.Session, minimum_discount: float) -> list[Deal]:
    return extract_link_deals("steam", http_get(session, URLS["steam"]).text, URLS["steam"], minimum_discount)


def discover_epic(session: requests.Session, minimum_discount: float) -> list[Deal]:
    try:
        return extract_link_deals("epic", http_get(session, URLS["epic"]).text, URLS["epic"], minimum_discount)
    except requests.HTTPError as exc:
        # A vitrine de vendas pode bloquear clientes sem JavaScript. O endpoint
        # público oficial continua sendo uma fonte válida para jogos gratuitos.
        if getattr(exc.response, "status_code", None) != 403:
            raise
        payload = http_get(session, EPIC_FREE_API).json()
        elements = payload.get("data", {}).get("Catalog", {}).get("searchStore", {}).get("elements", [])
        deals: list[Deal] = []
        for element in elements:
            promotions = element.get("promotions") or {}
            offers = promotions.get("promotionalOffers") or []
            if not offers:
                continue
            offer = (offers[0].get("promotionalOffers") or [{}])[0]
            slug = element.get("productSlug") or element.get("id")
            if not slug:
                continue
            deals.append(
                Deal(
                    store="epic",
                    product_id=str(element.get("id") or slug),
                    title=str(element.get("title") or "Epic Games Store — oferta gratuita"),
                    product_url=f"https://store.epicgames.com/p/{slug}",
                    source_url=EPIC_FREE_API,
                    discount_percent=100.0,
                    expires_at=offer.get("endDate"),
                    offer_type="free_to_keep",
                )
            )
        return deals


def discover_gog(session: requests.Session, minimum_discount: float) -> list[Deal]:
    return extract_link_deals("gog", http_get(session, URLS["gog"]).text, URLS["gog"], minimum_discount)


def discover_nuuvem(session: requests.Session, minimum_discount: float) -> list[Deal]:
    return extract_link_deals("nuuvem", http_get(session, URLS["nuuvem"]).text, URLS["nuuvem"], minimum_discount)


def discover_humble(session: requests.Session, minimum_discount: float) -> list[Deal]:
    return extract_link_deals("humble", http_get(session, URLS["humble"]).text, URLS["humble"], minimum_discount)


DISCOVERERS = {
    "steam": discover_steam,
    "epic": discover_epic,
    "gog": discover_gog,
    "nuuvem": discover_nuuvem,
    "humble": discover_humble,
}


def ensure_schema(db: sqlite3.Connection) -> None:
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=10000")
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS store_discount_alerts (
            alert_key TEXT PRIMARY KEY,
            store TEXT NOT NULL,
            product_id TEXT NOT NULL,
            title TEXT NOT NULL,
            offer_type TEXT NOT NULL,
            product_url TEXT NOT NULL,
            source_url TEXT NOT NULL,
            current_price TEXT,
            original_price TEXT,
            currency TEXT,
            discount_percent REAL NOT NULL,
            expires_at TEXT,
            first_seen_at TEXT NOT NULL,
            last_notified_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'notified'
        )
        """
    )
    db.execute("CREATE INDEX IF NOT EXISTS idx_store_discount_store ON store_discount_alerts(store)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_store_discount_date ON store_discount_alerts(first_seen_at)")
    db.commit()


def already_seen(db: sqlite3.Connection, deal: Deal) -> bool:
    return db.execute("SELECT 1 FROM store_discount_alerts WHERE alert_key = ?", (deal.key,)).fetchone() is not None


def save_deal(db: sqlite3.Connection, deal: Deal) -> None:
    stamp = now()
    db.execute(
        """
        INSERT INTO store_discount_alerts
        (alert_key, store, product_id, title, offer_type, product_url, source_url,
         current_price, original_price, currency, discount_percent, expires_at,
         first_seen_at, last_notified_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'notified')
        """,
        (
            deal.key,
            deal.store,
            deal.product_id,
            deal.title,
            deal.offer_type,
            deal.product_url,
            deal.source_url,
            deal.current_price,
            deal.original_price,
            deal.currency,
            deal.discount_percent,
            deal.expires_at,
            stamp,
            stamp,
        ),
    )


def _numeric_price(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"([0-9][0-9.,]*)", value.replace(" ", ""))
    if not match:
        return None
    raw = match.group(1)
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def telegram_send(token: str, chat_id: str, text: str) -> None:
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": text, "disable_web_page_preview": "false"},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(payload.get("description", "Telegram recusou a mensagem"))


def format_deal(deal: Deal) -> str:
    lines = [
        f"ATENA — desconto encontrado na {deal.store.upper()}",
        "",
        f"Título: {deal.title}",
        f"Desconto: {deal.discount_percent:g}% OFF",
    ]
    if deal.current_price:
        lines.append(f"Preço atual: {deal.current_price}")
    if deal.original_price:
        lines.append(f"Preço anterior: {deal.original_price}")
    if deal.expires_at:
        lines.append(f"Prazo: {deal.expires_at}")
    lines.extend(["", f"Comprar: {deal.product_url}", f"Fonte: {deal.source_url}"])
    return "\n".join(lines)


def collect(stores: list[str], minimum_discount: float = 50.0) -> tuple[list[Deal], list[str]]:
    session = requests.Session()
    deals: list[Deal] = []
    errors: list[str] = []
    health: MonitoringHealth | None = None
    try:
        health = MonitoringHealth(os.getenv("ATENA_MEMORY_DB", "atena_evolution/memory.sqlite3"))
    except Exception as exc:
        LOG.warning("monitoramento de saúde indisponível: %s", exc)
    try:
        for store in stores:
            started = time.monotonic()
            try:
                found = DISCOVERERS[store](session, minimum_discount)
                if len(found) > int(os.getenv("ATENA_MAX_STORE_ITEMS", "200")):
                    found = found[: int(os.getenv("ATENA_MAX_STORE_ITEMS", "200"))]
                deals.extend(found)
                if health:
                    health.record_check(store, status="healthy" if found else "degraded",
                                        latency_ms=(time.monotonic() - started) * 1000,
                                        item_count=len(found))
            except Exception as exc:
                LOG.warning("falha em %s: %s", store, exc)
                errors.append(f"{store}: {type(exc).__name__}: {exc}")
                response = getattr(exc, "response", None)
                http_status = getattr(response, "status_code", None)
                if health:
                    health.record_check(store, status="blocked" if http_status == 403 else "failed",
                                        http_status=http_status, latency_ms=(time.monotonic() - started) * 1000,
                                        error_type=type(exc).__name__, error_message=str(exc))
    finally:
        if health:
            health.close()
    unique = {deal.key: deal for deal in deals}
    return sorted(unique.values(), key=lambda item: (-item.discount_percent, item.store, item.title.lower())), errors


def best_deals(stores: list[str], minimum_discount: float = 50.0, limit: int = 10) -> dict:
    deals, errors = collect(stores, minimum_discount)
    return {
        "stores": stores,
        "minimum_discount": minimum_discount,
        "deals": [deal.__dict__ | {"key": deal.key} for deal in deals[:limit]],
        "errors": errors,
        "checked_at": now(),
    }


def run(db_path: Path, stores: list[str], minimum_discount: float = 50.0, dry_run: bool = False) -> dict:
    token = os.getenv("ATENA_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("ATENA_TELEGRAM_CHAT_ID", "").strip()
    if not dry_run and (not token or not chat_id):
        raise RuntimeError("ATENA_TELEGRAM_BOT_TOKEN e ATENA_TELEGRAM_CHAT_ID são obrigatórios")

    deals, errors = collect(stores, minimum_discount)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Lê as chaves legadas e fecha a conexão antes de abrir o deduplicador
    # semântico. Isso evita dois escritores SQLite ativos no mesmo arquivo.
    legacy_db = sqlite3.connect(db_path, timeout=30)
    legacy_db.execute("PRAGMA busy_timeout=30000")
    ensure_schema(legacy_db)
    legacy_keys = {row[0] for row in legacy_db.execute("SELECT alert_key FROM store_discount_alerts")}
    legacy_db.close()

    actionable: list[tuple[Deal, str]] = []
    with SemanticDeduplicator(db_path) as semantic:
        for deal in deals:
            observation = semantic.observe(MonitoredItem(
                kind="game_offer", source=deal.store, title=deal.title,
                url=deal.product_url, external_id=deal.product_id,
                summary=f"{deal.current_price or ''} {deal.original_price or ''}",
                price=_numeric_price(deal.current_price),
                discount_percent=deal.discount_percent,
                currency=deal.currency,
                metadata={"offer_type": deal.offer_type, "expires_at": deal.expires_at},
            ))
            if observation.action == "duplicate" or deal.key in legacy_keys:
                continue
            actionable.append((deal, observation.action))

    db = sqlite3.connect(db_path, timeout=30)
    db.execute("PRAGMA busy_timeout=30000")
    ensure_schema(db)
    sent = 0
    try:
        for deal, action in actionable:
            message = format_deal(deal)
            if action == "changed":
                message = "ATENA — alteração detectada em oferta existente\n\n" + message
            if dry_run:
                print(message + "\n")
            else:
                telegram_send(token, chat_id, message)
            save_deal(db, deal)
            sent += 1
        db.commit()
    finally:
        db.close()
    return {
        "stores": stores,
        "discovered": len(deals),
        "sent": sent,
        "errors": errors,
        "checked_at": now(),
    }


def workflow_exit_code(report: dict) -> int:
    """Retorna falha apenas quando nenhuma loja conseguiu ser processada."""
    stores = list(report.get("stores") or [])
    errors = list(report.get("errors") or [])
    if errors and len(errors) >= len(stores):
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitora descontos nas lojas de jogos")
    parser.add_argument("--db", type=Path, default=Path(os.getenv("ATENA_MEMORY_DB", "atena_evolution/memory.sqlite3")))
    parser.add_argument("--stores", nargs="+", choices=sorted(DISCOVERERS), default=sorted(DISCOVERERS))
    parser.add_argument("--minimum-discount", type=float, default=float(os.getenv("ATENA_MIN_DISCOUNT", "50")))
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--best-deals", action="store_true", help="consulta as melhores ofertas sem gravar nem notificar")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.best_deals:
        print(json.dumps(best_deals(args.stores, args.minimum_discount, args.limit), ensure_ascii=False, indent=2))
        return 0
    report = run(args.db, args.stores, args.minimum_discount, args.dry_run)
    print(json.dumps(report, ensure_ascii=False))
    return workflow_exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
