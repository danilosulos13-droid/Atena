"""Deduplicação semântica e detecção de mudanças para notícias e ofertas.

A identidade de um item usa URL canônica quando disponível e, como fallback,
uma combinação de fonte, título normalizado e identificador externo. O conteúdo
é versionado por hash; alterações de preço são tratadas separadamente para que
uma queda ou aumento relevante gere novo alerta sem duplicar a mesma oferta.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

DEFAULT_DB = Path("atena_evolution/memory.sqlite3")
_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid", "mc_cid", "mc_eid"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_text(value: str | None) -> str:
    raw = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z0-9]+", raw.casefold()))


def canonical_url(value: str | None) -> str:
    if not value:
        return ""
    parsed = urlsplit(value.strip())
    query = [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True) if key.casefold() not in _TRACKING_PARAMS]
    return urlunsplit((parsed.scheme.casefold(), parsed.netloc.casefold(), parsed.path.rstrip("/"), urlencode(sorted(query)), ""))


def content_hash(*parts: str | None) -> str:
    normalized = "\n".join(normalize_text(part) for part in parts)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    left_tokens, right_tokens = set(left.split()), set(right.split())
    jaccard = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
    sequence = SequenceMatcher(None, left, right).ratio()
    return round(0.55 * jaccard + 0.45 * sequence, 6)


@dataclass(frozen=True)
class MonitoredItem:
    kind: str
    source: str
    title: str
    url: str = ""
    summary: str = ""
    content: str = ""
    external_id: str = ""
    price: float | None = None
    discount_percent: float | None = None
    currency: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def normalized_title(self) -> str:
        return normalize_text(self.title)

    @property
    def identity(self) -> str:
        stable = canonical_url(self.url) or self.external_id or f"{self.source}:{self.normalized_title}"
        return hashlib.sha256(f"{self.kind}|{stable}".encode("utf-8")).hexdigest()

    @property
    def fingerprint(self) -> str:
        return content_hash(self.title, self.summary, self.content, json.dumps(self.metadata, sort_keys=True, ensure_ascii=False))


@dataclass(frozen=True)
class ObservationResult:
    action: str
    identity: str
    reason: str
    similarity: float
    changed_fields: tuple[str, ...] = ()
    previous: dict[str, Any] | None = None


class SemanticDeduplicator:
    def __init__(self, db_path: str | Path = DEFAULT_DB) -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=30000")
        self.ensure_schema()

    def __enter__(self) -> "SemanticDeduplicator":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def ensure_schema(self) -> None:
        with self.connection:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS semantic_items (
                    identity TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    source TEXT NOT NULL,
                    title TEXT NOT NULL,
                    normalized_title TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    price REAL,
                    discount_percent REAL,
                    currency TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    last_changed_at TEXT,
                    seen_count INTEGER NOT NULL DEFAULT 1
                );
                CREATE INDEX IF NOT EXISTS idx_semantic_kind_source ON semantic_items(kind, source);
                CREATE INDEX IF NOT EXISTS idx_semantic_last_seen ON semantic_items(last_seen_at DESC);
                CREATE TABLE IF NOT EXISTS semantic_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    identity TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    action TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    changed_fields_json TEXT NOT NULL,
                    similarity REAL NOT NULL,
                    previous_json TEXT
                );
                """
            )

    def observe(self, item: MonitoredItem, *, similarity_threshold: float = 0.88, price_epsilon: float = 0.01) -> ObservationResult:
        stamp = utc_now()
        row = self.connection.execute("SELECT * FROM semantic_items WHERE identity=?", (item.identity,)).fetchone()
        if row is None:
            action, reason, similarity, changed = "new", "identidade ainda não observada", 0.0, ()
            with self.connection:
                self.connection.execute(
                    """INSERT INTO semantic_items
                    (identity, kind, source, title, normalized_title, canonical_url, summary, content_hash,
                     price, discount_percent, currency, metadata_json, first_seen_at, last_seen_at, last_changed_at, seen_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                    (item.identity, item.kind, item.source, item.title, item.normalized_title, canonical_url(item.url),
                     item.summary, item.fingerprint, item.price, item.discount_percent, item.currency,
                     json.dumps(item.metadata, ensure_ascii=False, sort_keys=True), stamp, stamp, stamp),
                )
        else:
            previous = dict(row)
            changed_fields: list[str] = []
            previous_title = str(row["normalized_title"] or "")
            similarity = _similarity(previous_title, item.normalized_title)
            if row["content_hash"] != item.fingerprint and similarity >= similarity_threshold:
                changed_fields.append("content")
            if row["price"] is not None and item.price is not None and abs(float(row["price"]) - float(item.price)) > price_epsilon:
                changed_fields.append("price")
            if row["discount_percent"] is not None and item.discount_percent is not None and abs(float(row["discount_percent"]) - float(item.discount_percent)) > price_epsilon:
                changed_fields.append("discount_percent")
            if normalize_text(row["title"]) != item.normalized_title:
                changed_fields.append("title")
            if changed_fields:
                action, reason = "changed", "item observado novamente com mudança relevante"
                with self.connection:
                    self.connection.execute(
                        """UPDATE semantic_items SET title=?, normalized_title=?, canonical_url=?, summary=?, content_hash=?,
                        price=?, discount_percent=?, currency=?, metadata_json=?, last_seen_at=?, last_changed_at=?, seen_count=seen_count+1
                        WHERE identity=?""",
                        (item.title, item.normalized_title, canonical_url(item.url), item.summary, item.fingerprint,
                         item.price, item.discount_percent, item.currency, json.dumps(item.metadata, ensure_ascii=False, sort_keys=True),
                         stamp, stamp, item.identity),
                    )
            else:
                action, reason, changed_fields = "duplicate", "conteúdo e valores relevantes sem mudança", []
                with self.connection:
                    self.connection.execute("UPDATE semantic_items SET last_seen_at=?, seen_count=seen_count+1 WHERE identity=?", (stamp, item.identity))
            changed = tuple(dict.fromkeys(changed_fields))
            previous = {key: previous[key] for key in ("title", "summary", "price", "discount_percent", "currency", "content_hash")}
        with self.connection:
            self.connection.execute(
                "INSERT INTO semantic_events(identity, observed_at, action, reason, changed_fields_json, similarity, previous_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (item.identity, stamp, action, reason, json.dumps(changed, ensure_ascii=False), similarity,
                 json.dumps(previous, ensure_ascii=False, sort_keys=True) if row is not None else None),
            )
        return ObservationResult(action, item.identity, reason, similarity, changed, previous if row is not None else None)

    def recent_events(self, *, kind: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT e.* FROM semantic_events e JOIN semantic_items i ON i.identity=e.identity"
        args: list[Any] = []
        if kind:
            query += " WHERE i.kind=?"; args.append(kind)
        query += " ORDER BY e.event_id DESC LIMIT ?"; args.append(max(1, min(limit, 1000)))
        rows = self.connection.execute(query, args).fetchall()
        return [dict(row) for row in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspeciona o histórico de deduplicação semântica")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--kind")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    with SemanticDeduplicator(args.db) as dedup:
        print(json.dumps(dedup.recent_events(kind=args.kind, limit=args.limit), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
