#!/usr/bin/env python3
"""Render package governance summary and exact detail from supplied evidence."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.testing.package_governance import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
