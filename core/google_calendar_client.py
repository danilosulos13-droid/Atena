"""Cliente Google Calendar para a Atena.

A biblioteca é importada sob demanda para manter o bot executável mesmo antes
de instalar as dependências Google. O cliente nunca envia ou modifica eventos
sem que o chamador tenha concluído a confirmação da intenção.
"""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
from typing import Any

READ_SCOPE = "https://www.googleapis.com/auth/calendar.events.readonly"
WRITE_SCOPE = "https://www.googleapis.com/auth/calendar.events"


class GoogleCalendarNotConfigured(RuntimeError):
    """OAuth ou dependências do Google Calendar não estão configurados."""


class GoogleCalendarClient:
    def __init__(
        self,
        credentials_path: str | Path | None = None,
        token_path: str | Path | None = None,
        calendar_id: str | None = None,
    ) -> None:
        root = Path(os.getenv("ATENA_ROOT", Path(__file__).resolve().parents[1]))
        self.credentials_path = Path(credentials_path or os.getenv("ATENA_GOOGLE_CREDENTIALS", root / "secrets" / "google" / "credentials.json"))
        self.token_path = Path(token_path or os.getenv("ATENA_GOOGLE_CALENDAR_TOKEN", root / "secrets" / "google" / "calendar-token.json"))
        self.calendar_id = calendar_id or os.getenv("ATENA_GOOGLE_CALENDAR_ID", "primary")

    def _credentials(self, write: bool = False) -> Any:
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise GoogleCalendarNotConfigured(
                "Dependências ausentes. Instale google-api-python-client, "
                "google-auth-httplib2 e google-auth-oauthlib."
            ) from exc

        scope = WRITE_SCOPE if write else READ_SCOPE
        creds = None
        if self.token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(self.token_path), [scope])
            except (ValueError, OSError):
                creds = None
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not self.credentials_path.exists():
                    raise GoogleCalendarNotConfigured(
                        f"OAuth não configurado: arquivo ausente em {self.credentials_path}"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_path), [scope])
                creds = flow.run_local_server(port=0)
            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            self.token_path.write_text(creds.to_json() + "\n", encoding="utf-8")
            try:
                self.token_path.chmod(0o600)
            except OSError:
                pass
        return creds

    def _service(self, write: bool = False) -> Any:
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise GoogleCalendarNotConfigured(
                "Dependência ausente: google-api-python-client."
            ) from exc
        return build("calendar", "v3", credentials=self._credentials(write), cache_discovery=False)

    def upcoming(self, limit: int = 10) -> list[dict[str, Any]]:
        service = self._service(write=False)
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        response = service.events().list(
            calendarId=self.calendar_id,
            timeMin=now,
            maxResults=max(1, min(int(limit), 50)),
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        return list(response.get("items", []))

    def create_event(self, parameters: dict[str, Any]) -> dict[str, Any]:
        date = str(parameters.get("date", "")).strip()
        time = str(parameters.get("time", "09:00")).strip()
        if not date:
            raise ValueError("o evento precisa de uma data no formato DD/MM/AAAA")
        try:
            start = dt.datetime.fromisoformat(f"{date}T{time}")
        except ValueError as exc:
            raise ValueError("data ou hora inválida; use DD/MM/AAAA e HH:MM") from exc
        end = start + dt.timedelta(minutes=int(parameters.get("duration_minutes", 60)))
        title = str(parameters.get("title") or parameters.get("request") or "Evento Atena").strip()
        body = str(parameters.get("description", "Criado pela Atena após confirmação.")).strip()
        timezone_name = str(parameters.get("timezone") or os.getenv("ATENA_GOOGLE_TIMEZONE", "America/Sao_Paulo"))
        payload = {
            "summary": title,
            "description": body,
            "start": {"dateTime": start.isoformat(), "timeZone": timezone_name},
            "end": {"dateTime": end.isoformat(), "timeZone": timezone_name},
        }
        return self._service(write=True).events().insert(
            calendarId=self.calendar_id,
            body=payload,
        ).execute()


def format_event(event: dict[str, Any]) -> str:
    start = event.get("start", {})
    when = start.get("dateTime") or start.get("date") or "sem horário"
    return f"{when} — {event.get('summary', '(sem título)')}"
