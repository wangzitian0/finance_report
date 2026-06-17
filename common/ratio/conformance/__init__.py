"""Loader for the language-neutral ratio conformance vectors.

``vectors.json`` is the single percent/ratio standard (#1167) that every ratio
implementation must reproduce — the Python reference (``common/ratio``) and the
TypeScript impl (``apps/frontend/src/lib/ratio``). Each stack loads the same file
and asserts every expected value; divergence (e.g. HALF_UP vs HALF_EVEN) turns CI
red on whichever end drifted.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

VECTORS_PATH = Path(__file__).resolve().parent / "vectors.json"


def load_vectors() -> dict[str, Any]:
    """Return the parsed ratio conformance standard from ``vectors.json``."""
    return json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
