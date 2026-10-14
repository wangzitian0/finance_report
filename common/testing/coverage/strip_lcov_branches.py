#!/usr/bin/env python3
"""Build a line-only LCOV file for reporting tools that blend branch counters."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from common.testing.coverage.lcov import (
    BRANCH_RECORD_PREFIXES,
    is_branch_record,
    strip_branches,
)

__all__ = ["BRANCH_RECORD_PREFIXES", "is_branch_record", "strip_lcov_branches"]


def strip_lcov_branches(input_path: Path, output_path: Path) -> int:
    """Copy LCOV input to output without branch coverage records."""
    return strip_branches(input_path, output_path)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strip branch records from LCOV.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    return strip_lcov_branches(args.input, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
