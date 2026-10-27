#!/usr/bin/env python3
"""Thin shim for API response vector generation."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT_DIR / "apps" / "backend"

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(1, str(BACKEND_ROOT))

from common.platform.api_response_vectors import (  # noqa: E402, F401
    build_vector_files as build_vector_files,
    main,
)

if __name__ == "__main__":
    raise SystemExit(main())
