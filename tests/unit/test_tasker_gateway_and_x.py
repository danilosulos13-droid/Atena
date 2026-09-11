import hashlib
import hmac
import json
import time

from fastapi.testclient import TestClient


def _signed(payload: dict, secret: str, nonce: str):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    message = f"{timestamp}.{nonce}.".encode() + body
    signature = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return body, {"X-Atena-Timestamp": timestamp, "X-Atena-Nonce": nonce, "X-Atena-Signature": signature}


def test_gateway_accepts_signed_whitelisted_command(monkeypatch, tmp_path):
    monkeypatch.setenv("ATENA_TASKER_HMAC_SECRET", "s" * 40)
    monkeypatch.setenv("ATENA_TASKER_GATEWAY_DB", str(tmp_path / "gateway.sqlite3"))
    from api.tasker_command_gateway import app

    body, headers = _signed({"command": "agenda", "device_id": "phone-1"}, "s" * 40, "nonce-123456")
    response = TestClient(app).post("/v1/tasker/commands", content=body, headers=headers)
    assert response.status_code == 200
    assert response.json()["accepted"] is True


def test_gateway_rejects_replayed_nonce(monkeypatch, tmp_path):
    monkeypatch.setenv("ATENA_TASKER_HMAC_SECRET", "s" * 40)
    monkeypatch.setenv("ATENA_TASKER_GATEWAY_DB", str(tmp_path / "gateway.sqlite3"))
    from api.tasker_command_gateway import app

    body, headers = _signed({"command": "agenda", "device_id": "phone-1"}, "s" * 40, "nonce-abcdef")
    client = TestClient(app)
    assert client.post("/v1/tasker/commands", content=body, headers=headers).status_code == 200
    assert client.post("/v1/tasker/commands", content=body, headers=headers).status_code == 409


def test_gateway_rejects_unknown_command(monkeypatch, tmp_path):
    monkeypatch.setenv("ATENA_TASKER_HMAC_SECRET", "s" * 40)
    monkeypatch.setenv("ATENA_TASKER_GATEWAY_DB", str(tmp_path / "gateway.sqlite3"))
    from api.tasker_command_gateway import app

    body, headers = _signed({"command": "apagar tudo", "device_id": "phone-1"}, "s" * 40, "nonce-unknown")
    assert TestClient(app).post("/v1/tasker/commands", content=body, headers=headers).status_code == 403


def test_x_evidence_maps_official_url():
    from core.x_news_research import XNewsResearch

    # A URL is deterministic and does not require a live API call.
    assert XNewsResearch.endpoint.endswith("/2/tweets/search/recent")
