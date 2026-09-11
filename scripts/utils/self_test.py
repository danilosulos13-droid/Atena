from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.atena_self_test import main as self_test_main


def main() -> int:
    return self_test_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
