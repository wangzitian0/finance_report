#!/usr/bin/env python3
"""Compatibility wrapper for common.ci.github_workflow_timing_summary."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.ci import github_workflow_timing_summary as _impl  # noqa: E402

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_impl.main())

sys.modules[__name__] = _impl
