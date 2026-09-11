"""Gera uma proposta auditável a partir de resultados do X.

O scanner não executa repositórios, não copia código e não altera a aplicação.
Ele apenas registra posts, URLs GitHub, metadados públicos e critérios para uma
revisão posterior em sandbox/PR.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path

import requests

from core.x_news_research import XNewsResearch, XNotConfigured

GITHUB_RE = re.compile(r"https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")


def github_metadata(owner: str, repo: str) -> dict:
    response = requests.get(
        f"https://api.github.com/repos/{owner}/{repo}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Atena-IA evolution scanner/1.0"},
        timeout=20,
    )
    if response.status_code == 404:
        return {"owner": owner, "repo": repo, "available": False}
    response.raise_for_status()
    data = response.json()
    return {
        "owner": owner,
        "repo": repo,
        "available": True,
        "url": data.get("html_url"),
        "stars": data.get("stargazers_count", 0),
        "forks": data.get("forks_count", 0),
        "license": (data.get("license") or {}).get("spdx_id"),
        "default_branch": data.get("default_branch"),
        "pushed_at": data.get("pushed_at"),
        "description": data.get("description"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="atena_evolution/x_research")
    parser.add_argument("--query", default="(AI OR LLM OR agent OR memory) github.com lang:en")
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat()
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    result = {"generated_at": generated_at, "query": args.query, "status": "ok", "posts": [], "repositories": [], "next_action": "review_in_sandbox_before_any_code_change"}
    try:
        posts = XNewsResearch().search(args.query, args.limit)
    except XNotConfigured as exc:
        result["status"] = "not_configured"
        result["error"] = str(exc)
        posts = []
    seen: set[str] = set()
    for post in posts:
        result["posts"].append({"id": post.post_id, "text": post.text, "url": post.url, "created_at": post.created_at})
        for owner, repo in GITHUB_RE.findall(post.text):
            key = f"{owner.lower()}/{repo.lower()}"
            if key in seen:
                continue
            seen.add(key)
            try:
                result["repositories"].append(github_metadata(owner, repo.rstrip("/")))
            except requests.RequestException as exc:
                result["repositories"].append({"owner": owner, "repo": repo, "available": False, "error": type(exc).__name__})
    result["repositories"].sort(key=lambda item: int(item.get("stars", 0)), reverse=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = out / f"x-scan-{stamp}.json"
    md_path = out / f"x-scan-{stamp}.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Proposta de pesquisa: X → GitHub",
        "",
        f"**Gerado:** {generated_at}",
        f"**Consulta:** `{args.query}`",
        f"**Estado:** `{result['status']}`",
        "",
        "> Este arquivo é uma proposta de investigação. Nenhum repositório externo foi executado ou copiado.",
        "",
        "## Repositórios candidatos",
        "",
    ]
    if result["repositories"]:
        for repo in result["repositories"]:
            lines.append(f"- [{repo.get('owner')}/{repo.get('repo')}]({repo.get('url', '')}) — estrelas: {repo.get('stars', 0)}; licença: {repo.get('license') or 'não informada'}; branch: {repo.get('default_branch') or 'n/d'}")
    else:
        lines.append("Nenhum repositório candidato foi encontrado; a ausência de token ou de resultados não é tratada como evidência de que não existam projetos.")
    lines.extend(["", "## Próximas etapas obrigatórias", "", "1. Fixar o commit analisado.", "2. Verificar licença, dependências e secrets.", "3. Testar em sandbox isolada.", "4. Comparar benchmarks da Atena.", "5. Abrir PR de código somente com evidências e revisão humana."])
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "posts": len(result["posts"]), "repositories": len(result["repositories"]), "json": str(json_path), "markdown": str(md_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
