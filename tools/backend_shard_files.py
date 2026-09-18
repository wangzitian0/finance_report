#!/usr/bin/env python3
"""Print the backend test files one CI shard runs (file-level split)."""

import sys
from collections.abc import Sequence
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))


def main(argv: Sequence[str] | None = None) -> int:
    from common.testing.backend_shard import main as shard_main

    return shard_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
