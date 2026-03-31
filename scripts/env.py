#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from frida_analykit.env import repo_cli_main


def main(argv: list[str] | None = None) -> int:
    return repo_cli_main(argv, repo_root=PROJECT_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
