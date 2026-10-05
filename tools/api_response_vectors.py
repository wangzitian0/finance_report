#!/usr/bin/env python3
"""Thin shim for API response vector generation."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT_DIR / "apps" / "backend"

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(1, str(BACKEND_ROOT))

from tools._lib import api_response_vectors as _impl  # noqa: E402


def build_vector_files() -> dict[Path, dict[str, Any]]:
    _impl.ROOT_DIR = getattr(sys.modules[__name__], "ROOT_DIR", ROOT_DIR)
    return _impl.build_vector_files()


def main(argv: Sequence[str] | None = None) -> int:
    _this = sys.modules[__name__]
    _impl.ROOT_DIR = getattr(_this, "ROOT_DIR", ROOT_DIR)
    _impl.build_vector_files = getattr(_this, "build_vector_files")
    return _impl.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
