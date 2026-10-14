#!/usr/bin/env python3
"""Merge multiple LCOV files by taking the union of coverage.

Delegates core LCOV operations to common.testing.coverage.lcov single source of truth.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from common.testing.coverage.lcov import (
    merge_records,
    parse_lcov_to_records,
    write_lcov,
)

__all__ = ["merge_records", "parse_lcov_to_records", "write_lcov"]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge LCOV files.")
    parser.add_argument("output", type=Path)
    parser.add_argument("inputs", nargs="+", type=Path)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    output_path = args.output
    input_paths = args.inputs

    print(f"Merging {len(input_paths)} LCOV files...")

    all_records = []
    for input_path in input_paths:
        if input_path.exists():
            records = parse_lcov_to_records(input_path)
            all_records.append(records)
            print(f"  {input_path.name}: {len(records)} files")
        else:
            print(f"  Warning: {input_path} not found")

    merged = merge_records(all_records)
    print(f"Merged result: {len(merged)} unique source files")

    write_lcov(merged, output_path)
    print(f"✅ Wrote merged coverage to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
