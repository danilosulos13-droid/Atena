from pathlib import Path

from core.google_calendar_client import GoogleCalendarClient, format_event


def test_format_event_supports_datetime_and_all_day():
    assert format_event({"summary": "Reunião", "start": {"dateTime": "2026-08-25T14:30:00"}}) == "2026-08-25T14:30:00 — Reunião"
    assert format_event({"summary": "Feriado", "start": {"date": "2026-09-07"}}) == "2026-09-07 — Feriado"


def test_client_uses_secure_default_paths(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ATENA_ROOT", str(tmp_path))
    client = GoogleCalendarClient()
    assert client.credentials_path == tmp_path / "secrets" / "google" / "credentials.json"
    assert client.token_path == tmp_path / "secrets" / "google" / "calendar-token.json"
    assert client.calendar_id == "primary"
