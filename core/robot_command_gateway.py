"""Gateway seguro para intenções de voz destinadas a robôs.

O módulo separa interpretação de voz, seleção do robô e transporte físico.
Por padrão, nenhum comando real é enviado: ``ATENA_ROBOT_DRY_RUN`` deve ser
explicitamente definido como ``0`` por uma integração validada no servidor.

A camada não presume HTTP, MQTT ou ROS 2. Um adaptador concreto deve
implementar ``RobotTransport`` depois que o fabricante e a API forem
confirmados.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


ROBOT_ACTIONS = {
    "robot_status",
    "robot_stop",
    "robot_start_mission",
    "robot_move_to",
    "robot_close_door",
}

HIGH_RISK_ACTIONS = {
    "robot_start_mission",
    "robot_move_to",
    "robot_close_door",
}

LOCATION_ALIASES = {
    "casa": "casa",
    "em casa": "casa",
    "residência": "casa",
    "residencia": "casa",
    "sítio": "sitio",
    "sitio": "sitio",
    "fazenda": "sitio",
    "no sítio": "sitio",
    "no sitio": "sitio",
}


@dataclass(frozen=True)
class RobotProfile:
    robot_id: str
    location: str
    display_name: str = ""
    transport: str = "unknown"
    capabilities: frozenset[str] = frozenset()
    enabled: bool = True


@dataclass(frozen=True)
class RobotIntent:
    action: str
    location: str | None
    parameters: dict[str, Any] = field(default_factory=dict)
    risk: str = "low"
    requires_confirmation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "location": self.location,
            "parameters": self.parameters,
            "risk": self.risk,
            "requires_confirmation": self.requires_confirmation,
        }


@dataclass(frozen=True)
class RobotCommand:
    command_id: str
    robot_id: str
    location: str
    action: str
    parameters: dict[str, Any]
    risk: str
    requires_confirmation: bool
    expires_at: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "robot_id": self.robot_id,
            "location": self.location,
            "action": self.action,
            "parameters": self.parameters,
            "risk": self.risk,
            "requires_confirmation": self.requires_confirmation,
            "expires_at": self.expires_at,
        }


class RobotTransport(Protocol):
    def send(self, profile: RobotProfile, command: RobotCommand) -> dict[str, Any]:
        """Enviar um comando já validado ao adaptador do fabricante."""


class SimulatedRobotTransport:
    """Transporte de teste que nunca acessa a rede nem altera dispositivos."""

    def send(self, profile: RobotProfile, command: RobotCommand) -> dict[str, Any]:
        return {
            "simulated": True,
            "robot_id": profile.robot_id,
            "location": profile.location,
            "action": command.action,
            "device_state_changed": False,
        }


def _normalize(text: str) -> str:
    return " ".join(str(text).strip().casefold().split())


def _location_from_text(text: str) -> str | None:
    normalized = _normalize(text)
    for alias, location in sorted(LOCATION_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if alias in normalized:
            return location
    return None


def parse_robot_voice_intent(text: str) -> RobotIntent | None:
    """Converte frases controladas em intenções, sem executar nada."""
    compact = _normalize(text)
    if not compact:
        return None
    location = _location_from_text(compact)

    if re.search(r"\b(parar|pare|emergência|emergencia|stop)\b", compact):
        return RobotIntent("robot_stop", location, risk="critical")
    if re.search(r"\b(status|situação|situacao|estado)\b", compact) and re.search(r"\brobô|robo\b", compact):
        return RobotIntent("robot_status", location)
    if re.search(r"\b(fechar|feche|fecha)\b", compact) and re.search(r"\b(porta|portão|portao)\b", compact):
        return RobotIntent("robot_close_door", location, risk="high", requires_confirmation=True)
    if re.search(r"\b(iniciar|inicie|começar|comecar|execute|executar)\b", compact) and re.search(r"\b(missão|missao|patrulha)\b", compact):
        return RobotIntent("robot_start_mission", location, risk="high", requires_confirmation=True)
    move = re.search(r"\b(?:ir|vá|va|mover|mova)\s+(?:para|até|ate)\s+(.+)$", compact)
    if move and re.search(r"\brobô|robo\b", compact):
        destination = move.group(1).strip(" .")
        return RobotIntent(
            "robot_move_to",
            location,
            {"destination": destination[:120]},
            risk="high",
            requires_confirmation=True,
        )
    return None


def load_registry(path: str | Path | None = None) -> list[RobotProfile]:
    """Carrega perfis sem descobrir nem comandar a rede."""
    registry_path = Path(path or os.getenv("ATENA_ROBOT_REGISTRY", ""))
    if not str(registry_path):
        return []
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("robots", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    profiles: list[RobotProfile] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        robot_id = str(row.get("robot_id", "")).strip()
        location = _normalize(str(row.get("location", "")))
        if not robot_id or not location:
            continue
        capabilities = row.get("capabilities", [])
        if isinstance(capabilities, str):
            capabilities = [capabilities]
        profiles.append(
            RobotProfile(
                robot_id=robot_id[:120],
                location=location[:80],
                display_name=str(row.get("display_name", ""))[:120],
                transport=str(row.get("transport", "unknown"))[:40],
                capabilities=frozenset(str(item) for item in capabilities if item),
                enabled=bool(row.get("enabled", True)),
            )
        )
    return profiles


class RobotCommandGateway:
    """Valida, roteia e registra comandos; o transporte é injetado."""

    def __init__(
        self,
        profiles: list[RobotProfile],
        transport: RobotTransport | None = None,
        ledger_path: str | Path | None = None,
        dry_run: bool | None = None,
        command_ttl_seconds: int = 15,
    ) -> None:
        self.profiles = tuple(profiles)
        self.transport = transport or SimulatedRobotTransport()
        self.dry_run = (os.getenv("ATENA_ROBOT_DRY_RUN", "1") != "0") if dry_run is None else dry_run
        self.command_ttl_seconds = max(1, min(int(command_ttl_seconds), 300))
        self.ledger_path = Path(ledger_path or os.getenv("ATENA_ROBOT_LEDGER", "atena_evolution/robot_commands.sqlite3"))
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.ledger_path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS robot_commands (command_id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE, robot_id TEXT NOT NULL, action TEXT NOT NULL, status TEXT NOT NULL, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, result_json TEXT)"
            )
            connection.commit()

    def resolve(self, intent: RobotIntent) -> RobotProfile:
        candidates = [p for p in self.profiles if p.enabled and (not intent.location or p.location == intent.location)]
        if not candidates:
            raise ValueError("nenhum robô habilitado corresponde ao local informado")
        if len(candidates) > 1 and not intent.location:
            raise ValueError("mais de um robô disponível; informe casa ou sítio")
        return candidates[0]

    def build_command(self, intent: RobotIntent, now: int | None = None) -> RobotCommand:
        if intent.action not in ROBOT_ACTIONS:
            raise ValueError("ação de robô fora da allowlist")
        profile = self.resolve(intent)
        timestamp = int(time.time()) if now is None else int(now)
        if intent.action == "robot_move_to" and not str(intent.parameters.get("destination", "")).strip():
            raise ValueError("destino obrigatório para movimento")
        return RobotCommand(
            command_id=f"robot-{uuid.uuid4().hex[:18]}",
            robot_id=profile.robot_id,
            location=profile.location,
            action=intent.action,
            parameters=dict(intent.parameters),
            risk=intent.risk,
            requires_confirmation=intent.requires_confirmation,
            expires_at=timestamp + self.command_ttl_seconds,
        )

    def dispatch(self, command: RobotCommand, *, approved: bool = False, now: int | None = None) -> dict[str, Any]:
        current = int(time.time()) if now is None else int(now)
        if command.expires_at < current:
            return {"ok": False, "status": "expired", "command_id": command.command_id}
        if command.requires_confirmation and not approved:
            return {"ok": False, "status": "approval_required", "command_id": command.command_id}
        profile = next((item for item in self.profiles if item.robot_id == command.robot_id and item.enabled), None)
        if profile is None:
            return {"ok": False, "status": "robot_unavailable", "command_id": command.command_id}
        fingerprint = hashlib.sha256(json.dumps(command.to_dict(), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with sqlite3.connect(self.ledger_path) as connection:
            try:
                connection.execute(
                    "INSERT INTO robot_commands(command_id, fingerprint, robot_id, action, status, created_at, expires_at) VALUES (?, ?, ?, ?, 'queued', ?, ?)",
                    (command.command_id, fingerprint, command.robot_id, command.action, current, command.expires_at),
                )
                connection.commit()
            except sqlite3.IntegrityError:
                return {"ok": False, "status": "duplicate", "command_id": command.command_id}
        if self.dry_run:
            result = {"simulated": True, "device_state_changed": False}
        else:
            result = self.transport.send(profile, command)
        with sqlite3.connect(self.ledger_path) as connection:
            connection.execute(
                "UPDATE robot_commands SET status=?, result_json=? WHERE command_id=?",
                ("simulated" if self.dry_run else "sent", json.dumps(result, ensure_ascii=False), command.command_id),
            )
            connection.commit()
        return {"ok": True, "status": "simulated" if self.dry_run else "sent", "command_id": command.command_id, "result": result}

    def watchdog(self, now: int | None = None) -> dict[str, Any]:
        current = int(time.time()) if now is None else int(now)
        with sqlite3.connect(self.ledger_path) as connection:
            updated = connection.execute(
                "UPDATE robot_commands SET status='expired' WHERE status='queued' AND expires_at < ?",
                (current,),
            ).rowcount
            connection.commit()
        return {"expired_commands": int(updated), "checked_at": current, "safe_state": True}


__all__ = [
    "HIGH_RISK_ACTIONS",
    "ROBOT_ACTIONS",
    "RobotCommand",
    "RobotCommandGateway",
    "RobotIntent",
    "RobotProfile",
    "RobotTransport",
    "SimulatedRobotTransport",
    "load_registry",
    "parse_robot_voice_intent",
]
