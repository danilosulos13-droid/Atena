"""Auditoria de comandos da Atena em uma planilha Google Sheets."""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
from typing import Any

READ_WRITE_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


class GoogleSheetsNotConfigured(RuntimeError):
    pass


class GoogleSheetsAudit:
    def __init__(self, spreadsheet_id: str | None = None, range_name: str | None = None) -> None:
        root = Path(os.getenv("ATENA_ROOT", Path(__file__).resolve().parents[1]))
        self.spreadsheet_id = spreadsheet_id or os.getenv("ATENA_AUDIT_SHEET_ID", "").strip()
        self.range_name = range_name or os.getenv("ATENA_AUDIT_SHEET_RANGE", "Comandos!A:H")
        self.credentials_path = Path(os.getenv("ATENA_GOOGLE_CREDENTIALS", root / "secrets" / "google" / "credentials.json"))
        self.token_path = Path(os.getenv("ATENA_GOOGLE_SHEETS_TOKEN", root / "secrets" / "google" / "sheets-token.json"))

    def _service(self) -> Any:
        if not self.spreadsheet_id:
            raise GoogleSheetsNotConfigured("ATENA_AUDIT_SHEET_ID não configurado")
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise GoogleSheetsNotConfigured("dependências Google Sheets ausentes") from exc
        creds = None
        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_path), [READ_WRITE_SCOPE])
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not self.credentials_path.exists():
                    raise GoogleSheetsNotConfigured(f"OAuth ausente: {self.credentials_path}")
                flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_path), [READ_WRITE_SCOPE])
                creds = flow.run_local_server(port=0)
            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            self.token_path.write_text(creds.to_json() + "\n", encoding="utf-8")
            try:
                self.token_path.chmod(0o600)
            except OSError:
                pass
        return build("sheets", "v4", credentials=creds, cache_discovery=False)

    def append_command(self, *, command: str, device_id: str, accepted: bool, source: str, intent: str = "device_command", details: str = "") -> dict[str, Any]:
        values = [[
            dt.datetime.now(dt.timezone.utc).isoformat(),
            device_id,
            command,
            "accepted" if accepted else "rejected",
            source,
            intent,
            details[:500],
            os.getenv("GITHUB_SHA", "local"),
        ]]
        return self._service().spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range=self.range_name,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        ).execute()
