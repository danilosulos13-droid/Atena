#!/usr/bin/env python3
"""Monitora promoções gratuitas da Steam, Epic e GOG e alerta o Telegram."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

USER_AGENT = "Atena-IA free-game monitor/1.1"
STEAMDB_URL = "https://steamdb.info/upcoming/free/"
STEAM_STORE_URL = "https://store.steampowered.com/app/{app_id}/?l=english"
EPIC_FREE_API = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions?locale=pt-BR&country=BR&allowCountries=BR"
EPIC_FREE_PAGE = "https://store.epicgames.com/free-games?lang=pt-BR"
GOG_FREE_PAGE = "https://www.gog.com/en/partner/free_games"


@dataclass
class Promotion:
    store: str
    app_id: str
    title: str
    store_url: str
    source_url: str
    promotion_type: str
    expires_at: str | None
    description: str

    @property
    def key(self) -> str:
        raw = f"{self.store}:{self.app_id}:{self.promotion_type}:{self.expires_at or 'permanent'}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def http_get(url: str, timeout: int = 30) -> requests.Response:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    return response


def discover_steam() -> list[dict]:
    response = http_get(STEAMDB_URL)
    soup = BeautifulSoup(response.text, "html.parser")
    result: list[dict] = []
    for link in soup.select("a[href*='/app/']"):
        href = urljoin(STEAMDB_URL, link.get("href", ""))
        match = re.search(r"/app/(\d+)", href)
        if not match:
            continue
        item = {"store": "steam", "app_id": match.group(1), "title": link.get_text(" ", strip=True), "source_url": href}
        if not item["title"]:
            item["title"] = f"App {item['app_id']}"
        if item not in result:
            result.append(item)
    return result


def discover_epic() -> list[dict]:
    """Usa o endpoint público do backend da própria Epic, sem credenciais."""
    payload = http_get(EPIC_FREE_API).json()
    elements = payload.get("data", {}).get("Catalog", {}).get("searchStore", {}).get("elements", [])
    result: list[dict] = []
    for element in elements:
        promotions = element.get("promotions") or {}
        offers = promotions.get("promotionalOffers") or []
        if not offers:
            continue
        offer = offers[0].get("promotionalOffers", [{}])[0]
        result.append({
            "store": "epic",
            "app_id": element.get("id") or element.get("productSlug") or element.get("namespace"),
            "title": element.get("title") or "Epic Games Store offer",
            "source_url": EPIC_FREE_PAGE,
            "store_url": f"https://store.epicgames.com/p/{element.get('productSlug') or element.get('id')}",
            "starts_at": offer.get("startDate"),
            "expires_at": offer.get("endDate"),
        })
    return [item for item in result if item["app_id"]]


def discover_gog() -> list[dict]:
    """Descobre títulos do catálogo oficial Free Games da GOG."""
    response = http_get(GOG_FREE_PAGE)
    soup = BeautifulSoup(response.text, "html.parser")
    result: list[dict] = []
    for link in soup.select("a[href*='/game/']"):
        href = urljoin(GOG_FREE_PAGE, link.get("href", ""))
        match = re.search(r"/game/([^/?#]+)", href)
        if not match:
            continue
        title = link.get_text(" ", strip=True)
        title = re.sub(r"\\b(owned|free)\\b", " ", title, flags=re.IGNORECASE)
        title = re.sub(r"\\s+", " ", title).strip()
        if not title:
            title = match.group(1).replace("_", " ").title()
        item = {"store": "gog", "app_id": match.group(1), "title": title, "store_url": href, "source_url": GOG_FREE_PAGE}
        if item not in result:
            result.append(item)
    return result


def confirm_steam(candidate: dict) -> Promotion | None:
    app_id = candidate["app_id"]
    details = http_get(f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=br&l=portuguese").json()
    app = details.get(str(app_id), {})
    data = app.get("data", {}) if app.get("success") else {}
    title = str(data.get("name") or candidate["title"])
    store_url = STEAM_STORE_URL.format(app_id=app_id)
    html = http_get(store_url).text.lower()
    plain = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    is_free = bool(data.get("is_free"))
    final_price = (data.get("price_overview") or {}).get("final")
    temporary_markers = ("free weekend", "fim de semana grátis", "free to play this weekend")
    free_markers = temporary_markers + ("free to keep", "gratuito para manter")
    if is_free:
        if os.getenv("ATENA_NOTIFY_PERMANENT_FREE", "0") != "1":
            return None
        return Promotion("steam", app_id, title, store_url, candidate["source_url"], "free_to_play", None, "Jogo permanentemente gratuito.")
    temporary = any(marker in html or marker in plain for marker in temporary_markers)
    has_free_marker = any(marker in html or marker in plain for marker in free_markers)
    if final_price not in (0, "0", None) and not has_free_marker:
        return None
    if not has_free_marker:
        return None
    kind = "free_weekend" if temporary else "free_to_keep"
    description = "Acesso gratuito temporário; pode deixar de funcionar após o prazo." if temporary else "Promoção confirmada na página oficial da Steam."
    return Promotion("steam", app_id, title, store_url, candidate["source_url"], kind, None, description)


def confirm_epic(candidate: dict) -> Promotion | None:
    # O endpoint oficial de freeGamesPromotions já retorna somente ofertas gratuitas.
    expires = candidate.get("expires_at")
    return Promotion(
        "epic", str(candidate["app_id"]), candidate["title"], candidate["store_url"],
        candidate["source_url"], "free_to_keep", expires,
        "Oferta gratuita confirmada pelo catálogo oficial de promoções da Epic Games Store.",
    )


def confirm_gog(candidate: dict) -> Promotion | None:
    if os.getenv("ATENA_NOTIFY_GOG_PERMANENT_FREE", "0") != "1":
        return None
    # A coleção oficial da GOG é a fonte de confirmação e já marca cada item como Free.
    return Promotion(
        "gog", candidate["app_id"], candidate["title"], candidate["store_url"], candidate["source_url"],
        "free_to_play", None, "Jogo gratuito confirmado na coleção oficial Free Games da GOG.",
    )


def ensure_schema(db: sqlite3.Connection) -> None:
    db.execute("""
        CREATE TABLE IF NOT EXISTS steam_alerts (
            promotion_key TEXT PRIMARY KEY,
            store TEXT NOT NULL DEFAULT 'steam',
            app_id TEXT NOT NULL,
            title TEXT NOT NULL,
            promotion_type TEXT NOT NULL,
            store_url TEXT NOT NULL,
            source_url TEXT NOT NULL,
            expires_at TEXT,
            first_seen_at TEXT NOT NULL,
            last_notified_at TEXT NOT NULL,
            status TEXT NOT NULL
        )
    """)
    columns = {row[1] for row in db.execute("PRAGMA table_info(steam_alerts)")}
    if "store" not in columns:
        db.execute("ALTER TABLE steam_alerts ADD COLUMN store TEXT NOT NULL DEFAULT 'steam'")
    db.commit()


def unseen(db: sqlite3.Connection, promotion: Promotion) -> bool:
    return db.execute("SELECT 1 FROM steam_alerts WHERE promotion_key = ?", (promotion.key,)).fetchone() is None


def mark_notified(db: sqlite3.Connection, promotion: Promotion) -> None:
    timestamp = now()
    db.execute("""
        INSERT INTO steam_alerts
        (promotion_key, store, app_id, title, promotion_type, store_url, source_url,
         expires_at, first_seen_at, last_notified_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'notified')
    """, (promotion.key, promotion.store, promotion.app_id, promotion.title, promotion.promotion_type,
          promotion.store_url, promotion.source_url, promotion.expires_at, timestamp, timestamp))


def telegram_send(token: str, chat_id: str, text: str) -> None:
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": text, "disable_web_page_preview": "false"},
        timeout=20,
    )
    response.raise_for_status()
    if not response.json().get("ok"):
        raise RuntimeError(response.json().get("description", "Telegram recusou a mensagem"))


def format_message(promotion: Promotion) -> str:
    labels = {"free_to_keep": "Gratuito para resgatar", "free_weekend": "Free Weekend — acesso temporário", "free_to_play": "Gratuito permanente"}
    return (
        f"ATENA — jogo gratuito confirmado na {promotion.store.upper()}\n\n"
        f"Título: {promotion.title}\nTipo: {labels[promotion.promotion_type]}\n"
        f"{promotion.description}\n"
        + (f"Prazo: {promotion.expires_at}\n" if promotion.expires_at else "")
        + f"\nLoja: {promotion.store_url}\nFonte: {promotion.source_url}"
    )


def run(db_path: Path, stores: list[str], dry_run: bool = False) -> dict:
    token, chat_id = os.getenv("ATENA_TELEGRAM_BOT_TOKEN", "").strip(), os.getenv("ATENA_TELEGRAM_CHAT_ID", "").strip()
    if not dry_run and (not token or not chat_id):
        raise RuntimeError("ATENA_TELEGRAM_BOT_TOKEN e ATENA_TELEGRAM_CHAT_ID são obrigatórios")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(db_path)
    ensure_schema(db)
    discoverers = {"steam": discover_steam, "epic": discover_epic, "gog": discover_gog}
    confirmers = {"steam": confirm_steam, "epic": confirm_epic, "gog": confirm_gog}
    discovered = checked = sent = 0
    errors: list[str] = []
    try:
        for store in stores:
            try:
                candidates = discoverers[store]()
                discovered += len(candidates)
            except Exception as exc:
                errors.append(f"{store}: discovery {type(exc).__name__}: {exc}")
                continue
            for candidate in candidates:
                try:
                    promotion = confirmers[store](candidate)
                    checked += 1
                    if promotion is None or not unseen(db, promotion):
                        continue
                    message = format_message(promotion)
                    if dry_run:
                        print(message + "\n")
                    else:
                        telegram_send(token, chat_id, message)
                    mark_notified(db, promotion)
                    sent += 1
                except Exception as exc:
                    errors.append(f"{store}:{candidate.get('app_id')}: {type(exc).__name__}: {exc}")
        db.commit()
    finally:
        db.close()
    return {"stores": stores, "discovered": discovered, "checked": checked, "sent": sent, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path(os.getenv("ATENA_MEMORY_DB", "atena_evolution/memory.sqlite3")))
    parser.add_argument("--stores", nargs="+", choices=["steam", "epic", "gog"], default=["steam", "epic", "gog"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = run(args.db, args.stores, args.dry_run)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
