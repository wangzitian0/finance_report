"""Loader for the language-neutral money conformance vectors.

``vectors.json`` is the single financial standard (#1167) that **every** money
implementation must reproduce — the Python reference impl in ``common/audit/money`` and
the TypeScript impl in ``apps/frontend/src/lib/audit/money``. Each stack loads the same
file and asserts every expected value; divergence (e.g. HALF_UP vs HALF_EVEN
rounding) turns CI red on whichever end drifted.

This module is the Python-side accessor. The TS side reads the same JSON directly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

VECTORS_PATH = Path(__file__).resolve().parent / "vectors.json"


def load_vectors() -> dict[str, Any]:
    """Return the parsed conformance standard from ``vectors.json``."""
    return json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
