#!/usr/bin/env python3
"""Executa um ciclo de integração local do Planner com o broker de produção.

O teste usa SQLite temporário e uma fonte RSS HTTP local, sem chamadas externas
nem efeitos de escrita fora do diretório temporário.
"""
from __future__ import annotations

import argparse
import json
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from core.agent_plan_loop import Plan, PlanStep
from core.executors.factory import build_production_broker, build_production_planner
from core.knowledge_base import KnowledgeBase


RSS = b'''<?xml version="1.0"?><rss version="2.0"><channel><title>Fixture</title><item><title>Rollback seguro</title><link>http://127.0.0.1/rollback</link><description>O rollback deve ser validado em sandbox.</description></item></channel></rss>'''


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml")
        self.send_header("Content-Length", str(len(RSS)))
        self.end_headers()
        self.wfile.write(RSS)

    def log_message(self, *_args):
        return


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="não apagar o diretório temporário")
    args = parser.parse_args()

    temporary = tempfile.TemporaryDirectory(prefix="atena-agent-cycle-")
    root = Path(temporary.name)
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        feed_url = f"http://127.0.0.1:{server.server_port}/feed.xml"
        config_path = root / "sources.json"
        config_path.write_text(json.dumps({"sources": [{
            "name": "local-fixture", "type": "rss", "enabled": True,
            "mode": "autonomous", "url": feed_url, "category": "test", "weight": 1.0,
        }]}), encoding="utf-8")
        db_path = root / "memory.sqlite3"
        with KnowledgeBase(db_path) as knowledge:
            knowledge.add_document(
                url="https://memory.test/rollback",
                title="Memória de rollback",
                topic="segurança",
                content="O rollback deve ser testado antes da promoção.",
            )

        audit_path = root / "audit.jsonl"
        broker = build_production_broker(db_path, audit_path=audit_path, sources_config=config_path)
        planner = build_production_planner(broker)
        plan = Plan(
            goal="validar evidência de rollback com memória e pesquisa web",
            steps=(
                PlanStep(
                    id="memory",
                    objective="consultar memória persistida",
                    tool="memory_search",
                    parameters={"query": "rollback", "limit": 3},
                    success_criteria=("evidence",),
                ),
                PlanStep(
                    id="web",
                    objective="consultar fonte RSS autorizada",
                    tool="web_search",
                    parameters={"query": "rollback", "domain": "127.0.0.1"},
                    success_criteria=("evidence",),
                ),
            ),
        )
        result = planner.execute(plan)
        output = {
            "accepted": result["critic"]["accepted"],
            "failed_steps": result["critic"]["failed_steps"],
            "missing_evidence": result["critic"]["missing_evidence"],
            "observations": result["observations"],
            "rollback": result["rollback"],
            "audit_events": len(audit_path.read_text(encoding="utf-8").splitlines()) if audit_path.exists() else 0,
            "temporary_root": str(root),
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        if not result["critic"]["accepted"]:
            return 1
        if args.keep:
            temporary = None
        return 0
    finally:
        server.shutdown()
        server.server_close()
        if temporary is not None:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
