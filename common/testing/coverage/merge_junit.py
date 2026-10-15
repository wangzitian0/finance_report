"""Merge JUnit XML reports from multiple shards into a single report.

Concatenates <testsuite> elements under a single <testsuites> root element.
Delegates core JUnit merging to common.testing.coverage.junit single source of truth.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from common.testing.coverage.junit import merge_junit_files

__all__ = ["merge_junit_files"]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge JUnit XML files into one.")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        dest="output_flag",
        default=None,
        help="Path to output JUnit XML file",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=None,
        help="Directory containing JUnit XML shards",
    )
    parser.add_argument(
        "--pattern",
        type=str,
        default="*.xml",
        help="File pattern to match when using --input-dir (default: *.xml)",
    )
    parser.add_argument(
        "positional_args",
        nargs="*",
        type=Path,
        help="Positional args: [output] inputs... or inputs...",
    )
    args = parser.parse_args(argv)

    output_path: Path | None = args.output_flag
    input_paths: list[Path] = []

    if args.input_dir:
        input_paths.extend(sorted(args.input_dir.glob(args.pattern)))

    pos = list(args.positional_args)
    if output_path is None:
        if not pos:
            print("Error: no output path specified (use --output or positional output)")
            return 1
        output_path = pos.pop(0)

    input_paths.extend(pos)

    if not input_paths:
        print("Error: no input files provided")
        return 1

    return merge_junit_files(input_paths, output_path)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
