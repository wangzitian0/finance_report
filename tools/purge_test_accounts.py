#!/usr/bin/env python3
"""Purge throwaway test/QA accounts from a staging database (#997 item 4)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "apps" / "backend"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(1, str(BACKEND_DIR))

from tools._lib.dev.purge_test_accounts import main  # noqa: E402

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
