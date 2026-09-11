"""Executor de testes em cópia temporária e com limites de recursos.

Este executor reduz o impacto do código testado, mas não substitui isolamento de
container/VM: a política de rede do processo precisa ser fornecida pelo ambiente
externo quando código não confiável for executado.
"""
from __future__ import annotations

import os
import re
import shutil
import signal
import site
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

try:
    import resource
except ImportError:  # pragma: no cover - plataformas não POSIX
    resource = None  # type: ignore[assignment]


class SandboxedTestExecutor:
    """Executa pytest em workspace descartável, sem shell e com limites."""

    def __init__(
        self,
        workspace: str | Path,
        *,
        max_timeout_seconds: int = 30,
        memory_mb: int = 512,
        max_file_size_mb: int = 32,
        max_processes: int = 64,
        max_output_chars: int = 12_000,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        if not self.workspace.is_dir():
            raise ValueError("workspace de testes não existe ou não é diretório")
        self.max_timeout_seconds = max(1, min(max_timeout_seconds, 300))
        self.memory_bytes = max(64, memory_mb) * 1024 * 1024
        self.max_file_size_bytes = max(1, max_file_size_mb) * 1024 * 1024
        self.max_processes = max(1, max_processes)
        self.max_output_chars = max(1_000, max_output_chars)

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        target = self._safe_target(str(arguments.get("target", "")))
        timeout = max(1, min(int(arguments.get("timeout_seconds", 10)), self.max_timeout_seconds))
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="atena-test-workspace-") as temporary:
            temp_root = Path(temporary)
            self._copy_workspace(temp_root)
            command = [sys.executable, "-m", "pytest", target, "-q", "--disable-warnings"]
            process = subprocess.Popen(
                command,
                cwd=temp_root,
                env=self._clean_environment(temp_root),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
                preexec_fn=self._limits if os.name == "posix" else None,
            )
            timed_out = False
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                self._terminate_group(process)
                stdout, stderr = process.communicate()
                stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
                stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
                stderr += "\n[timeout] limite de execução excedido"

        return {
            "target": target,
            "passed": process.returncode == 0 and not timed_out,
            "returncode": 124 if timed_out else process.returncode,
            "timed_out": timed_out,
            "stdout": self._truncate(stdout),
            "stderr": self._truncate(stderr),
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "isolation": {
                "filesystem": "temporary_copy",
                "memory_mb": self.memory_bytes // (1024 * 1024),
                "max_file_size_mb": self.max_file_size_bytes // (1024 * 1024),
                "max_processes": self.max_processes,
                "network": "not_isolated_by_executor",
            },
            "evidence": [f"test://sandbox/{target}"],
        }

    def _safe_target(self, target: str) -> str:
        if not target or target.startswith("-") or "\x00" in target:
            raise ValueError("target de teste inválido")
        candidate = (self.workspace / target).resolve()
        try:
            candidate.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("target fora do workspace") from exc
        if not candidate.exists():
            raise FileNotFoundError(f"target de teste não existe: {target}")
        return candidate.relative_to(self.workspace).as_posix()

    def _copy_workspace(self, destination: Path) -> None:
        ignored = shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".venv", "venv", "*.sqlite", "*.sqlite3", "*.db")
        for child in self.workspace.iterdir():
            target = destination / child.name
            if child.is_dir():
                shutil.copytree(child, target, ignore=ignored, symlinks=False)
            elif child.is_file():
                shutil.copy2(child, target)

    def _clean_environment(self, temp_root: Path) -> dict[str, str]:
        blocked = re.compile(r"(TOKEN|KEY|SECRET|PASSWORD|CREDENTIAL|PRIVATE)", re.I)
        env = {
            "PATH": os.environ.get("PATH", os.defpath),
            "HOME": str(temp_root / ".home"),
            "PYTHONPATH": os.pathsep.join((str(temp_root), site.getusersitepackages())),
            "PYTHONDONTWRITEBYTECODE": "1",
            "CI": "1",
            "NO_COLOR": "1",
        }
        env["HOME"] = str(temp_root / ".home")
        Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
        # Nenhum segredo do processo pai é herdado.
        for key, value in os.environ.items():
            if key in {"PATH", "HOME", "PYTHONPATH"} or blocked.search(key):
                continue
            if key.startswith("ATENA_") or key.startswith("GITHUB_"):
                continue
            if key in {"LANG", "LC_ALL", "TMPDIR"}:
                env[key] = value
        return env

    def _limits(self) -> None:
        if resource is None:
            return
        resource.setrlimit(resource.RLIMIT_CPU, (self.max_timeout_seconds, self.max_timeout_seconds + 1))
        resource.setrlimit(resource.RLIMIT_AS, (self.memory_bytes, self.memory_bytes))
        resource.setrlimit(resource.RLIMIT_FSIZE, (self.max_file_size_bytes, self.max_file_size_bytes))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        if hasattr(resource, "RLIMIT_NPROC"):
            resource.setrlimit(resource.RLIMIT_NPROC, (self.max_processes, self.max_processes))

    @staticmethod
    def _terminate_group(process: subprocess.Popen[str]) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process.kill()

    def _truncate(self, value: str) -> str:
        if len(value) <= self.max_output_chars:
            return value
        return value[: self.max_output_chars] + "\n[output truncated]"


class RootlessContainerTestExecutor:
    """Executa testes em Podman rootless com rede bloqueada e rootfs somente leitura."""

    def __init__(
        self,
        workspace: str | Path,
        *,
        image: str = "atena-sandbox-test:latest",
        runtime: str = "podman",
        max_timeout_seconds: int = 30,
        memory_mb: int = 512,
        max_file_size_mb: int = 32,
        max_processes: int = 64,
        max_output_chars: int = 12_000,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        if not self.workspace.is_dir():
            raise ValueError("workspace de testes não existe ou não é diretório")
        if not image or image.startswith(("-", "/")) or any(char.isspace() for char in image):
            raise ValueError("imagem do container inválida")
        if runtime != "podman":
            raise ValueError("RootlessContainerTestExecutor exige runtime Podman")
        self.image = image
        self.runtime = runtime
        self.max_timeout_seconds = max(1, min(max_timeout_seconds, 300))
        self.memory_mb = max(64, memory_mb)
        self.max_file_size_mb = max(1, max_file_size_mb)
        self.max_processes = max(1, max_processes)
        self.max_output_chars = max(1_000, max_output_chars)

    def __call__(self, arguments: dict[str, Any]) -> dict[str, Any]:
        target = self._safe_target(str(arguments.get("target", "")))
        timeout = max(1, min(int(arguments.get("timeout_seconds", 10)), self.max_timeout_seconds))
        command = [
            self.runtime, "run", "--rm",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            f"--pids-limit={self.max_processes}",
            f"--memory={self.memory_mb}m",
            f"--memory-swap={self.memory_mb}m",
            "--cpus=1",
            "--ulimit", "nofile=64:64",
            "--ulimit", f"fsize={self.max_file_size_mb * 1024 * 1024}:{self.max_file_size_mb * 1024 * 1024}",
            "--user=65532:65532",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m",
            "--tmpfs", "/home/sandbox:rw,noexec,nosuid,nodev,size=32m",
            "--mount", f"type=bind,src={self.workspace},dst=/workspace,ro",
            self.image,
            "python", "-m", "pytest", target, "-q", "--disable-warnings",
        ]
        started = time.perf_counter()
        env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": "/home/sandbox", "NO_COLOR": "1", "CI": "1"}
        try:
            completed = subprocess.run(
                command,
                cwd=self.workspace,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            timed_out = False
            stdout, stderr = completed.stdout, completed.stderr
            returncode = completed.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = exc.stdout or ""
            stderr = (exc.stderr or "") + "\n[timeout] limite do container excedido"
            returncode = 124
        except FileNotFoundError as exc:
            raise RuntimeError(f"runtime rootless indisponível: {self.runtime}") from exc
        return {
            "target": target,
            "passed": returncode == 0 and not timed_out,
            "returncode": returncode,
            "timed_out": timed_out,
            "stdout": self._truncate(str(stdout)),
            "stderr": self._truncate(str(stderr)),
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "runtime": f"{self.runtime}-rootless",
            "image": self.image,
            "isolation": {
                "filesystem": "read_only_bind_mount",
                "network": "none",
                "memory_mb": self.memory_mb,
                "max_file_size_mb": self.max_file_size_mb,
                "max_processes": self.max_processes,
                "user": "65532:65532",
            },
            "evidence": [f"test://rootless-container/{target}"],
        }

    def _safe_target(self, target: str) -> str:
        if not target or target.startswith("-") or "\x00" in target:
            raise ValueError("target de teste inválido")
        candidate = (self.workspace / target).resolve()
        try:
            candidate.relative_to(self.workspace)
        except ValueError as exc:
            raise ValueError("target fora do workspace") from exc
        if not candidate.exists():
            raise FileNotFoundError(f"target de teste não existe: {target}")
        return candidate.relative_to(self.workspace).as_posix()

    def _truncate(self, value: str) -> str:
        if len(value) <= self.max_output_chars:
            return value
        return value[: self.max_output_chars] + "\n[output truncated]"
