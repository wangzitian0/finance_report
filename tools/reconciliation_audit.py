#!/usr/bin/env python3
"""Command wrapper for the EPIC-004 reconciliation audit harness."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "apps" / "backend"
for path in (ROOT_DIR, BACKEND_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import src.models._registry  # noqa: E402, F401  -- register every ORM mapper before relationship config
from src.reconciliation.extension.reconciliation_audit import main  # noqa: E402


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
