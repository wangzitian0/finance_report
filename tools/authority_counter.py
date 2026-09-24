#!/usr/bin/env python3
"""CODE/LLM authority counter (EPIC-026 AC26.9).

Prints the per-package (EPIC) CODE/LLM distribution and band — a live, on-demand
view (no committed snapshot: the declared-vs-detected reconciliation gate,
tools/check_authority_reconcile.py, is the enforced check; this is the human view).

    python tools/authority_counter.py            # print the table
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.meta.extension.authority_classifier import (  # noqa: E402
    main,
    render_table,
)

__all__ = ["main", "render_table"]

if __name__ == "__main__":
    raise SystemExit(main())
