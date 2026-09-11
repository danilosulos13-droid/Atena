"""Roteador determinístico de tarefas para Android/Tasker.

O módulo não executa ações. Ele transforma linguagem controlada em intenções
estruturadas e bloqueia aplicativos/comandos fora da allowlist.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any


ALLOWED_APPS = {
    "spotify": "com.spotify.music",
    "youtube": "com.google.android.youtube",
    "whatsapp": "com.whatsapp",
    "chrome": "com.android.chrome",
    "câmera": "android.media.action.IMAGE_CAPTURE",
    "camera": "android.media.action.IMAGE_CAPTURE",
}

LOW_RISK_ACTIONS = {
    "android_open_app",
    "android_media_play",
    "android_media_pause",
    "android_media_next",
    "android_media_previous",
    "spotify_search_open",
    "android_status",
}


@dataclass(frozen=True)
class TaskIntent:
    id: str
    action: str
    target: str
    parameters: dict[str, Any]
    risk: str
    requires_confirmation: bool

    def to_tasker_payload(self, device_id: str) -> dict[str, Any]:
        return {
            "command_id": self.id,
            "action": self.action,
            "target": self.target,
            "parameters": self.parameters,
            "device_id": device_id,
        }


def _new(action: str, target: str, parameters: dict[str, Any] | None = None, risk: str = "low") -> TaskIntent:
    return TaskIntent(
        id=f"task-{uuid.uuid4().hex[:18]}",
        action=action,
        target=target,
        parameters=parameters or {},
        risk=risk,
        requires_confirmation=risk != "low",
    )


def parse_task_intent(text: str) -> TaskIntent | None:
    compact = " ".join(text.strip().split())
    lowered = compact.casefold()
    if not compact:
        return None

    if re.search(r"\b(abrir|abra|iniciar|inicie)\s+(o\s+)?spotify\b", lowered):
        return _new("android_open_app", "android", {"package": ALLOWED_APPS["spotify"]})
    if re.search(r"\b(abrir|abra|iniciar|inicie)\s+(o\s+)?(youtube|whatsapp|chrome|câmera|camera)\b", lowered):
        app = next(name for name in ALLOWED_APPS if re.search(rf"\b{name}\b", lowered))
        return _new("android_open_app", "android", {"package": ALLOWED_APPS[app]})

    music = re.match(r"(?:tocar|toque|pesquisar e abrir|pesquise e abra)\s+(.+)$", compact, re.I)
    if music:
        request = re.sub(r"^(?:a\s+)?m[uú]sica\s+", "", music.group(1).strip(), flags=re.I).strip(" .")
        title, separator, artist = request.rpartition(" de ")
        if not separator:
            title, artist = request, ""
        title = title.strip(" .")
        artist = artist.strip(" .")
        return _new("spotify_search_open", "spotify", {"query": " ".join(x for x in (title, artist) if x)})

    media_actions = {
        "pausar mídia": "android_media_pause",
        "pausar musica": "android_media_pause",
        "pausar música": "android_media_pause",
        "retomar música": "android_media_play",
        "retomar musica": "android_media_play",
        "continuar música": "android_media_play",
        "próxima música": "android_media_next",
        "proxima musica": "android_media_next",
        "música anterior": "android_media_previous",
        "musica anterior": "android_media_previous",
    }
    if lowered in media_actions:
        return _new(media_actions[lowered], "android")
    if lowered in {"status do celular", "status android", "consultar bateria", "bateria do celular"}:
        return _new("android_status", "android", {"fields": ["battery", "network", "foreground_app"]})

    call = re.match(r"(?:ligar|fazer ligação para|fazer ligacao para)\s+(.+)$", compact, re.I)
    if call:
        return _new("android_call_contact", "android", {"contact": call.group(1).strip()}, risk="high")

    message = re.match(r"(?:enviar mensagem para|mande mensagem para)\s+(.+?)\s*:\s*(.+)$", compact, re.I)
    if message:
        return _new("android_send_message", "android", {"recipient": message.group(1).strip(), "text": message.group(2).strip()}, risk="high")

    # Outras ações sensíveis ficam classificadas para confirmação, mas não
    # podem ser executadas até existir um executor específico e autorizado.
    if re.search(r"\b(apagar arquivo|instalar aplicativo|comprar|baixar)\b", lowered):
        return _new("android_sensitive_action", "android", {"request": compact}, risk="high")
    return None


def confirmation_prompt(intent: TaskIntent) -> str:
    return f"Esta ação no Android exige confirmação: {intent.action}.\nDetalhes: {intent.parameters}\nResponda CONFIRMAR {intent.id} ou CANCELAR {intent.id}."
