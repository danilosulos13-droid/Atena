"""Execução opcional de código em sandbox Docker endurecido.

Desativado por padrão. Não acessa a rede, não monta o host e remove privilégios.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class SandboxError(RuntimeError):
    pass


@dataclass(frozen=True)
class SandboxResult:
    status: str
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False


class PythonSandbox:
    def __init__(self, *, image: str = "python:3.11-slim", timeout: int = 20, memory: str = "256m", cpus: str = "0.5", allow_network: bool = False) -> None:
        self.image = image
        self.timeout = max(1, min(int(timeout), 120))
        self.memory = memory
        self.cpus = cpus
        self.allow_network = allow_network

    def run(self, code: str, *, approved: bool = False) -> SandboxResult:
        if os.getenv("ATENA_SANDBOX_ENABLED", "0").lower() not in {"1", "true", "yes"}:
            raise SandboxError("sandbox desativado; defina ATENA_SANDBOX_ENABLED=1")
        if not approved:
            raise SandboxError("execução exige confirmação explícita")
        if len(code.encode("utf-8")) > 100_000:
            raise SandboxError("código excede o limite de 100 KB")
        with tempfile.TemporaryDirectory(prefix="atena-sandbox-") as workdir:
            script = Path(workdir) / "main.py"
            script.write_text(code, encoding="utf-8")
            command = ["docker", "run", "--rm", "--init", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit", "64", "--memory", self.memory, "--cpus", self.cpus]
            command += [] if self.allow_network else ["--network", "none"]
            command += ["--tmpfs", "/tmp:rw,noexec,nosuid,size=64m", "-v", f"{workdir}:/work:rw,noexec,nosuid", "-w", "/work", self.image, "python", "-I", "-B", "/work/main.py"]
            try:
                completed = subprocess.run(command, capture_output=True, text=True, timeout=self.timeout, check=False)
            except FileNotFoundError as exc:
                raise SandboxError("Docker não está instalado") from exc
            except subprocess.TimeoutExpired as exc:
                return SandboxResult("timeout", (exc.stdout or "")[-12000:], (exc.stderr or "")[-12000:], 124, True)
            return SandboxResult("ok" if completed.returncode == 0 else "error", completed.stdout[-12000:], completed.stderr[-12000:], completed.returncode)
