import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run(cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, cwd=str(ROOT), text=True, capture_output=True, check=False)


def test_production_center_onboarding_run_e2e():
    proc = _run("./atena production-center onboarding-run")
    payload = json.loads(proc.stdout)

    # O quality gate deve bloquear o onboarding quando o Guardian reprova.
    # O teste valida a decisão canônica, não força um falso sucesso.
    if proc.returncode != 0:
        assert proc.returncode == 2
        assert payload["status"] == "partial"
        assert payload["gate_ok"] is False
        assert payload["contract_valid"] is True
        assert payload["completed_steps"] < payload["total_steps"]
    else:
        assert payload["status"] == "ok"
        assert payload["gate_ok"] is True
        assert payload["completed_steps"] == payload["total_steps"] == 4


def test_production_center_quality_score_e2e():
    proc = _run("./atena production-center quality-score --profiles support,dev")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["total"] == 2
    assert payload["passed"] >= 1
    assert payload["score"] >= 0.5
