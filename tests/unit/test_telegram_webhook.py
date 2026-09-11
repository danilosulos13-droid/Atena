import importlib

import pytest


@pytest.fixture
def webhook(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "webhook-secret")
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", "12345")
    monkeypatch.setenv("ATENA_BACKEND_URL", "https://backend.example.test/telegram")
    return importlib.import_module("api.telegram_webhook")


def test_webhook_rejects_invalid_secret(webhook):
    from fastapi.testclient import TestClient

    response = TestClient(webhook.app).post(
        "/api/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        json={"update_id": 1, "message": {"chat": {"id": 12345}}},
    )

    assert response.status_code == 403


def test_webhook_ignores_non_message_updates(webhook):
    from fastapi.testclient import TestClient

    response = TestClient(webhook.app).post(
        "/api/telegram/webhook",
        headers={"X-Telegram-Bot-Api-Secret-Token": "webhook-secret"},
        json={"update_id": 2, "callback_query": {"id": "x"}},
    )

    assert response.status_code == 200
    assert response.json()["ignored"] == "unsupported_update"
