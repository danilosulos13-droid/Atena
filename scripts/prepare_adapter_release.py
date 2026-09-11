#!/usr/bin/env python3
"""Versiona o adapter promovido e gera um manifesto verificável."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVOLUTION = ROOT / "atena_evolution"
ACTIVE = EVOLUTION / "models" / "active"
RELEASES = EVOLUTION / "models" / "releases"
MANIFEST = EVOLUTION / "models" / "active_manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    files = sorted(path for path in ACTIVE.rglob("*") if path.is_file()) if ACTIVE.is_dir() else []
    if not files:
        print(json.dumps({"status": "missing", "reason": "adapter ativo vazio"}))
        return 0
    release_id = os.getenv("GITHUB_RUN_ID", "local") + "-" + os.getenv("GITHUB_SHA", "unknown")[:12]
    release_dir = RELEASES / release_id
    if release_dir.exists():
        shutil.rmtree(release_dir)
    release_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ACTIVE, release_dir)
    manifest = {
        "status": "active",
        "release_id": release_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_model": os.getenv("ATENA_TRAIN_MODEL", ""),
        "active_path": "atena_evolution/models/active",
        "release_path": f"atena_evolution/models/releases/{release_id}",
        "files": [
            {
                "path": str(path.relative_to(ACTIVE)),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in files
        ],
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "release_id": release_id, "files": len(files), "manifest": str(MANIFEST)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
