#!/usr/bin/env python3
"""Verify frontend generated API types and operations without /tmp races."""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.platform.check_api_types import main  # noqa: E402

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
