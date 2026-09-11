#!/usr/bin/env python3
"""Validate PR checks and required modules before a safe GitHub merge."""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
from typing import Any

REPO_DEFAULT = "danilosullos-lang/Atena-IA"
REQUIRED_FILES = (
    "core/evolution_quality_gate.py",
    "core/atena_llm_router.py",
    "core/provider_quota.py",
    "core/agent_plan_loop.py",
    "core/identity_state.py",
    "core/sensemaking.py",
    "core/tool_broker.py",
    "core/tool_contracts.py",
    "scripts/run_tool_augmented_benchmark.py",
    "scripts/run_resilient_structured_benchmark.py",
    "scripts/evaluate_structured_benchmark.py",
)
ESSENTIAL_CHECK_TERMS = ("ATENA CI", "Testes e smoke test")


def run(*args: str) -> str:
    env = dict(__import__('os').environ)
    env['GH_FORCE_TTY'] = '0'
    p = subprocess.run(args, text=True, capture_output=True, env=env)
    if p.returncode:
        raise RuntimeError(f"comando falhou ({p.returncode}): {' '.join(args)}\n{p.stderr.strip()}")
    return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", p.stdout)


def gh_json(*args: str) -> Any:
    return json.loads(run("gh", *args))


def current_checks(repo: str, pr_number: int) -> list[dict[str, Any]]:
    """Lê os checks atuais mesmo quando gh pr checks retorna exit 1."""
    env = dict(__import__('os').environ)
    env['GH_FORCE_TTY'] = '0'
    command = [
        "gh", "pr", "checks", str(pr_number), "--repo", repo,
        "--json", "name,state,workflow,bucket,link",
    ]
    result = subprocess.run(command, text=True, capture_output=True, env=env)
    output = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", result.stdout)
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"não foi possível interpretar checks do PR: {exc}") from exc
    return value if isinstance(value, list) else []


def exists(repo: str, path: str, ref: str) -> bool:
    p = subprocess.run(["gh", "api", f"repos/{repo}/contents/{path}?ref={ref}"], capture_output=True, text=True)
    return p.returncode == 0


def known_vercel_failure(name: str, state: str) -> bool:
    return "VERCEL" in name.upper() and state == "FAILURE"


def validate(args: argparse.Namespace) -> tuple[dict[str, Any], bool]:
    pr = gh_json("pr", "view", str(args.pr), "--repo", args.repo, "--json", "number,state,mergeable,mergeStateStatus,isDraft,headRefName,baseRefName,url")
    head = pr["headRefName"]
    base = pr["baseRefName"]
    checks = []
    for item in current_checks(args.repo, args.pr):
        check_name = str(item.get("name") or "")
        workflow_name = str(item.get("workflow") or "")
        checks.append({
            "name": check_name,
            "display_name": f"{workflow_name} / {check_name}" if workflow_name else check_name,
            "state": str(item.get("state") or "").upper(),
            "workflow": str(item.get("workflow") or ""),
            "bucket": str(item.get("bucket") or ""),
            "link": str(item.get("link") or ""),
        })
    missing_on_head = [p for p in REQUIRED_FILES if not exists(args.repo, p, head)]
    essential_failures = [term for term in ESSENTIAL_CHECK_TERMS if not any(term.lower() in c.get("display_name", c["name"]).lower() and c["state"] == "SUCCESS" for c in checks)]
    blocking_states = {"FAILURE", "ERROR", "CANCELLED", "PENDING", "IN_PROGRESS", "QUEUED", "REQUESTED"}
    failures = [c for c in checks if c["state"] in blocking_states and not (args.allow_vercel_rate_limit_failures and known_vercel_failure(c["name"], c["state"]))]
    report = {"pr": pr.get("number"), "url": pr.get("url"), "state": pr.get("state"), "head": head, "base": base, "mergeable": pr.get("mergeable"), "merge_state": pr.get("mergeStateStatus"), "missing_on_head": missing_on_head, "essential_failures": essential_failures, "unexpected_failures": failures, "checks": checks}
    ok = pr.get("state") == "OPEN" and not pr.get("isDraft") and pr.get("mergeable") != "CONFLICTING" and not missing_on_head and not essential_failures and not failures
    return report, ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=REPO_DEFAULT)
    ap.add_argument("--pr", type=int, required=True)
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--allow-vercel-rate-limit-failures", action="store_true")
    ap.add_argument("--report")
    args = ap.parse_args()
    try:
        report, ok = validate(args)
    except (RuntimeError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    if not ok:
        print("MERGE_BLOCKED: pré-condições não atendidas", file=sys.stderr)
        return 1
    if not args.merge:
        print("DRY_RUN_OK: PR pronto para merge")
        return 0
    try:
        run("gh", "pr", "merge", str(args.pr), "--repo", args.repo, "--squash", "--delete-branch", "--subject", "feat(atena): integrate validated runtime", "--body", "Merged after module and CI validation.")
        print("MERGED_OK")
    except RuntimeError as exc:
        print(f"MERGE_FAILED: {exc}", file=sys.stderr)
        return 3
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
