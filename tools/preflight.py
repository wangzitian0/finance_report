#!/usr/bin/env python3
"""Command wrapper for the diff-aware pre-push verification dispatcher.

Run the gate checks relevant to your current diff before pushing:

    python tools/preflight.py            # run the relevant gates
    python tools/preflight.py --list     # show what would run, don't run it
    python tools/preflight.py --base origin/main

Run it with an interpreter that has the project deps (e.g. the backend venv) so
the sub-checks can import their dependencies.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.testing.preflight import main  # noqa: E402

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
