#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "config" / "nanorobotics_sources.json"
payload = json.loads(path.read_text(encoding="utf-8"))
blocked = {"doi.org", "dx.doi.org", "doi.crossref.org"}
kept = []
removed = []
for source in payload.get("sources", []):
    host = source.get("url", "").split("/", 3)[2].lower().removeprefix("www.") if "://" in source.get("url", "") else ""
    if host in blocked:
        removed.append(source.get("url"))
    else:
        kept.append(source)
payload["sources"] = kept
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"removed": removed, "total": len(kept)}, ensure_ascii=False))
