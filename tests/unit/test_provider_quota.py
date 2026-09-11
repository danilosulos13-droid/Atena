from core.provider_quota import QuotaLedger


def test_daily_request_limit(monkeypatch, tmp_path):
    monkeypatch.setenv("ATENA_GEMINI_DAILY_REQUESTS", "1")
    ledger = QuotaLedger(str(tmp_path / "quota.sqlite3"))
    assert ledger.available("gemini")
    ledger.record("gemini", tokens=20)
    assert not ledger.available("gemini")


def test_daily_token_limit(monkeypatch, tmp_path):
    monkeypatch.setenv("ATENA_ANTHROPIC_DAILY_TOKENS", "10")
    ledger = QuotaLedger(str(tmp_path / "quota.sqlite3"))
    ledger.record("anthropic", tokens=10)
    assert not ledger.available("anthropic")


def test_cooldown_expires(monkeypatch, tmp_path):
    ledger = QuotaLedger(str(tmp_path / "quota.sqlite3"))
    ledger.cooldown("gemini", 60, "HTTP 429 quota")
    assert not ledger.available("gemini")
    row = ledger.snapshot()[0]
    assert row["last_error"] == "HTTP 429 quota"
