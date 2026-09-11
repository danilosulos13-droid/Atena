#!/usr/bin/env python3
"""Loop persistente de aprendizado da ATENA."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.atena_terminal_assistant import (
    parse_background_topics,
    run_background_internet_learning_cycle,
)

DEFAULT_STATUS = ROOT / "atena_evolution" / "learning_daemon_status.json"
running = True


def _stop(signum: int, frame: object) -> None:
    del signum, frame
    global running
    running = False


def write_status(status_path: Path, **values: object) -> None:
    status_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        **values,
    }
    status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(topics: list[str], interval: float, status_path: Path, once: bool) -> int:
    cycle = 0
    write_status(status_path, state="starting", topics=topics, cycle=cycle)
    while running:
        topic = topics[cycle % len(topics)]
        cycle += 1
        started = datetime.now(timezone.utc).isoformat()
        write_status(status_path, state="running", topic=topic, topics=topics, cycle=cycle, started_at=started)
        try:
            result = run_background_internet_learning_cycle(topic)
            write_status(
                status_path,
                state="completed" if once else "sleeping",
                topic=topic,
                topics=topics,
                cycle=cycle,
                last_result={"status": result.get("status"), "created": result.get("created", [])},
                last_completed_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:
            write_status(status_path, state="error", topic=topic, topics=topics, cycle=cycle, error=str(exc))
            if once:
                return 1
        if once:
            return 0
        for _ in range(max(1, int(interval))):
            if not running:
                break
            time.sleep(1)
    write_status(status_path, state="stopped", topics=topics, cycle=cycle)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Executa o aprendizado contínuo da ATENA.")
    parser.add_argument("--topics", default=os.getenv("ATENA_LEARNING_TOPICS"), help="Tópicos separados por vírgula.")
    parser.add_argument("--interval", type=float, default=float(os.getenv("ATENA_LEARNING_INTERVAL", "3600")))
    parser.add_argument("--status-file", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--once", action="store_true", help="Executa apenas um ciclo e encerra.")
    args = parser.parse_args()
    topics = parse_background_topics(args.topics)
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    return run(topics, max(1, args.interval), args.status_file, args.once)


if __name__ == "__main__":
    raise SystemExit(main())