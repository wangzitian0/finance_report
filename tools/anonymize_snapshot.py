#!/usr/bin/env python3
"""Thin shim for database snapshot anonymizer."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools._lib.dev import anonymize_snapshot as _impl  # noqa: E402
from tools._lib.dev.anonymize_snapshot import (  # noqa: E402
    Base as Base,
    ResidualError as ResidualError,
    _get_anonymizer_sha as _get_anonymizer_sha,
    _get_schema_revision as _get_schema_revision,
    _normalize_url as _normalize_url,
    anonymize as anonymize,
    classify_columns as classify_columns,
    scan_for_residuals as scan_for_residuals,
)


def main(argv: Sequence[str] | None = None) -> int:
    _this = sys.modules[__name__]
    for attr in ("anonymize", "scan_for_residuals", "classify_columns"):
        if hasattr(_this, attr):
            setattr(_impl, attr, getattr(_this, attr))
    return _impl.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
