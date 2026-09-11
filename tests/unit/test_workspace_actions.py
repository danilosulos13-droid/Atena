from core.workspace_actions import (
    confirmation_prompt,
    is_cancellation,
    is_confirmation,
    parse_workspace_intent,
)


def test_agendar_requires_confirmation_and_parses_google_provider():
    intent = parse_workspace_intent(123, "/agendar reunião da empresa em 25/08/2026 às 14:30 no Google Calendar")
    assert intent is not None
    assert intent.action == "calendar_create"
    assert intent.provider == "google"
    assert intent.requires_confirmation is True
    assert intent.parameters["title"] == "reunião da empresa"
    assert intent.parameters["date"] == "2026-08-25"
    assert intent.parameters["time"] == "14:30"
    assert "CONFIRMAR" in confirmation_prompt(intent)


def test_read_commands_do_not_require_confirmation():
    intent = parse_workspace_intent("chat", "/agenda outlook")
    assert intent is not None
    assert intent.action == "calendar_list"
    assert intent.provider == "microsoft"
    assert intent.requires_confirmation is False


def test_spreadsheet_write_requires_confirmation():
    intent = parse_workspace_intent("chat", "criar planilha Ganhos 2026")
    assert intent is not None
    assert intent.action == "spreadsheet_create"
    assert intent.parameters["title"] == "Ganhos 2026"
    assert intent.requires_confirmation is True
    assert is_confirmation(f"CONFIRMAR {intent.id}", intent.id)
    assert is_cancellation(f"CANCELAR {intent.id}", intent.id)


def test_free_text_does_not_become_device_or_workspace_action():
    assert parse_workspace_intent("chat", "explique como funciona uma planilha") is None
