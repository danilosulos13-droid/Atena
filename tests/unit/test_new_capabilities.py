from pathlib import Path

import pytest

from core.code_sandbox import PythonSandbox, SandboxError
from core.home_assistant_gateway import HomeAssistantError, HomeAssistantGateway
from core.vision_analysis import VisionAnalysisError


def test_sandbox_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ATENA_SANDBOX_ENABLED", raising=False)
    with pytest.raises(SandboxError):
        PythonSandbox().run("print(1)", approved=True)


def test_sandbox_requires_explicit_approval(monkeypatch):
    monkeypatch.setenv("ATENA_SANDBOX_ENABLED", "1")
    with pytest.raises(SandboxError, match="confirmação"):
        PythonSandbox().run("print(1)")


def test_home_assistant_requires_confirmation():
    gateway = HomeAssistantGateway(base_url="http://ha.local", token="secret", dry_run=True)
    with pytest.raises(HomeAssistantError, match="confirmação"):
        gateway.call_service("light", "turn_on", entity_id="light.office")


def test_home_assistant_dry_run_is_allowlisted():
    gateway = HomeAssistantGateway(base_url="http://ha.local", token="secret", dry_run=True)
    result = gateway.call_service("light", "turn_on", entity_id="light.office", approved=True)
    assert result["status"] == "simulated"


def test_vision_rejects_missing_image():
    with pytest.raises(VisionAnalysisError):
        from core.vision_analysis import analyze_image
        analyze_image(Path("/tmp/does-not-exist.png"), "descreva")
