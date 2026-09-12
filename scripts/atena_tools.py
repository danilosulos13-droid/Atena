#!/usr/bin/env python3
"""CLI do roteador geral de ferramentas da Atena."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.general_tool_router import GeneralToolRouter


def main() -> int:
    parser = argparse.ArgumentParser(description="Executa ferramentas allowlisted da Atena")
    parser.add_argument("action", choices=("list", "execute"))
    parser.add_argument("name", nargs="?")
    parser.add_argument("--arguments", default="{}", help="JSON de argumentos")
    parser.add_argument("--approve", action="store_true", help="aprova ações browser.write")
    parser.add_argument("--audit", default="atena_evolution/tool_router_audit.jsonl")
    args = parser.parse_args()
    router = GeneralToolRouter(audit_path=Path(args.audit))
    try:
        if args.action == "list":
            print(json.dumps([policy.__dict__ for policy in router.POLICIES.values()], ensure_ascii=False, indent=2))
            return 0
        if not args.name:
            parser.error("name é obrigatório com execute")
        result = router.dispatch(args.name, json.loads(args.arguments), approval=args.approve)
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2, default=str))
        return 0 if result.status == "executed" else 2
    finally:
        router.close()


if __name__ == "__main__":
    raise SystemExit(main())
