"""File-level least-duration split for the backend CI shards.

pytest-split balances test *items*, so every shard first imports and collects
the whole backend suite (~3,500 tests) only to keep one eighth of it. On a
2-core hosted runner under ``--cov-branch`` that collection alone took 40-60 s
per shard (#2050). This module assigns whole test *files* to shards with the
same seeded ``least_duration`` rule, so each shard passes pytest only its own
files and collects only those.

Every ``tests/**/test_*.py`` file under the backend root is assigned to exactly
one shard, which is a superset of what ``testpaths = ["tests"]`` plus
``python_files = ["test_*.py"]`` collects; marker deselection still happens in
pytest. Stdlib only: the workflow runs this before any dependency install.
"""

from __future__ import annotations

import argparse
import heapq
import json
import statistics
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

LEAST_DURATION = "least_duration"
TEST_FILE_GLOB = "test_*.py"


def discover_test_files(backend_root: Path, tests_dir: str = "tests") -> list[str]:
    """Every pytest-collectable test file, as a backend-root-relative POSIX path."""
    root = backend_root / tests_dir
    return sorted(
        path.relative_to(backend_root).as_posix()
        for path in root.rglob(TEST_FILE_GLOB)
        if path.is_file() and "__pycache__" not in path.parts
    )


def file_durations(durations: Mapping[str, float]) -> dict[str, float]:
    """Sum a pytest-split node-id duration seed per test file."""
    totals: dict[str, float] = {}
    for node_id, seconds in durations.items():
        path = node_id.split("::", 1)[0]
        totals[path] = totals.get(path, 0.0) + float(seconds)
    return totals


def split_files(
    files: Iterable[str],
    durations: Mapping[str, float],
    splits: int,
) -> list[list[str]]:
    """Assign each file to the currently lightest shard, heaviest file first.

    A file absent from the seed (new, or fully deselected by markers) weighs
    the median seeded file. Ties break on the path, so the split is a pure
    function of its inputs and every shard computes the same partition.
    """
    if splits < 1:
        raise ValueError("splits must be at least 1")
    unique_files = sorted(set(files))
    per_file = file_durations(durations)
    seeded = [per_file[path] for path in unique_files if path in per_file]
    default = statistics.median(seeded) if seeded else 1.0
    weight = {path: per_file.get(path, default) for path in unique_files}

    heap = [(0.0, index) for index in range(splits)]
    groups: list[list[str]] = [[] for _ in range(splits)]
    for path in sorted(unique_files, key=lambda item: (-weight[item], item)):
        total, index = heapq.heappop(heap)
        groups[index].append(path)
        heapq.heappush(heap, (total + weight[path], index))
    return [sorted(group) for group in groups]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--splits", type=int, required=True)
    parser.add_argument("--group", type=int, required=True)
    parser.add_argument(
        "--splitting-algorithm", choices=[LEAST_DURATION], default=LEAST_DURATION
    )
    parser.add_argument("--durations-path", type=Path, required=True)
    parser.add_argument(
        "--backend-root",
        type=Path,
        default=Path.cwd(),
        help="Directory containing tests/ and the seed path (default: cwd).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not 1 <= args.group <= args.splits:
        print(f"--group must be within 1..{args.splits}", file=sys.stderr)
        return 2
    seed_path = args.durations_path
    if not seed_path.is_absolute():
        seed_path = args.backend_root / seed_path
    durations = json.loads(seed_path.read_text(encoding="utf-8"))
    files = discover_test_files(args.backend_root)
    if not files:
        print(f"no {TEST_FILE_GLOB} files under {args.backend_root}", file=sys.stderr)
        return 1
    for path in split_files(files, durations, args.splits)[args.group - 1]:
        print(path)
    return 0
