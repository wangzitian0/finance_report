#!/usr/bin/env python3
"""CLI wrapper for common.testing.mutation_check (#2448)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.testing.mutation_check import main  # noqa: E402

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
