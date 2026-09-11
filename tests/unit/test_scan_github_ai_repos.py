from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "scan_github_ai_repos.py"
    spec = importlib.util.spec_from_file_location("scan_github_ai_repos", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _make_repo(mod, full_name, stars, *, forks=1, open_issues=1, language="Python",
                topics=None, license_spdx="MIT", description="An autonomous AI agent."):
    now = datetime.now(timezone.utc)
    iso = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return mod.RepoSnapshot(
        full_name=full_name,
        html_url=f"https://github.com/{full_name}",
        description=description,
        stars=stars,
        forks=forks,
        watchers=stars,
        open_issues=open_issues,
        language=language,
        topics=topics or ["ai", "agent", "llm"],
        license_spdx=license_spdx,
        created_at=iso(now - timedelta(days=200)),
        updated_at=iso(now - timedelta(days=1)),
        pushed_at=iso(now - timedelta(days=1)),
    )


def test_rank_repos_orders_by_total_score_descending():
    mod = _load_module()
    repos = [
        _make_repo(mod, "org/low", stars=5),
        _make_repo(mod, "org/high", stars=5000),
        _make_repo(mod, "org/mid", stars=200),
    ]

    ranked = mod.rank_repos(repos, top_n=10)

    assert len(ranked) == 3
    scores = [r.total_score for r in ranked]
    assert scores == sorted(scores, reverse=True)
    assert ranked[0].full_name == "org/high"


def test_write_watchlist_writes_expected_payload(tmp_path, monkeypatch):
    mod = _load_module()

    watchlist_path = tmp_path / "docs" / "ai_repo_watchlist.json"
    monkeypatch.setattr(mod, "WATCHLIST_PATH", watchlist_path)
    monkeypatch.setattr(mod, "DELTA_CACHE_PATH", tmp_path / "delta_cache.json")

    repos = [
        _make_repo(mod, "org/x", stars=999),
        _make_repo(mod, "org/y", stars=500),
    ]
    for repo in repos:
        repo.compute_scores(max_stars=999)
        repo.compute_themes()

    output = mod.write_watchlist(repos, source="unit-test", queries=["test query"])

    assert watchlist_path.exists()
    payload = json.loads(watchlist_path.read_text(encoding="utf-8"))
    assert payload["count"] == 2
    assert payload["repos"][0]["full_name"] in {"org/x", "org/y"}
    assert output["count"] == len(repos)
