from core.monitoring_health import MonitoringHealth, SourceSpec
from core.semantic_dedup import MonitoredItem, SemanticDeduplicator, canonical_url


def test_source_health_records_blocked_403_and_summary(tmp_path):
    db = tmp_path / "health.sqlite3"
    with MonitoringHealth(db) as health:
        health.register_catalog([SourceSpec("nuuvem", "games", "https://example.test/nuuvem")])
        health.record_check("nuuvem", status="blocked", http_status=403, error_type="HTTPError", error_message="Forbidden")
        item = health.source_health("nuuvem")
        assert item["status"] == "blocked"
        assert item["http_status"] == 403
        assert health.summary()["status_counts"]["blocked"] == 1


def test_semantic_dedup_detects_duplicate_then_price_change(tmp_path):
    with SemanticDeduplicator(tmp_path / "semantic.sqlite3") as dedup:
        first = MonitoredItem("game_offer", "steam", "Test Game", "https://example.test/game?utm_source=x", price=10.0, discount_percent=50)
        duplicate = MonitoredItem("game_offer", "steam", "Test Game", "https://example.test/game", price=10.0, discount_percent=50)
        changed = MonitoredItem("game_offer", "steam", "Test Game", "https://example.test/game", price=5.0, discount_percent=75)
        assert canonical_url(first.url) == canonical_url(duplicate.url)
        assert dedup.observe(first).action == "new"
        assert dedup.observe(duplicate).action == "duplicate"
        result = dedup.observe(changed)
        assert result.action == "changed"
        assert "price" in result.changed_fields
        assert "discount_percent" in result.changed_fields


def test_semantic_dedup_detects_news_content_change(tmp_path):
    with SemanticDeduplicator(tmp_path / "semantic.sqlite3") as dedup:
        base = MonitoredItem("news", "ge", "Santos vence", "https://example.test/news", summary="Resumo inicial")
        changed = MonitoredItem("news", "ge", "Santos vence", "https://example.test/news", summary="Resumo atualizado com informação nova")
        assert dedup.observe(base).action == "new"
        result = dedup.observe(changed)
        assert result.action == "changed"
        assert "content" in result.changed_fields
