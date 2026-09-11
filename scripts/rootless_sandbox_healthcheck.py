#!/usr/bin/env python3
"""Preflight obrigatório do executor rootless antes do ciclo da Atena."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def run(command: list[str], *, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--image", default=os.getenv("ATENA_SANDBOX_IMAGE", "atena-sandbox-test:latest"))
    parser.add_argument("--runtime", default="podman")
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    if not workspace.is_dir():
        print(json.dumps({"ok": False, "reason": "workspace inexistente"}), file=sys.stderr)
        return 2
    if args.runtime != "podman" or not args.image or args.image.startswith(("-", "/")) or any(c.isspace() for c in args.image):
        print(json.dumps({"ok": False, "reason": "runtime ou imagem inválidos"}), file=sys.stderr)
        return 2

    checks: dict[str, object] = {}
    try:
        info = run([args.runtime, "info", "--format", "{{.Host.Security.Rootless}}"])
    except FileNotFoundError:
        print(json.dumps({"ok": False, "reason": "podman não instalado"}), file=sys.stderr)
        return 127
    checks["podman_rootless"] = info.returncode == 0 and info.stdout.strip() == "true"
    checks["image_exists"] = run([args.runtime, "image", "exists", args.image]).returncode == 0
    if not all(checks.values()):
        print(json.dumps({"ok": False, "checks": checks}, ensure_ascii=False), file=sys.stderr)
        return 1

    probe_code = """import os
import socket

assert os.getuid() == 65532, os.getuid()
try:
    socket.create_connection(('1.1.1.1', 443), 2)
except OSError:
    pass
else:
    raise AssertionError('rede não está bloqueada')
try:
    open('/workspace/.atena-healthcheck', 'w').close()
except OSError:
    pass
else:
    raise AssertionError('workspace não é somente leitura')
print('rootless sandbox checks passed')"""
    command = [
        args.runtime, "run", "--rm",
        "--network=none", "--read-only", "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true", "--pids-limit=64",
        "--memory=512m", "--memory-swap=512m", "--cpus=1",
        "--user=65532:65532",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m",
        "--tmpfs", "/home/sandbox:rw,noexec,nosuid,nodev,size=32m",
        "--mount", f"type=bind,src={workspace},dst=/workspace,ro",
        args.image, "python", "-c", probe_code,
    ]
    probe = run(command, timeout=20)
    checks.update({
        "uid_65532": probe.returncode == 0,
        "network_none": probe.returncode == 0,
        "workspace_read_only": probe.returncode == 0,
    })
    report = {"ok": all(checks.values()), "image": args.image, "workspace": str(workspace), "checks": checks, "stdout": probe.stdout[-2000:], "stderr": probe.stderr[-2000:]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
