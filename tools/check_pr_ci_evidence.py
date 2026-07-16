#!/usr/bin/env python3
"""Thin wrapper for common.testing.check_pr_ci_evidence (issue #1557)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.testing.check_pr_ci_evidence import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
