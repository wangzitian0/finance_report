#!/usr/bin/env python3
"""Thin CLI shim for the Tier-2 deployed HTTP E2E probe."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.runtime.tier2_http_e2e import *  # noqa: E402,F403
from common.runtime.tier2_http_e2e import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
