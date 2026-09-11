#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ATENA Release Gate — avaliação de prontidão para release.

Executa uma bateria determinística de gates e decide GO/NO-GO:
  1. Sintaxe/compilação dos módulos core e modules (py_compile)
  2. Smoke de módulos (modules-smoke mission)
  3. Auto-validação (self-test quick)
  4. Validação externa de maturidade (AGI external validation)

O resultado é escrito como JSON consumível por CI/CD.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "atena_evolution" / "release_gates"


def _run(cmd: List[str], timeout: int = 240) -> Dict[str, Any]:
    started = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout
        )
        elapsed = time.time() - started
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "elapsed_seconds": round(elapsed, 2),
            "tail": (proc.stdout or proc.stderr or "")[-600:],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "returncode": -1, "elapsed_seconds": timeout, "tail": "TIMEOUT"}


def gate_syntax() -> Dict[str, Any]:
    """Compila todos os .py de core/ e modules/."""
    result = _run([sys.executable, "-m", "compileall", "-q", "core", "modules"])
    if result["ok"]:
        return {"id": "syntax", "description": "Compilação de core/ e modules/", **result}
    return {"id": "syntax", "description": "Compilação de core/ e modules/", **result}


def gate_smoke() -> Dict[str, Any]:
    result = _run([str(ROOT / "atena"), "modules-smoke"])
    return {"id": "modules-smoke", "description": "Smoke de módulos", **result}


def gate_self_test() -> Dict[str, Any]:
    result = _run([sys.executable, str(ROOT / "core/atena_self_test.py"), "quick"])
    return {"id": "self-test-quick", "description": "Auto-validação rápida (pytest)", **result}


def gate_external_validation() -> Dict[str, Any]:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "atena_agi_external_validation", str(ROOT / "core/atena_agi_external_validation.py")
    )
    mod = importlib.util.module_from_spec(spec)
    # Necessário registrar em sys.modules ANTES de executar: módulos que usam
    # dataclasses/frozen=True acessam sys.modules[cls.__module__] durante a
    # definição da classe e falham com AttributeError se não estiver registrado.
    sys.modules["atena_agi_external_validation"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    try:
        payload = mod.run_external_validation(ROOT, timeout_seconds=240)
        ok = (payload.get("score_1_10") or 0) >= 7.0
        return {
            "id": "external-validation",
            "description": "Validação externa de maturidade AGI",
            "ok": ok,
            "score_1_10": payload.get("score_1_10"),
            "elapsed_seconds": payload.get("duration_seconds", 0),
            "tail": json.dumps(payload, default=str)[:600],
        }
    except Exception as exc:  # pragma: no cover
        import traceback
        return {
            "id": "external-validation",
            "description": "Validação externa de maturidade AGI",
            "ok": False,
            "returncode": -1,
            "elapsed_seconds": 0,
            "tail": f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-800:]}",
        }


def gate_benchmark() -> Dict[str, Any]:
    result = _run([sys.executable, str(ROOT / "core/atena_benchmark.py")], timeout=120)
    try:
        report = json.loads((ROOT / "atena_evolution" / "release_gates" / "benchmark-latest.json").read_text(encoding="utf-8"))
    except Exception:
        report = {}
    result["score"] = report.get("score")
    result["minimum"] = float(__import__("os").getenv("ATENA_BENCHMARK_MIN", "90"))
    result["ok"] = result.get("score", 0) >= result["minimum"]
    return {"id": "benchmark", "description": "Benchmark determinístico de prontidão", **result}


GATES = [gate_syntax, gate_smoke, gate_self_test, gate_benchmark, gate_external_validation]


def run_release_gate() -> Dict[str, Any]:
    started = datetime.now(timezone.utc)
    results: List[Dict[str, Any]] = []
    for gate in GATES:
        try:
            results.append(gate())
        except Exception as exc:  # pragma: no cover
            results.append({"id": gate.__name__, "ok": False, "tail": f"{type(exc).__name__}: {exc}"})

    passed = sum(1 for r in results if r.get("ok"))
    total = len(results)
    # Gate é bloqueante: syntax, smoke e self-test devem passar; validação externa
    # entra com peso informativo (necessita LLM provider).
    hard_pass = all(r.get("ok") for r in results if r["id"] != "external-validation")
    status = "GO" if hard_pass else "NO-GO"
    payload: Dict[str, Any] = {
        "status": status,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "gates": {"passed": passed, "total": total},
        "results": results,
        "recommendation": (
            "Aprovado para release." if status == "GO"
            else "Reprova no gate; revise os itens 'ok: false' antes de liberar."
        ),
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = REPORT_DIR / f"release_gate_{ts}.json"
    report_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    payload["report_path"] = str(report_path)
    return payload


def main(argv: List[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    json_only = "--json" in argv
    payload = run_release_gate()
    print(f"ATENA release-gate status={payload['status']} "
          f"gates={payload['gates']['passed']}/{payload['gates']['total']}")
    print(f"Report: {payload['report_path']}")
    for r in payload["results"]:
        mark = "OK" if r.get("ok") else "FAIL"
        print(f"  [{mark}] {r['id']}: {r.get('description', '')} "
              f"(rc={r.get('returncode')})")
    if json_only:
        print(json.dumps(payload, indent=2, default=str))
    return 0 if payload["status"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
