#!/usr/bin/env python3
"""Compatibility wrapper for common.coverage.policy."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.coverage.policy import *  # noqa: E402,F401,F403
