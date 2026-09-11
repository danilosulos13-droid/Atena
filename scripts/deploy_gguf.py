#!/usr/bin/env python3
"""Publica um GGUF aprovado no servidor da ponte Telegram.

O deploy é bloqueado se o relatório não tiver ``status=pass`` e
``promotion_allowed=true``. O arquivo é enviado para um temporário, validado
por SHA-256 no destino e instalado como release imutável; o symlink ``active``
é atualizado por operação atômica. Segredos devem vir de variáveis de ambiente
ou do ssh-agent, nunca do Git.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path


def run(command: list[str]) -> str:
    print("+", " ".join(shlex.quote(item) for item in command), flush=True)
    result = subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.stdout:
        print(result.stdout, end="")
    return result.stdout


def remote(host: str, command: str, port: str) -> str:
    return run(["ssh", "-p", port, host, "bash", "-lc", command])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gguf", type=Path, required=True)
    parser.add_argument("--holdout-report", type=Path, required=True)
    parser.add_argument("--release", default=os.getenv("GITHUB_RUN_ID", "manual"))
    parser.add_argument("--restart-service", action="store_true")
    parser.add_argument("--ollama-model", default=os.getenv("ATENA_DEPLOY_OLLAMA_MODEL", ""), help="nome Ollama a criar a partir de active.gguf")
    parser.add_argument("--configure-systemd", action="store_true", help="persistir ATENA_LOCAL_MODEL no drop-in do serviço")
    args = parser.parse_args()

    report = json.loads(args.holdout_report.read_text(encoding="utf-8"))
    if report.get("status") != "pass" or report.get("promotion_allowed") is not True:
        raise SystemExit("deploy bloqueado: o holdout não aprovou este candidato")
    if not args.gguf.is_file() or args.gguf.stat().st_size == 0:
        raise SystemExit(f"GGUF ausente ou vazio: {args.gguf}")

    host = os.getenv("ATENA_DEPLOY_HOST", "").strip()
    user = os.getenv("ATENA_DEPLOY_USER", "ubuntu").strip()
    port = os.getenv("ATENA_DEPLOY_SSH_PORT", "22").strip()
    remote_dir = os.getenv("ATENA_DEPLOY_REMOTE_DIR", "/opt/atena/models").strip()
    service = os.getenv("ATENA_DEPLOY_SERVICE", "atena-telegram").strip()
    if not host:
        raise SystemExit("ATENA_DEPLOY_HOST não configurado")
    if not remote_dir.startswith("/"):
        raise SystemExit("ATENA_DEPLOY_REMOTE_DIR deve ser absoluto")
    target = f"{user}@{host}"
    digest = hashlib.sha256(args.gguf.read_bytes()).hexdigest()
    release_name = f"atena-{args.release}-{digest[:12]}.gguf"
    tmp_name = f".upload-{release_name}.tmp"
    remote_release = f"{remote_dir}/{release_name}"
    remote_tmp = f"{remote_dir}/{tmp_name}"
    remote_active = f"{remote_dir}/active.gguf"

    remote(target, f"install -d -m 0755 {shlex.quote(remote_dir)}", port)
    run(["scp", "-P", port, str(args.gguf), f"{target}:{remote_tmp}"])
    remote_hash = remote(target, f"sha256sum {shlex.quote(remote_tmp)} | cut -d' ' -f1", port).strip().splitlines()[-1]
    if remote_hash != digest:
        remote(target, f"rm -f {shlex.quote(remote_tmp)}", port)
        raise SystemExit(f"hash remoto divergente: local={digest} remoto={remote_hash}")

    install_command = (
        f"install -m 0644 {shlex.quote(remote_tmp)} {shlex.quote(remote_release)} && "
        f"rm -f {shlex.quote(remote_tmp)} && "
        f"ln -sfn {shlex.quote(remote_release)} {shlex.quote(remote_active)}"
    )
    if args.ollama_model:
        safe_model = shlex.quote(args.ollama_model)
        safe_dir = shlex.quote(remote_dir)
        install_command += (
            f" && printf '%s\\n' 'FROM {remote_dir}/active.gguf' > {safe_dir}/Modelfile.atena "
            f"&& ollama create {safe_model} -f {safe_dir}/Modelfile.atena"
        )
        if args.configure_systemd:
            systemd_dir = f"/etc/systemd/system/{service}.service.d"
            systemd_file = f"{systemd_dir}/20-atena-model.conf"
            install_command += (
                f" && sudo install -d -m 0755 {shlex.quote(systemd_dir)}"
                f" && printf '%s\\n' '[Service]' 'Environment=ATENA_LOCAL_MODEL={args.ollama_model}' "
                f"| sudo tee {shlex.quote(systemd_file)} >/dev/null"
                " && sudo systemctl daemon-reload"
            )
    if args.restart_service:
        install_command += f" && sudo systemctl try-restart {shlex.quote(service)}"
    remote(target, install_command, port)
    print(json.dumps({
        "status": "deployed",
        "host": host,
        "release": release_name,
        "active": remote_active,
        "sha256": digest,
        "holdout": report.get("improvement"),
        "service_restarted": args.restart_service,
        "ollama_model": args.ollama_model or None,
        "systemd_configured": args.configure_systemd,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
