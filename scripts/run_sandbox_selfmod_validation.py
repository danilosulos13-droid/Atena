#!/usr/bin/env python3
"""Valida auto-modificações em sandbox descartável.

O script não faz push, deploy, chamadas Telegram/Tasker nem altera a main.
Ele é usado no CI sobre o checkout do candidato.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ALLOWED_PREFIXES = ("core/", "scripts/", "tests/", "docs/", "research/", "setup/", "deploy/", "config/", ".github/workflows/")
ALLOWED_ROOT_FILES = {"README.md", "pyproject.toml", "CHANGELOG.md", "conftest.py"}
FORBIDDEN_PREFIXES = (".git/", "data/", "evolution/", "atena_evolution/", "generated/", "logs/")


def run(cmd: list[str], cwd: Path, env: dict[str, str], timeout: int) -> dict:
    started = time.perf_counter()
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout)
        return {"cmd": cmd, "returncode": p.returncode, "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                "stdout": p.stdout[-6000:], "stderr": p.stderr[-6000:]}
    except subprocess.TimeoutExpired as exc:
        return {"cmd": cmd, "returncode": 124, "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                "stdout": (exc.stdout or "")[-6000:], "stderr": "timeout"}


def changed_files(root: Path, base: str) -> list[str]:
    p = subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD"], cwd=root, text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or "git diff failed")
    return [x.strip() for x in p.stdout.splitlines() if x.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--output", type=Path, default=Path("sandbox-validation.json"))
    ap.add_argument("--pytest", default="tests/unit")
    ap.add_argument("--timeout", type=int, default=300)
    args = ap.parse_args()
    root = Path.cwd().resolve()
    report = {"decision": "block", "repository": str(root), "base": args.base, "changed_files": [], "checks": []}
    try:
        files = changed_files(root, args.base)
    except Exception as exc:
        report["checks"].append({"name": "changed_files", "passed": False, "error": str(exc)})
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 1
    report["changed_files"] = files
    forbidden = [f for f in files if f.startswith(FORBIDDEN_PREFIXES) or (not f.startswith(ALLOWED_PREFIXES) and f not in ALLOWED_ROOT_FILES)]
    report["checks"].append({"name": "file_allowlist", "passed": not forbidden, "forbidden": forbidden})
    if forbidden:
        report["reason"] = "alteração fora da allowlist ou em dados persistentes"
    else:
        env = os.environ.copy()
        env.update({"PYTHONPATH": str(root), "ALLOW_DEEP_SELF_MOD": "false", "ALLOW_CHECKER_EVOLVE": "false",
                    "ALLOW_WORKFLOW_MUTATION": "false", "DEPLOY_GIT_REPO": "", "DEPLOY_DOCKER_IMAGE": "",
                    "DEPLOY_COMMAND": "", "CI": "true", "GITHUB_ACTIONS": "true"})
        commands = [
            ("compile", [sys.executable, "-m", "compileall", "-q", "core", "scripts"]),
            ("healthcheck", [sys.executable, "scripts/main_healthcheck.py"]),
            ("unit_tests", [sys.executable, "-m", "pytest", "-q", args.pytest, "--disable-warnings"]),
        ]
        for name, cmd in commands:
            result = run(cmd, root, env, args.timeout)
            result["name"] = name; result["passed"] = result["returncode"] == 0
            report["checks"].append(result)
            if not result["passed"]:
                report["reason"] = f"check falhou: {name}"
                break
        else:
            report["checks"].append({"name": "external_side_effects", "passed": True,
                                     "policy": "sem push, deploy, Telegram, Tasker ou shell de modelo"})
            report["decision"] = "pass"
            report["reason"] = "candidato validado em sandbox; promoção depende do benchmark de regressão"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"decision": report["decision"], "output": str(args.output), "checks": len(report["checks"])}, ensure_ascii=False))
    return 0 if report["decision"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
