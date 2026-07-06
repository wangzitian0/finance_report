#!/usr/bin/env python3
"""Build a line-only LCOV file for reporting tools that blend branch counters."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


BRANCH_RECORD_PREFIXES = ("BRDA:", "BRF:", "BRH:")


def is_branch_record(line: str) -> bool:
    """Return True for LCOV branch detail or branch summary records."""
    return line.startswith(BRANCH_RECORD_PREFIXES)


def strip_lcov_branches(input_path: Path, output_path: Path) -> int:
    """Copy LCOV input to output without branch coverage records."""
    if not input_path.exists():
        print(f"LCOV input not found: {input_path}", file=sys.stderr)
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with (
        open(input_path, "r", encoding="utf-8") as source,
        open(output_path, "w", encoding="utf-8") as target,
    ):
        for line in source:
            if is_branch_record(line):
                continue
            target.write(line)

    print(f"Wrote line-only LCOV to {output_path}")
    return 0


def parse_args(argv: list[str] | tuple[str, ...]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strip branch records from LCOV.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | tuple[str, ...] | None = None) -> None:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    sys.exit(strip_lcov_branches(args.input, args.output))


if __name__ == "__main__":
    main()
