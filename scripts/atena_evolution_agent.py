#!/usr/bin/env python3
"""Agente de evolução contínua, auditável e limitado da Atena.

O agente analisa o repositório, solicita uma proposta estruturada ao modelo
opcional, executa testes locais e publica somente uma proposta de evolução em
uma branch/PR. Ele não faz merge, não altera credenciais e não permite que o
modelo execute comandos ou edite código diretamente.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = os.getenv("ATENA_EVOLUTION_MODEL", "gpt-5-mini")
MAX_FILE_BYTES = 120_000


def run(command: list[str], *, timeout: int = 120, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=timeout, check=check)


def tracked_files() -> list[Path]:
    result = run(["git", "ls-files", "core", "scripts", "tests", ".github/workflows"], timeout=30)
    if result.returncode != 0:
        return []
    paths: list[Path] = []
    for line in result.stdout.splitlines():
        path = ROOT / line.strip()
        if path.is_file() and path.stat().st_size <= MAX_FILE_BYTES:
            paths.append(path)
    return paths


def repository_snapshot() -> dict[str, Any]:
    status = run(["git", "status", "--short"], timeout=30)
    files: dict[str, str] = {}
    for path in tracked_files():
        relative = path.relative_to(ROOT).as_posix()
        try:
            files[relative] = path.read_text(encoding="utf-8", errors="replace")[:MAX_FILE_BYTES]
        except OSError:
            continue
    return {
        "commit": run(["git", "rev-parse", "HEAD"], timeout=30).stdout.strip(),
        "status": status.stdout.splitlines()[:100],
        "files": files,
    }


def run_tests() -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "-q"]
    try:
        result = run(command, timeout=int(os.getenv("ATENA_EVOLUTION_TEST_TIMEOUT", "300")))
        return {
            "command": " ".join(command),
            "returncode": result.returncode,
            "passed": result.returncode == 0,
            "stdout_tail": result.stdout[-6000:],
            "stderr_tail": result.stderr[-3000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {"command": " ".join(command), "returncode": 124, "passed": False, "error": f"timeout: {exc}"}


def fallback_proposal(snapshot: dict[str, Any], tests: dict[str, Any]) -> dict[str, Any]:
    return {
        "objective": "Aumentar capacidade geral, confiabilidade e auditabilidade sem autorreplicação ou merge automático.",
        "priority": "high" if not tests.get("passed") else "medium",
        "insights": [
            {"text": "Manter ciclos de evolução baseados em evidências, testes e revisão humana.", "evidence_refs": [], "confidence": 0.7},
            {"text": "Separar métricas funcionais de alegações de consciência ou AGI.", "evidence_refs": [], "confidence": 0.8},
        ],
        "risks": [
            "Alterações automáticas sem revisão podem introduzir regressões ou ampliar permissões.",
            "Métricas internas não comprovam consciência subjetiva nem AGI.",
        ],
        "proposed_changes": [
            "Adicionar benchmarks independentes para memória, planejamento, uso de ferramentas e resistência a contradições.",
            "Exigir quality gate, testes e aprovação humana antes de qualquer merge.",
        ],
        "next_cycle": [
            "Executar a suíte completa e comparar com a baseline.",
            "Abrir PR somente com relatório, evidências e diff revisável.",
        ],
        "tests": tests,
        "base_commit": snapshot["commit"],
        "generated_by": "deterministic-fallback",
    }


def model_proposal(snapshot: dict[str, Any], tests: dict[str, Any]) -> dict[str, Any] | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from openai import OpenAI

        client = OpenAI()
        compact = {
            "commit": snapshot["commit"],
            "status": snapshot["status"],
            "files": {name: text for name, text in snapshot["files"].items() if name.startswith(("core/", "scripts/", "tests/"))},
            "tests": tests,
        }
        schema = {
            "type": "object",
            "properties": {
                "objective": {"type": "string"},
                "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                "insights": {"type": "array", "items": {"type": "object", "properties": {"text": {"type": "string"}, "evidence_refs": {"type": "array", "items": {"type": "string"}}, "confidence": {"type": "number"}}, "required": ["text", "evidence_refs", "confidence"], "additionalProperties": False}},
                "risks": {"type": "array", "items": {"type": "string"}},
                "proposed_changes": {"type": "array", "items": {"type": "string"}},
                "next_cycle": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["objective", "priority", "insights", "risks", "proposed_changes", "next_cycle"],
            "additionalProperties": False,
        }
        response = client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": "Você é o arquiteto de evolução segura da Atena. Produza somente uma proposta auditável. Não proponha autorreplicação, evasão de controles, execução irrestrita, alteração de credenciais ou merge automático. Não declare consciência ou AGI como fato. Use apenas evidências do snapshot."},
                {"role": "user", "content": json.dumps(compact, ensure_ascii=False)},
            ],
            response_format={"type": "json_schema", "json_schema": {"name": "evolution_proposal", "strict": True, "schema": schema}},
            max_completion_tokens=4000,
        )
        data = json.loads(response.choices[0].message.content)
        data["tests"] = tests
        data["base_commit"] = snapshot["commit"]
        data["generated_by"] = DEFAULT_MODEL
        return data
    except Exception as exc:
        print(f"modelo indisponível; usando fallback determinístico: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None


def write_report(proposal: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(), "proposal": proposal}
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def publish_pr(report: Path, *, branch: str) -> str | None:
    if os.getenv("ATENA_EVOLUTION_PUBLISH", "false").casefold() not in {"1", "true", "yes", "on"}:
        return None
    checkout = run(["git", "checkout", "-B", branch], timeout=30)
    if checkout.returncode != 0:
        raise RuntimeError(checkout.stderr[-2000:])
    run(["git", "add", str(report.relative_to(ROOT))], timeout=30, check=True)
    commit = run(["git", "commit", "-m", "chore(atena): record audited evolution proposal"], timeout=60)
    if commit.returncode not in {0, 1}:
        raise RuntimeError(commit.stderr[-2000:])
    push = run(["git", "push", "--force-with-lease", "origin", f"HEAD:{branch}"], timeout=120)
    if push.returncode != 0:
        raise RuntimeError(push.stderr[-2000:])
    pr = run(["gh", "pr", "create", "--base", "main", "--head", branch, "--title", "chore(atena): audited evolution proposal", "--body-file", str(report)], timeout=120)
    return pr.stdout.strip() if pr.returncode == 0 else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("atena_evolution/agent_reports/latest.json"))
    parser.add_argument("--publish", action="store_true", help="Publica uma proposta em branch/PR; nunca faz merge")
    args = parser.parse_args()
    if args.publish:
        os.environ["ATENA_EVOLUTION_PUBLISH"] = "true"
    snapshot = repository_snapshot()
    tests = run_tests()
    proposal = model_proposal(snapshot, tests) or fallback_proposal(snapshot, tests)
    write_report(proposal, ROOT / args.output)
    pr_url = publish_pr(ROOT / args.output, branch=os.getenv("ATENA_EVOLUTION_BRANCH", "atena/evolution-proposal")) if args.publish else None
    print(json.dumps({"report": str(args.output), "tests_passed": tests.get("passed"), "pr_url": pr_url, "model": proposal.get("generated_by")}, ensure_ascii=False))
    return 0 if tests.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
