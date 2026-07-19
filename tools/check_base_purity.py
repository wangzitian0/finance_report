#!/usr/bin/env python3
"""Command wrapper for the base-purity shrink-only gate."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.meta.extension.check_base_purity import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
