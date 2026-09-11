import hashlib
import hmac
import json
import time

from fastapi.testclient import TestClient


def signed(payload: dict, secret: str, nonce: str):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    message = f"{timestamp}.{nonce}.".encode() + body
    signature = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return body, {
        "Content-Type": "application/json",
        "X-Atena-Timestamp": timestamp,
        "X-Atena-Nonce": nonce,
        "X-Atena-Signature": signature,
    }


def test_parse_spotify_track():
    from core.universal_task_router import parse_task_intent

    intent = parse_task_intent("tocar Evidências de um Rapaz de Fresno")
    assert intent is not None
    assert intent.action == "spotify_search_open"
    assert intent.parameters["query"] == "Evidências de um Rapaz Fresno"
    assert intent.requires_confirmation is False


def test_parse_sensitive_actions_require_confirmation():
    from core.universal_task_router import parse_task_intent

    call = parse_task_intent("ligar para Danilo")
    assert call is not None
    assert call.action == "android_call_contact"
    assert call.requires_confirmation is True

    message = parse_task_intent("enviar mensagem para Danilo: Cheguei em casa")
    assert message is not None
    assert message.action == "android_send_message"
    assert message.requires_confirmation is True


def test_parse_media_pause():
    from core.universal_task_router import parse_task_intent

    intent = parse_task_intent("pausar mídia")
    assert intent is not None
    assert intent.action == "android_media_pause"


def test_gateway_rejects_sensitive_dispatch_without_approval(monkeypatch, tmp_path):
    secret = "t" * 40
    monkeypatch.setenv("ATENA_TASKER_HMAC_SECRET", secret)
    monkeypatch.setenv("ATENA_TASKER_GATEWAY_DB", str(tmp_path / "gateway.sqlite3"))
    import api.tasker_command_gateway as gateway
    gateway.DB_PATH = tmp_path / "gateway.sqlite3"
    client = TestClient(gateway.app)
    payload = {"command_id": "task-sensitive-1", "device_id": "android-principal", "action": "android_call_contact", "target": "android", "parameters": {"contact": "Danilo"}}
    body, headers = signed(payload, secret, "nonce-sensitive-1")
    response = client.post("/v1/tasker/dispatch", content=body, headers=headers)
    assert response.status_code == 428


def test_gateway_dispatch_claim_and_complete(monkeypatch, tmp_path):
    secret = "t" * 40
    monkeypatch.setenv("ATENA_TASKER_HMAC_SECRET", secret)
    monkeypatch.setenv("ATENA_TASKER_GATEWAY_DB", str(tmp_path / "gateway.sqlite3"))
    import api.tasker_command_gateway as gateway
    gateway.DB_PATH = tmp_path / "gateway.sqlite3"
    client = TestClient(gateway.app)
    payload = {
        "command_id": "task-test-123456",
        "device_id": "android-principal",
        "action": "spotify_search_open",
        "target": "spotify",
        "parameters": {"query": "Fresno"},
    }
    body, headers = signed(payload, secret, "nonce-dispatch-1")
    response = client.post("/v1/tasker/dispatch", content=body, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "queued"

    claim_payload = {"device_id": "android-principal"}
    body, headers = signed(claim_payload, secret, "nonce-claim-1")
    response = client.post("/v1/tasker/next", content=body, headers=headers)
    assert response.status_code == 200
    assert response.json()["task"]["action"] == "spotify_search_open"

    result_payload = {"command_id": "task-test-123456", "device_id": "android-principal", "ok": True, "result": {"opened": True}}
    body, headers = signed(result_payload, secret, "nonce-result-1")
    response = client.post("/v1/tasker/result", content=body, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
