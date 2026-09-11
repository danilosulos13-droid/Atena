from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_root_dashboard() -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "ATENA" in resp.text


def test_healthz() -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in ("healthy", "degraded")
    assert "version" in body


def test_status_payload() -> None:
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "online"
