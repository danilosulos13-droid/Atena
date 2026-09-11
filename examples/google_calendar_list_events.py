#!/usr/bin/env python3
"""Lista os próximos eventos do Google Calendar via OAuth desktop.

Pré-requisitos:
  pip install --upgrade google-api-python-client google-auth-httplib2 google-auth-oauthlib

Coloque o JSON baixado em Google Cloud como credentials.json no diretório do
script. A primeira execução abre o navegador para consentimento e grava
token.json localmente. Nunca versionar credentials.json ou token.json.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/calendar.events.readonly"]


def load_credentials(credentials_path: Path, token_path: Path) -> Credentials:
    creds: Credentials | None = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not credentials_path.exists():
                raise FileNotFoundError(
                    f"Credenciais não encontradas: {credentials_path}. "
                    "Baixe o OAuth Client ID desktop no Google Cloud."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json() + "\n", encoding="utf-8")
    return creds


def list_upcoming_events(
    credentials_path: Path,
    token_path: Path,
    calendar_id: str = "primary",
    limit: int = 10,
) -> list[dict[str, Any]]:
    creds = load_credentials(credentials_path, token_path)
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    response = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=now,
            maxResults=max(1, min(limit, 50)),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    return response.get("items", [])


def event_start(event: dict[str, Any]) -> str:
    start = event.get("start", {})
    return str(start.get("dateTime") or start.get("date") or "sem horário")


def main() -> int:
    parser = argparse.ArgumentParser(description="Lista próximos eventos do Google Calendar")
    parser.add_argument("--credentials", type=Path, default=Path("credentials.json"))
    parser.add_argument("--token", type=Path, default=Path("token.json"))
    parser.add_argument("--calendar-id", default="primary")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    try:
        events = list_upcoming_events(
            args.credentials, args.token, args.calendar_id, args.limit
        )
    except HttpError as exc:
        print(f"Erro HTTP da API Calendar: {exc}")
        return 2
    except Exception as exc:
        print(f"Não foi possível autenticar ou consultar o Calendar: {type(exc).__name__}: {exc}")
        return 2

    if args.as_json:
        print(json.dumps(events, ensure_ascii=False, indent=2))
        return 0

    if not events:
        print("Nenhum evento futuro encontrado.")
        return 0

    print(f"Próximos eventos ({len(events)}):")
    for event in events:
        title = event.get("summary", "(sem título)")
        print(f"- {event_start(event)} — {title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
