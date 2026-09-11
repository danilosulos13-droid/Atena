#!/usr/bin/env python3
"""Gerencia download/preparação e treinamento LoRA em segundo plano.

Uso:
  ./atena train-background [--model MODEL] [--examples N] [--install-deps]
  ./atena train-status
  ./atena train-log [-f]
  ./atena train-stop

O processo filho grava PID, estado e log em atena_evolution/training/background/.
O download do modelo acontece pelo transformers durante o preflight/treino e fica
no cache Hugging Face configurado por HF_HOME.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "atena_evolution" / "training" / "background"
PID_FILE = STATE_DIR / "train.pid"
STATE_FILE = STATE_DIR / "state.json"
LOG_FILE = STATE_DIR / "train.log"
DEFAULT_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default.copy()


def write_state(**updates: object) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state = read_json(STATE_FILE, {})
    state.update(updates)
    state["updated_at"] = now()
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def active_pid() -> int | None:
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    if pid_alive(pid):
        return pid
    return None


def dependency_command(install: bool) -> list[list[str]]:
    if not install:
        return []
    commands = []
    pinned = ROOT / "setup" / "requirements-pinned.txt"
    autonomous = ROOT / "setup" / "requirements-autonomous-learning.txt"
    for req in (pinned, autonomous):
        if req.exists():
            commands.append([sys.executable, "-m", "pip", "install", "-r", str(req)])
    commands.append([sys.executable, "-m", "pip", "install", "piper-tts"])
    return commands


def run_child(model: str, examples: int, epochs: int, install: bool) -> int:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    env = os.environ.copy()
    env.update({
        "ATENA_ROOT": str(ROOT),
        "PYTHONPATH": str(ROOT),
        "ATENA_TRAIN_MODEL": model,
        "ATENA_MIN_TRAIN_EXAMPLES": str(examples),
        "ATENA_MAX_TRAIN_EXAMPLES": str(examples),
        "ATENA_AUTOTRAIN": "1",
        "ATENA_TRAIN_EPOCHS": str(epochs),
        "HF_HOME": env.get("HF_HOME", str(ROOT / ".cache" / "huggingface")),
        "TOKENIZERS_PARALLELISM": "false",
    })
    log = LOG_FILE.open("a", encoding="utf-8", buffering=1)
    try:
        write_state(status="installing" if install else "preparing", pid=os.getpid(), model=model, examples=examples, started_at=now())
        log.write(f"[{now()}] ATENA background training started model={model} examples={examples}\n")
        for command in dependency_command(install):
            log.write(f"[{now()}] install: {' '.join(command)}\n")
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            if result.returncode:
                write_state(status="failed", returncode=result.returncode, error="dependency installation failed", finished_at=now())
                return result.returncode
        write_state(status="training", pid=os.getpid(), model=model, examples=examples)
        command = [sys.executable, "scripts/atena_autonomous_learning.py", "cycle", "--train"]
        log.write(f"[{now()}] train: {' '.join(command)}\n")
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        status = "completed" if result.returncode == 0 else "failed"
        write_state(status=status, returncode=result.returncode, finished_at=now())
        log.write(f"[{now()}] ATENA background training {status}\n")
        return result.returncode
    except KeyboardInterrupt:
        write_state(status="stopped", finished_at=now())
        return 130
    finally:
        log.close()
        try:
            PID_FILE.unlink()
        except FileNotFoundError:
            pass


def start(args: argparse.Namespace) -> int:
    pid = active_pid()
    if pid:
        print(json.dumps({"status": "already_running", "pid": pid, "state": str(STATE_FILE)}, ensure_ascii=False))
        return 0
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as log:
        log.write(f"[{now()}] scheduling background process\n")
    command = [sys.executable, str(Path(__file__).resolve()), "_worker", "--model", args.model, "--examples", str(args.examples), "--epochs", str(args.epochs)]
    if args.install_deps:
        command.append("--install-deps")
    with LOG_FILE.open("a", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=ROOT, env=os.environ.copy(), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
    PID_FILE.write_text(str(process.pid), encoding="utf-8")
    write_state(status="queued", pid=process.pid, model=args.model, examples=args.examples, started_at=now())
    print(json.dumps({"status": "started", "pid": process.pid, "model": args.model, "examples": args.examples, "state": str(STATE_FILE), "log": str(LOG_FILE)}, ensure_ascii=False, indent=2))
    return 0


def status(_: argparse.Namespace) -> int:
    state = read_json(STATE_FILE, {"status": "never_started"})
    pid = active_pid()
    state["running"] = bool(pid)
    if pid:
        state["pid"] = pid
    elif state.get("status") in {"queued", "preparing", "installing", "training"}:
        state["status"] = "stale"
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


def log_cmd(args: argparse.Namespace) -> int:
    if not LOG_FILE.exists():
        print("Nenhum log de treinamento encontrado.")
        return 0
    if args.follow:
        with LOG_FILE.open(encoding="utf-8", errors="replace") as stream:
            stream.seek(0, os.SEEK_END)
            while True:
                line = stream.readline()
                if line:
                    print(line, end="")
                elif not active_pid():
                    break
                else:
                    time.sleep(1)
    else:
        print(LOG_FILE.read_text(encoding="utf-8", errors="replace")[-12000:])
    return 0


def stop(_: argparse.Namespace) -> int:
    pid = active_pid()
    if not pid:
        print(json.dumps({"status": "not_running"}, ensure_ascii=False))
        return 0
    os.killpg(pid, signal.SIGTERM)
    write_state(status="stopping", pid=pid, stopped_at=now())
    print(json.dumps({"status": "stop_requested", "pid": pid}, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Treinamento LoRA da Atena em segundo plano")
    sub = parser.add_subparsers(dest="command", required=True)
    p_start = sub.add_parser("start")
    p_start.add_argument("--model", default=os.getenv("ATENA_TRAIN_MODEL", DEFAULT_MODEL))
    p_start.add_argument("--examples", type=int, default=int(os.getenv("ATENA_MAX_TRAIN_EXAMPLES", "64")))
    p_start.add_argument("--epochs", type=int, default=int(os.getenv("ATENA_TRAIN_EPOCHS", "1")))
    p_start.add_argument("--install-deps", action="store_true")
    p_start.set_defaults(func=start)
    p_worker = sub.add_parser("_worker")
    p_worker.add_argument("--model", required=True)
    p_worker.add_argument("--examples", type=int, required=True)
    p_worker.add_argument("--epochs", type=int, default=1)
    p_worker.add_argument("--install-deps", action="store_true")
    p_worker.set_defaults(func=lambda a: run_child(a.model, a.examples, a.epochs, a.install_deps))
    p_status = sub.add_parser("status")
    p_status.set_defaults(func=status)
    p_log = sub.add_parser("log")
    p_log.add_argument("-f", "--follow", action="store_true")
    p_log.set_defaults(func=log_cmd)
    p_stop = sub.add_parser("stop")
    p_stop.set_defaults(func=stop)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
