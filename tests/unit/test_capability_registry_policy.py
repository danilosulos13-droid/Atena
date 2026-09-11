import pytest

from core.capability_registry import run_capability


def test_capability_execution_requires_explicit_allowlist(monkeypatch):
    monkeypatch.delenv("ATENA_CAPABILITY_ALLOWLIST", raising=False)
    with pytest.raises(PermissionError, match="bloqueada"):
        run_capability("hydra_protocol")


def test_capability_allowlist_rejects_unknown_module(monkeypatch):
    monkeypatch.setenv("ATENA_CAPABILITY_ALLOWLIST", "hydra_protocol")
    with pytest.raises(KeyError):
        run_capability("module_that_does_not_exist")
