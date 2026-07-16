#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) in sys.path:
    sys.path.remove(str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR))

from tools._lib.market_data.seed_fx_rates import main  # noqa: E402

if str(ROOT_DIR) in sys.path:
    sys.path.remove(str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR))

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
