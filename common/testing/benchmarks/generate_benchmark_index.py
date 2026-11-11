#!/usr/bin/env python3
"""Benchmark Multi-Version Index & Dashboard Generator."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from common.testing.benchmarks.benchmark_html_reporter import (
    generate_index_dashboard,
    sanitize_for_json,
    write_utf8_atomic,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def load_summaries(directory: Path) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for path in sorted(directory.glob("*/summary.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"Failed to parse {path}: {exc}", file=sys.stderr)
            continue
        if not isinstance(data, dict):
            print(f"Skipped {path}: the file is not a JSON object", file=sys.stderr)
            continue
        found[path.parent.name] = data
    return found


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--benchmarks-dir", type=Path, default=REPO_ROOT / "docs" / "benchmarks"
    )
    parser.add_argument("--history-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    bdir: Path = args.benchmarks_dir
    bdir.mkdir(parents=True, exist_ok=True)
    history = load_summaries(args.history_dir) if args.history_dir else {}
    summaries = sorted(
        {**history, **load_summaries(bdir)}.values(),
        key=lambda x: str(x.get("run_at") or ""),
        reverse=True,
    )
    safe = sanitize_for_json(summaries)
    write_utf8_atomic(bdir / "manifest.json", json.dumps(safe, indent=2))
    write_utf8_atomic(bdir / "index.html", generate_index_dashboard(safe))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
