"""Gateway mínimo e seguro para Home Assistant REST API."""
from __future__ import annotations

import os
from typing import Any

import requests


class HomeAssistantError(RuntimeError):
    pass


class HomeAssistantGateway:
    def __init__(self, *, base_url: str | None = None, token: str | None = None, dry_run: bool | None = None) -> None:
        self.base_url = (base_url or os.getenv("ATENA_HOME_ASSISTANT_URL", "")).rstrip("/")
        self.token = token or os.getenv("ATENA_HOME_ASSISTANT_TOKEN", "")
        self.dry_run = os.getenv("ATENA_HOME_ASSISTANT_DRY_RUN", "1") != "0" if dry_run is None else dry_run

    def _headers(self) -> dict[str, str]:
        if not self.base_url or not self.token:
            raise HomeAssistantError("Home Assistant não configurado")
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def states(self, entity_id: str | None = None) -> Any:
        if entity_id and (" " in entity_id or len(entity_id) > 200):
            raise HomeAssistantError("entity_id inválido")
        suffix = f"/api/states/{entity_id}" if entity_id else "/api/states"
        try:
            response = requests.get(self.base_url + suffix, headers=self._headers(), timeout=15)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            raise HomeAssistantError(f"falha ao consultar Home Assistant: {type(exc).__name__}") from exc

    def call_service(self, domain: str, service: str, *, entity_id: str, data: dict[str, Any] | None = None, approved: bool = False) -> dict[str, Any]:
        if not domain.isidentifier() or not service.isidentifier() or not entity_id.startswith(("light.", "switch.", "climate.", "media_player.")):
            raise HomeAssistantError("serviço ou entidade fora da allowlist")
        if not approved:
            raise HomeAssistantError("ação física exige confirmação explícita")
        if self.dry_run:
            return {"status": "simulated", "domain": domain, "service": service, "entity_id": entity_id}
        try:
            response = requests.post(self.base_url + f"/api/services/{domain}/{service}", headers=self._headers(), json={"entity_id": entity_id, **(data or {})}, timeout=15)
            response.raise_for_status()
            return {"status": "sent", "result": response.json()}
        except (requests.RequestException, ValueError) as exc:
            raise HomeAssistantError(f"falha ao chamar serviço Home Assistant: {type(exc).__name__}") from exc
