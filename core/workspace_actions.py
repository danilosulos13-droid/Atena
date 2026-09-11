"""Ações autorizáveis de planilhas e calendários para a Atena.

Este módulo não contém credenciais nem chama APIs externas. Ele transforma uma
mensagem do usuário em uma intenção estruturada e aplica uma política de
confirmação antes de qualquer criação, edição ou cancelamento.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class WorkspaceIntent:
    id: str
    chat_id: str
    action: str
    provider: str
    parameters: dict[str, Any]
    risk: str
    requires_confirmation: bool
    status: str = "pending_confirmation"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


READ_ACTIONS = {"calendar_list", "calendar_availability", "spreadsheet_read", "spreadsheet_analyze"}
WRITE_ACTIONS = {"calendar_create", "calendar_update", "calendar_cancel", "spreadsheet_create", "spreadsheet_write"}
ALLOWED_PROVIDERS = {"google", "microsoft", "auto"}


def _compact(value: str) -> str:
    return " ".join(str(value).strip().split())


def _provider(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("outlook", "microsoft", "office 365", "microsoft 365", "teams")):
        return "microsoft"
    if any(token in lowered for token in ("gmail", "google", "planilhas google", "google sheets", "google calendar")):
        return "google"
    return "auto"


def _event_parameters(text: str) -> dict[str, Any]:
    compact = _compact(text)
    result: dict[str, Any] = {"request": compact}
    title = re.sub(r"^(?:/)?agendar\s*", "", compact, flags=re.I)
    title = re.split(r"\s+(?:em|no dia|às|as|at)\s+", title, maxsplit=1, flags=re.I)[0].strip()
    if title:
        result["title"] = title
    time_match = re.search(r"\b(?:às|as|at)\s+(\d{1,2})(?::(\d{2}))?\b", compact, re.I)
    if time_match:
        result["time"] = f"{int(time_match.group(1)):02d}:{time_match.group(2) or '00'}"
    date_match = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", compact)
    if date_match:
        year = int(date_match.group(3) or datetime.now().year)
        if year < 100:
            year += 2000
        result["date"] = f"{year:04d}-{int(date_match.group(2)):02d}-{int(date_match.group(1)):02d}"
    return result


def parse_workspace_intent(chat_id: int | str, text: str) -> WorkspaceIntent | None:
    """Converte comandos explícitos em intenções; texto livre não executa ações."""
    compact = _compact(text)
    lowered = compact.lower()
    if not compact:
        return None
    provider = _provider(lowered)
    action: str | None = None
    parameters: dict[str, Any] = {"request": compact}

    if lowered.startswith("/agendar ") or lowered.startswith("agendar "):
        action = "calendar_create"
        parameters = _event_parameters(compact)
    elif lowered.startswith("/agenda") or lowered in {"ver agenda", "consultar agenda"}:
        action = "calendar_list"
    elif lowered.startswith("/cancelar evento") or lowered.startswith("cancelar evento"):
        action = "calendar_cancel"
        parameters = _event_parameters(compact)
    elif lowered.startswith("/criar planilha") or lowered.startswith("criar planilha"):
        action = "spreadsheet_create"
        parameters = {"request": compact, "title": re.sub(r"^(?:/)?criar planilha\s*", "", compact, flags=re.I).strip()}
    elif lowered.startswith("/preencher planilha") or lowered.startswith("preencher planilha"):
        action = "spreadsheet_write"
        parameters = {"request": compact}
    elif lowered.startswith("/analisar planilha") or lowered.startswith("analisar planilha"):
        action = "spreadsheet_analyze"
        parameters = {"request": compact}
    else:
        return None

    requires_confirmation = action in WRITE_ACTIONS
    risk = "write" if requires_confirmation else "read"
    return WorkspaceIntent(
        id=f"workspace-{uuid.uuid4().hex[:16]}",
        chat_id=str(chat_id),
        action=action,
        provider=provider if provider in ALLOWED_PROVIDERS else "auto",
        parameters=parameters,
        risk=risk,
        requires_confirmation=requires_confirmation,
    )


def confirmation_prompt(intent: WorkspaceIntent) -> str:
    if not intent.requires_confirmation:
        return ""
    action_labels = {
        "calendar_create": "criar este evento no calendário",
        "calendar_update": "alterar este evento no calendário",
        "calendar_cancel": "cancelar este evento no calendário",
        "spreadsheet_create": "criar esta planilha",
        "spreadsheet_write": "alterar esta planilha",
    }
    label = action_labels.get(intent.action, intent.action)
    provider = "Google" if intent.provider == "google" else "Microsoft" if intent.provider == "microsoft" else "provedor configurado"
    details = json.dumps(intent.parameters, ensure_ascii=False, sort_keys=True)
    return f"Confirma que devo {label} usando {provider}?\nDetalhes: {details}\nResponda CONFIRMAR {intent.id} ou CANCELAR {intent.id}."


def confirmation_token(intent: WorkspaceIntent) -> str:
    payload = f"{intent.id}|{intent.chat_id}|{intent.action}|{json.dumps(intent.parameters, sort_keys=True, ensure_ascii=False)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def is_confirmation(text: str, intent_id: str) -> bool:
    return _compact(text).lower() == f"confirmar {intent_id}".lower()


def is_cancellation(text: str, intent_id: str) -> bool:
    return _compact(text).lower() == f"cancelar {intent_id}".lower()
