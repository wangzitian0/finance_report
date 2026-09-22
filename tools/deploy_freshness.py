#!/usr/bin/env python3
"""Command wrapper for the deployed-environment freshness check.

Fails when staging or production serves a release whose oldest undeployed
``main`` commit is older than the environment's bound. See
``common/runtime/deploy_freshness.py`` and ``.github/workflows/deploy-freshness.yml``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.runtime.deploy_freshness import main  # noqa: E402

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
