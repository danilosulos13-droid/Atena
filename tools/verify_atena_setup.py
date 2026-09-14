#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from core.benchmark_scoring import load_weights
    from core.nanorobotics_learning import load_config

    weights = load_weights(ROOT / "benchmarks" / "weights_v1.json")
    model_files = []
    for pattern in ("*.safetensors", "*.pt", "*.pth", "*.onnx", "*.bin"):
        model_files.extend(path for path in ROOT.rglob(pattern) if ".venv" not in path.parts and ".git" not in path.parts)
    sources = load_config(ROOT / "config" / "nanorobotics_sources.json")
    test = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/unit/test_nanorobotics_learning.py", "tests/unit/test_research_sources.py", "-q"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    payload = {
        "python": sys.version,
        "weights_version": weights.get("version"),
        "weights": weights["components"],
        "gates": weights.get("gates", {}),
        "neural_checkpoint_files": [str(path.relative_to(ROOT)) for path in sorted(model_files)],
        "nanorobotics_source_count": len(sources),
        "pytest_returncode": test.returncode,
        "pytest_stdout": test.stdout[-4000:],
        "pytest_stderr": test.stderr[-4000:],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return test.returncode


if __name__ == "__main__":
    raise SystemExit(main())
