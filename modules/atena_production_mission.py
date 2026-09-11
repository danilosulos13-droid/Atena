# -*- coding: utf-8 -*-
"""ATENA Ω — Production Mission: gate final de produção."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.atena_quality_gate import evaluate_production_gate
from modules.atena_telemetry_hub import AtenaTelemetryHub, TelemetryEvent


def run_cmd(cmd: list[str], timeout: int = 300) -> dict:
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return {
        "command": " ".join(cmd),
        "returncode": proc.returncode,
        "stdout": proc.stdout[-8000:],
        "stderr": proc.stderr[-4000:],
        "ok": proc.returncode == 0,
    }


def latest_guardian_report() -> dict:
    reports = sorted((ROOT / "atena_evolution").glob("guardian_report_*.json"))
    if not reports:
        return {}
    try:
        return json.loads(reports[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def main() -> int:
    t0 = time.perf_counter()
    telemetry = AtenaTelemetryHub(ROOT)
    doctor = run_cmd(["./atena", "doctor"], timeout=240)
    guardian = run_cmd([sys.executable, "protocols/atena_guardian_mission.py"], timeout=300)
    guardian_report = latest_guardian_report()
    if not guardian_report:
        guardian_report = {
            "guardian_ok": False,
            "approved": False,
            "decision": "rejected",
            "blockers": ["Relatório canônico do Guardian não encontrado"],
        }

    expected_commit = os.getenv("GITHUB_SHA") or None
    gate = evaluate_production_gate(
        doctor_ok=doctor["ok"],
        guardian_result=guardian_report,
        guardian_process_ok=guardian["ok"],
        expected_commit_sha=expected_commit,
    )

    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%d")
    docs_dir = ROOT / "docs"
    evo_dir = ROOT / "atena_evolution"
    docs_dir.mkdir(parents=True, exist_ok=True)
    evo_dir.mkdir(parents=True, exist_ok=True)

    md_path = docs_dir / f"PRODUCTION_GATE_{stamp}.md"
    json_path = evo_dir / f"production_gate_{now.strftime('%Y%m%d_%H%M%S')}.json"
    md_lines = [
        f"# Production Gate — {stamp}",
        "",
        f"- Gate final: **{'APROVADO' if gate.approved else 'REPROVADO'}**",
        f"- Decisão canônica: **{gate.decision}**",
        f"- Guardian OK: **{gate.guardian_ok}**",
        f"- Commit esperado: `{expected_commit or 'não informado'}`",
        "",
        "## Checks executados",
        f"- {'✅' if doctor['ok'] else '❌'} `{doctor['command']}` (rc={doctor['returncode']})",
        f"- {'✅' if guardian['ok'] else '❌'} `{guardian['command']}` (rc={guardian['returncode']})",
        "",
        "## Blockers",
    ]
    md_lines.extend(f"- {blocker}" for blocker in gate.blockers)
    if not gate.blockers:
        md_lines.append("- Nenhum blocker detectado")
    md_lines.extend([
        "",
        "## Política",
        "Aprovar somente quando doctor, processo Guardian e relatório canônico Guardian estiverem aprovados no mesmo commit.",
    ])
    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    payload = {
        **gate.to_dict(),
        "generated_at": now.isoformat(),
        "expected_commit_sha": expected_commit,
        "checks": {"doctor": doctor, "guardian": guardian},
        "guardian_report": guardian_report,
        "report_markdown": str(md_path.relative_to(ROOT)),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("🚦 ATENA Production Gate")
    print(f"Status: {'APROVADO' if gate.approved else 'REPROVADO'}")
    print(f"Guardian: {'OK' if guardian['ok'] else 'FAIL'} / relatório: {guardian_report.get('decision', 'unknown')}")
    print(f"Relatório: {md_path.relative_to(ROOT)}")
    print(f"Artefato: {json_path.relative_to(ROOT)}")
    telemetry.log_event(
        TelemetryEvent(
            mission="production-ready",
            status="approved" if gate.approved else "rejected",
            latency_ms=(time.perf_counter() - t0) * 1000.0,
            metadata={"doctor_ok": doctor["ok"], "guardian_ok": gate.guardian_ok, "blockers": gate.blockers},
        )
    )
    return 0 if gate.approved else 2


if __name__ == "__main__":
    raise SystemExit(main())
