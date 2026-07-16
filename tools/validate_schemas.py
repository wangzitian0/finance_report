#!/usr/bin/env python3
"""Command wrapper for Pydantic schema validation."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "apps" / "backend"
for path in (ROOT_DIR, BACKEND_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from src.runtime.extension.schema_validation import main  # noqa: E402

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
