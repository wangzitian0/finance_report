"""Loader for the shared unit-price conformance vectors."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_vectors() -> dict[str, Any]:
    return json.loads(
        (Path(__file__).with_name("vectors.json")).read_text(encoding="utf-8")
    )
