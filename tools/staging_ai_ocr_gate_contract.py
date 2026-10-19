#!/usr/bin/env python3
"""Thin CLI shim for the staging AI-OCR gate contract."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.testing.staging_ai_ocr_gate_contract import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
