#!/usr/bin/env python3
"""Command wrapper for real-corpus re-verification against live extraction (#1744)."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
BACKEND_DIR = ROOT_DIR / "apps" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(1, str(BACKEND_DIR))

from common.testing.reverify_real_corpus import run as _reverify_main  # noqa: E402
from tools._lib.reverify_real_corpus import _live_extractor  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    return _reverify_main(argv, live_extractor=_live_extractor)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
