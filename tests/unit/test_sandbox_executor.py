from pathlib import Path

import pytest

from core.executors.sandbox import RootlessContainerTestExecutor, SandboxedTestExecutor
from core.executors.factory import build_production_broker
from core.tool_contracts import ToolCall


def make_workspace(tmp_path: Path, body: str) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / "tests" / "unit").mkdir(parents=True)
    (workspace / "tests" / "unit" / "test_sample.py").write_text(body, encoding="utf-8")
    return workspace


def test_sandbox_executor_runs_in_copy_and_returns_evidence(tmp_path: Path):
    workspace = make_workspace(tmp_path, "def test_ok():\n    assert 1 + 1 == 2\n")
    result = SandboxedTestExecutor(workspace, memory_mb=256)({"target": "tests/unit", "timeout_seconds": 10})
    assert result["passed"] is True
    assert result["returncode"] == 0
    assert result["isolation"]["filesystem"] == "temporary_copy"
    assert result["isolation"]["network"] == "not_isolated_by_executor"
    assert result["evidence"]


def test_sandbox_executor_reports_test_failure(tmp_path: Path):
    workspace = make_workspace(tmp_path, "def test_bad():\n    assert False\n")
    result = SandboxedTestExecutor(workspace, memory_mb=256)({"target": "tests/unit", "timeout_seconds": 10})
    assert result["passed"] is False
    assert result["returncode"] != 0
    assert "failed" in result["stdout"].lower() or "failed" in result["stderr"].lower()


def test_sandbox_executor_rejects_path_escape(tmp_path: Path):
    workspace = make_workspace(tmp_path, "def test_ok():\n    pass\n")
    executor = SandboxedTestExecutor(workspace)
    with pytest.raises(ValueError, match="fora do workspace"):
        executor({"target": "../../etc", "timeout_seconds": 1})


def test_sandbox_executor_times_out_and_kills_process_group(tmp_path: Path):
    workspace = make_workspace(tmp_path, "import time\ndef test_slow():\n    time.sleep(5)\n")
    result = SandboxedTestExecutor(workspace, max_timeout_seconds=2, memory_mb=256)({"target": "tests/unit", "timeout_seconds": 1})
    assert result["passed"] is False
    assert result["timed_out"] is True
    assert result["returncode"] == 124


def test_factory_binds_real_sandbox_executor_when_workspace_is_explicit(tmp_path: Path):
    workspace = make_workspace(tmp_path, "def test_ok():\n    assert True\n")
    broker = build_production_broker(tmp_path / "memory.sqlite3", workspace=workspace)
    result = broker.dispatch(ToolCall(
        tool_call_id="sandbox-test",
        name="code.run_tests",
        arguments={"target": "tests/unit", "timeout_seconds": 10},
        purpose="teste de integração",
    ))
    assert result.status == "executed"
    assert result.result["passed"] is True
    assert result.result["isolation"]["filesystem"] == "temporary_copy"


def test_rootless_executor_builds_hardened_command_without_shell(tmp_path: Path, monkeypatch):
    workspace = make_workspace(tmp_path, "def test_ok():\n    assert True\n")
    captured = {}

    class Completed:
        returncode = 0
        stdout = "1 passed"
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return Completed()

    monkeypatch.setattr("core.executors.sandbox.subprocess.run", fake_run)
    result = RootlessContainerTestExecutor(workspace)( {"target": "tests/unit", "timeout_seconds": 5} )
    command = captured["command"]
    assert result["passed"] is True
    assert "--network=none" in command
    assert "--read-only" in command
    assert "--cap-drop=ALL" in command
    assert "--security-opt=no-new-privileges:true" in command
    assert "--pids-limit=64" in command
    assert "--memory=512m" in command
    assert "--memory-swap=512m" in command
    assert "--user=65532:65532" in command
    assert captured["kwargs"].get("shell", False) is False


def test_rootless_executor_rejects_non_podman_runtime(tmp_path: Path):
    workspace = make_workspace(tmp_path, "def test_ok():\n    pass\n")
    with pytest.raises(ValueError, match="Podman"):
        RootlessContainerTestExecutor(workspace, runtime="docker")


def test_factory_selects_rootless_executor_in_container_mode(tmp_path: Path, monkeypatch):
    workspace = make_workspace(tmp_path, "def test_ok():\n    pass\n")
    monkeypatch.setenv("ATENA_SANDBOX_MODE", "container")
    broker = build_production_broker(tmp_path / "memory.sqlite3", workspace=workspace)
    assert "run_tests_rootless" in broker.executors
    assert broker.policies["code.run_tests"].executor_name == "run_tests_rootless"


def test_factory_selects_process_executor_in_process_mode(tmp_path: Path, monkeypatch):
    workspace = make_workspace(tmp_path, "def test_ok():\n    pass\n")
    monkeypatch.setenv("ATENA_SANDBOX_MODE", "process")
    broker = build_production_broker(tmp_path / "memory.sqlite3", workspace=workspace)
    assert "run_tests_sandbox" in broker.executors
    assert broker.policies["code.run_tests"].executor_name == "run_tests_sandbox"


def test_factory_rejects_invalid_sandbox_mode(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ATENA_SANDBOX_MODE", "unsafe")
    with pytest.raises(ValueError, match="process.*container"):
        build_production_broker(tmp_path / "memory.sqlite3", workspace=tmp_path)


def test_factory_fails_closed_without_workspace_in_container_mode(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ATENA_SANDBOX_MODE", "container")
    monkeypatch.delenv("ATENA_SANDBOX_WORKSPACE", raising=False)
    with pytest.raises(ValueError, match="workspace explícito"):
        build_production_broker(tmp_path / "memory.sqlite3")
