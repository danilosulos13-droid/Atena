#!/usr/bin/env python3
"""Rotaciona e comprime logs da Atena por tamanho, preservando retenção limitada."""
from __future__ import annotations

import argparse
import gzip
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def rotate_file(path: Path, max_bytes: int, keep: int) -> dict[str, object]:
    if not path.exists() or not path.is_file() or path.name.endswith(".gz"):
        return {"path": str(path), "rotated": False, "reason": "missing_or_not_plain_file"}
    size = path.stat().st_size
    if size <= max_bytes:
        return {"path": str(path), "rotated": False, "reason": "below_limit", "size_bytes": size}

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = path.with_name(f"{path.name}.{stamp}.gz")
    with path.open("rb") as source, gzip.open(archive, "wb", compresslevel=6) as target:
        shutil.copyfileobj(source, target)
    path.write_bytes(b"")

    archives = sorted(
        (item for item in path.parent.glob(f"{path.name}.*.gz") if item.is_file()),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    removed = []
    for old in archives[keep:]:
        old.unlink()
        removed.append(str(old))
    return {
        "path": str(path),
        "rotated": True,
        "size_before_bytes": size,
        "archive": str(archive),
        "removed": removed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-dir", type=Path, default=Path("atena_evolution/logs"))
    parser.add_argument("--file", action="append", dest="files", default=[])
    parser.add_argument("--max-mb", type=int, default=10)
    parser.add_argument("--keep", type=int, default=5)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.max_mb < 1 or args.keep < 1:
        raise SystemExit("--max-mb e --keep devem ser positivos")

    paths = [args.log_dir / name for name in args.files] if args.files else sorted(args.log_dir.glob("*.log"))
    report = {
        "ok": True,
        "max_bytes": args.max_mb * 1024 * 1024,
        "keep": args.keep,
        "files": [rotate_file(path, args.max_mb * 1024 * 1024, args.keep) for path in paths],
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
