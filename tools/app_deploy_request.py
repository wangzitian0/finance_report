#!/usr/bin/env python3
"""Render a validated Finance Report fixed-environment request without side effects."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.runtime.deploy.app_deploy_request import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
