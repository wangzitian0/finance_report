#!/usr/bin/env python3
"""Command wrapper for the one AC-index consistency gate."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.testing.check_ac_index import main  # noqa: E402

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
