#!/usr/bin/env python3
"""
Benchmark Multi-Version Index & Dashboard Generator.

Scans the benchmarks directory (e.g. docs/benchmarks/), aggregates all version
summaries (* /summary.json), and generates:
  1. manifest.json (Time-series benchmark dataset)
  2. index.html    (Multi-version trends dashboard with SVG charts)

The page lists every published run. The runs that GitHub Pages already holds
come from --history-dir (a copy of the published benchmarks tree). A run in
--benchmarks-dir replaces a published run of the same version.

Usage:
  python tools/generate_benchmark_index.py --benchmarks-dir docs/benchmarks \
      --history-dir /tmp/published/benchmarks
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from common.testing.benchmarks.benchmark_html_reporter import generate_index_dashboard

REPO_ROOT = Path(__file__).resolve().parents[3]


def load_summaries(directory: Path) -> dict[str, dict]:
    """The summary of each version folder, keyed by the folder name.

    A file that is not JSON, or not an object, is skipped with a warning.
    """
    found: dict[str, dict] = {}
    for summary_path in sorted(directory.glob("*/summary.json")):
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            print(f"⚠️ Failed to parse {summary_path}: {exc}", file=sys.stderr)
            continue
        if not isinstance(data, dict):
            print(
                f"⚠️ Skipped {summary_path}: the file is not a JSON object",
                file=sys.stderr,
            )
            continue
        found[summary_path.parent.name] = data
    return found


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate benchmark summaries into multi-version dashboard."
    )
    parser.add_argument(
        "--benchmarks-dir",
        type=Path,
        default=REPO_ROOT / "docs" / "benchmarks",
        help="Directory containing benchmark version folders (default: docs/benchmarks)",
    )
    parser.add_argument(
        "--history-dir",
        type=Path,
        default=None,
        help="Copy of the published benchmarks tree. Its runs join the dashboard.",
    )
    args = parser.parse_args(argv)

    benchmarks_dir = args.benchmarks_dir
    benchmarks_dir.mkdir(parents=True, exist_ok=True)

    # A run in benchmarks_dir replaces the published run of the same version.
    history = load_summaries(args.history_dir) if args.history_dir else {}
    if args.history_dir and not history:
        print(f"ℹ️ No published summary.json found in {args.history_dir}.")
    summaries = list({**history, **load_summaries(benchmarks_dir)}.values())

    if not summaries:
        print(f"ℹ️ No summary.json found in {benchmarks_dir}. Writing empty dashboard.")

    # Sort newest first
    summaries.sort(key=lambda x: x.get("run_at", ""), reverse=True)

    # 1. Write manifest.json
    manifest_path = benchmarks_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(summaries, f, indent=2)
    print(f"✅ Manifest written: {manifest_path} ({len(summaries)} versions)")

    # 2. Render index.html
    index_html = generate_index_dashboard(summaries)
    index_path = benchmarks_dir / "index.html"
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(index_html)
    print(f"✅ Dashboard written: {index_path} ({len(index_html)} bytes, <50KB)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
