"""Sync CI test durations from GitHub Actions JUnit artifacts or local directories.

SSOT Single Source of Truth for CI test duration seeds:
- apps/backend/ci/backend-test-durations.json
- ci/tooling-test-durations.json

Reads executed JUnit XML files, converts testcases to canonical node IDs,
updates duration seeds, and computes shard balance reports.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from xml.etree import ElementTree

from common.testing.backend_shard import (
    discover_test_files,
    file_durations,
    split_files,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def case_to_node_id(case: ElementTree.Element) -> str:
    """Convert a JUnit testcase element to a pytest-split node ID."""
    cls = case.get("classname", "")
    name = case.get("name", "")
    parts = cls.split(".")
    file_parts: list[str] = []
    class_parts: list[str] = []
    for p in parts:
        if class_parts or (file_parts and file_parts[-1].startswith("test_")):
            class_parts.append(p)
        else:
            file_parts.append(p)
    file_path = "/".join(file_parts) + ".py"
    if class_parts:
        return f"{file_path}::{'::'.join(class_parts)}::{name}"
    return f"{file_path}::{name}"


def extract_durations_from_xmls(xml_paths: Sequence[Path]) -> dict[str, float]:
    """Extract node_id -> duration mapping from a sequence of JUnit XML files."""
    durations: dict[str, float] = {}
    for path in xml_paths:
        if not path.is_file():
            continue
        try:
            tree = ElementTree.parse(path)
        except ElementTree.ParseError:
            continue
        for case in tree.iter("testcase"):
            nid = case_to_node_id(case)
            t = round(float(case.get("time", 0.0)), 3)
            durations[nid] = t
    return durations


def update_duration_seed(
    seed_file: Path,
    new_durations: dict[str, float],
    dry_run: bool = False,
) -> tuple[int, int]:
    """Merge new durations into seed file and save sorted compact JSON."""
    data: dict[str, float] = {}
    if seed_file.exists():
        data = json.loads(seed_file.read_text(encoding="utf-8"))

    updated_count = 0
    for nid, t in new_durations.items():
        data[nid] = t
        updated_count += 1

    sorted_data = dict(sorted(data.items()))
    if not dry_run:
        seed_file.parent.mkdir(parents=True, exist_ok=True)
        seed_file.write_text(
            json.dumps(sorted_data, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    return len(sorted_data), updated_count


def report_backend_balance(
    backend_root: Path,
    durations: dict[str, float],
    splits: int = 4,
) -> None:
    """Print partition balance report for backend shards."""
    per_file = file_durations(durations)
    all_files = discover_test_files(backend_root)
    partitions = split_files(all_files, per_file, splits=splits)
    print(f"\n--- Backend Shard Partition Balance ({splits} splits) ---")
    totals = []
    for i, group in enumerate(partitions, 1):
        total = sum(per_file.get(f, 0.0) for f in group)
        totals.append(total)
        print(f"Shard {i}: {len(group):>3} files, estimated {total:>6.2f}s")
    if totals:
        max_t = max(totals)
        min_t = min(totals)
        spread = max_t - min_t
        print(f"Spread: {spread:.2f}s (max={max_t:.2f}s, min={min_t:.2f}s)")


def sync_from_directory(
    junit_root: Path,
    repo_root: Path,
    dry_run: bool = False,
) -> None:
    """Find XMLs in directory and update both duration seeds."""
    backend_xmls = sorted(
        set(junit_root.glob("backend-shard-*-test-context/**/*.xml"))
        | set(junit_root.glob("backend-shard-*-test-context/*.xml"))
    )
    tooling_xmls = sorted(
        set(junit_root.glob("coverage-tooling-*/**/*.xml"))
        | set(junit_root.glob("coverage-tooling-*/*.xml"))
    )

    if backend_xmls:
        b_durations = extract_durations_from_xmls(backend_xmls)
        b_seed = repo_root / "apps" / "backend" / "ci" / "backend-test-durations.json"
        total, updated = update_duration_seed(b_seed, b_durations, dry_run=dry_run)
        print(
            f"Backend: {len(backend_xmls)} XMLs -> {updated} tests updated, total {total} in seed."
        )
        report_data = (
            json.loads(b_seed.read_text(encoding="utf-8"))
            if b_seed.exists()
            else b_durations
        )
        report_backend_balance(
            repo_root / "apps" / "backend",
            report_data,
        )
    else:
        print("Backend: no backend-shard XML files found in directory.")

    if tooling_xmls:
        t_durations = extract_durations_from_xmls(tooling_xmls)
        t_seed = repo_root / "ci" / "tooling-test-durations.json"
        total, updated = update_duration_seed(t_seed, t_durations, dry_run=dry_run)
        print(
            f"Tooling: {len(tooling_xmls)} XMLs -> {updated} tests updated, total {total} in seed."
        )
    else:
        print("Tooling: no coverage-tooling XML files found in directory.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-id",
        type=int,
        help="GitHub Actions run ID to download artifacts from via gh cli",
    )
    parser.add_argument(
        "--junit-dir",
        type=Path,
        help="Local directory containing downloaded JUnit XML artifacts",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root directory (default: current checkout)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and report without writing to seed files",
    )

    args = parser.parse_args(argv)

    if not args.run_id and not args.junit_dir:
        parser.error("Either --run-id or --junit-dir must be specified")

    if args.run_id:
        temp_dir = Path(tempfile.mkdtemp(prefix=f"ci_run_{args.run_id}_"))
        try:
            print(f"Downloading artifacts for run {args.run_id} to {temp_dir}...")
            subprocess.run(
                [
                    "gh",
                    "run",
                    "download",
                    str(args.run_id),
                    "-p",
                    "backend-shard-*",
                    "-p",
                    "coverage-tooling-*",
                    "--dir",
                    str(temp_dir),
                ],
                check=True,
            )
            sync_from_directory(temp_dir, args.repo_root, dry_run=args.dry_run)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    else:
        sync_from_directory(args.junit_dir, args.repo_root, dry_run=args.dry_run)

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
