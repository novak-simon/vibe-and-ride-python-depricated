from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.jamendo_importer import run_importer


def main() -> None:
    failed = run_importer()
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()