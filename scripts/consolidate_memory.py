#!/usr/bin/env python3
"""Consolida a memória JSON da Atena sem apagar o histórico bruto."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.memory_consolidation import consolidate_cycles


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--replace-input", action="store_true", help="substitui o JSON pelo consolidado; requer --backup")
    args = parser.parse_args()

    if args.replace_input and not args.backup:
        parser.error("--replace-input exige --backup")
    if not args.input.exists():
        raise SystemExit(f"memória não encontrada: {args.input}")
    data = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit("a memória bruta precisa ser uma lista JSON")

    consolidated = consolidate_cycles(data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(consolidated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.replace_input:
        args.backup.parent.mkdir(parents=True, exist_ok=True)
        if not args.backup.exists():
            shutil.copy2(args.input, args.backup)
        args.input.write_text(json.dumps(consolidated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "input": str(args.input),
        "output": str(args.output),
        "cycles": len(data),
        "unique_insights": len(consolidated["insights"]),
        "unique_risks": len(consolidated["risks"]),
        "unique_next_cycle": len(consolidated["next_cycle"]),
        "unique_proposals": len(consolidated["proposals"]),
        "replaced_input": args.replace_input,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
