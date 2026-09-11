from __future__ import annotations

import sqlite3

from scripts.store_discount_alert import Deal, ensure_schema, extract_link_deals, save_deal


STEAM_HTML = """
<a href="https://store.steampowered.com/app/42/Test_Game/">
  Test Game -75% R$ 100,00 R$ 25,00
</a>
"""


def test_extract_link_deals_parses_discount_and_prices() -> None:
    deals = extract_link_deals(
        "steam",
        STEAM_HTML,
        "https://store.steampowered.com/search/?specials=1",
        50,
    )
    assert len(deals) == 1
    assert deals[0].product_id == "42"
    assert deals[0].discount_percent == 75
    assert deals[0].current_price == "R$ 25,00"
    assert deals[0].original_price == "R$ 100,00"


def test_deal_key_changes_when_price_changes() -> None:
    first = Deal("nuuvem", "abc", "Game", "https://example.test/a", "https://example.test", 50, "R$ 10")
    second = Deal("nuuvem", "abc", "Game", "https://example.test/a", "https://example.test", 60, "R$ 8")
    assert first.key != second.key


def test_save_deal_is_idempotent_by_key() -> None:
    db = sqlite3.connect(":memory:")
    ensure_schema(db)
    deal = Deal("humble", "bundle-1", "Bundle", "https://example.test/b", "https://example.test", 70, "$ 5", "$ 20")
    save_deal(db, deal)
    db.commit()
    row = db.execute("SELECT store, discount_percent FROM store_discount_alerts WHERE alert_key = ?", (deal.key,)).fetchone()
    assert row == ("humble", 70.0)


from scripts.store_discount_alert import workflow_exit_code


def test_partial_store_failure_keeps_workflow_successful():
    report = {
        "stores": ["steam", "epic", "gog", "nuuvem", "humble"],
        "errors": ["nuuvem: HTTPError: 403 Client Error: Forbidden"],
    }
    assert workflow_exit_code(report) == 0


def test_all_store_failures_keep_workflow_failed():
    report = {
        "stores": ["steam", "epic"],
        "errors": ["steam: TimeoutError", "epic: HTTPError: 503"],
    }
    assert workflow_exit_code(report) == 1


def test_no_store_errors_are_successful():
    report = {"stores": ["steam"], "errors": []}
    assert workflow_exit_code(report) == 0
