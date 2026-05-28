#!/usr/bin/env python3
"""Compatibility wrapper for common.ssot.check_ssot_ownership."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.ssot import check_ssot_ownership as _impl  # noqa: E402

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_impl.main())

sys.modules[__name__] = _impl
