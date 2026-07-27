#!/usr/bin/env python3
"""Command wrapper for the Finance Report post-deploy health check."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.runtime.health_check import main  # noqa: E402


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
