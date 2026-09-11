#!/usr/bin/env python3
"""Verifica o entrypoint principal sem iniciar o loop autônomo nem efeitos externos."""
from __future__ import annotations
import ast
import importlib
import json
import os
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = [
    "core.episodic_memory", "core.memory_store", "core.memory_retrieval",
    "core.memory_consolidation", "core.identity_state", "core.sensemaking",
    "core.evolution_quality_gate", "core.atena_llm_router", "core.provider_quota",
    "core.agent_plan_loop", "core.structured_benchmark", "core.tool_broker",
]

def main() -> int:
    results = {}
    main_file = ROOT / "main.py"
    try:
        py_compile.compile(str(main_file), doraise=True)
        results["main_compile"] = "ok"
    except Exception as exc:
        results["main_compile"] = f"error: {exc}"
    for module in MODULES:
        try:
            importlib.import_module(module)
            results[module] = "ok"
        except Exception as exc:
            results[module] = f"error: {type(exc).__name__}: {exc}"
    source = main_file.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(source)
    results["main_ast"] = "ok" if tree else "error"
    results["safe_defaults"] = {
        "ALLOW_DEEP_SELF_MOD": os.getenv("ALLOW_DEEP_SELF_MOD", "false").lower() == "true",
        "ALLOW_CHECKER_EVOLVE": os.getenv("ALLOW_CHECKER_EVOLVE", "false").lower() == "true",
        "DEPLOY_GIT_REPO_configured": bool(os.getenv("DEPLOY_GIT_REPO")),
        "DEPLOY_COMMAND_configured": bool(os.getenv("DEPLOY_COMMAND")),
    }
    print(json.dumps(results, ensure_ascii=False, indent=2))
    failed = [k for k, v in results.items() if isinstance(v, str) and v.startswith("error:")]
    return 1 if failed else 0

if __name__ == "__main__":
    raise SystemExit(main())
