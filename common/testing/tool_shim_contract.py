"""Shrink-only line-count contract for top-level Python tool entry points."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = REPO_ROOT / "common/testing/data/fat-tool-baseline.json"
BASELINE_UPDATE_MODE = "shrink-only"
MAX_TOOL_LINES = 40


def _fat_tools(repo_root: Path) -> dict[str, int]:
    tools_dir = repo_root / "tools"
    fat_tools: dict[str, int] = {}
    for path in sorted(tools_dir.glob("*.py")):
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > MAX_TOOL_LINES:
            fat_tools[path.relative_to(repo_root).as_posix()] = line_count
    return fat_tools


def _load_baseline(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = payload.get("legacy_fat_tools") if isinstance(payload, dict) else None
    if not isinstance(values, list) or not all(
        isinstance(value, str) for value in values
    ):
        raise ValueError(f"{path}: legacy_fat_tools must be a list of paths")
    return set(values)


def _write_baseline(path: Path, paths: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"legacy_fat_tools": sorted(paths)}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def findings(repo_root: Path, baseline_path: Path) -> tuple[list[str], list[str]]:
    """Return newly fat and resolved-but-still-baselined tool paths."""
    current = _fat_tools(repo_root)
    baseline = _load_baseline(baseline_path)
    new = [
        f"new fat tool: {path} ({current[path]} lines; maximum {MAX_TOOL_LINES})"
        for path in sorted(current.keys() - baseline)
    ]
    stale = [
        f"resolved fat tool still baselined: {path}"
        for path in sorted(baseline - current.keys())
    ]
    return new, stale


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--baseline", type=Path, default=None)
    parser.add_argument(
        "--update",
        action="store_true",
        help="Drop resolved fat-tool paths; refuses to adopt new debt.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    repo_root = args.repo_root.resolve()
    baseline_path = args.baseline or (
        repo_root / DEFAULT_BASELINE.relative_to(REPO_ROOT)
    )
    new, stale = findings(repo_root, baseline_path)
    if new:
        for finding in new:
            print(f"::error title=Tool shim contract::{finding}", file=sys.stderr)
        print(f"[TOOL-SHIM] FAILED: {len(new)} new fat tool(s).", file=sys.stderr)
        return 1
    if args.update:
        _write_baseline(baseline_path, set(_fat_tools(repo_root)))
        print("[TOOL-SHIM] baseline tightened.")
        return 0
    if stale:
        for finding in stale:
            print(f"::error title=Tool shim contract::{finding}", file=sys.stderr)
        print(
            f"[TOOL-SHIM] FAILED: remove {len(stale)} resolved baseline path(s).",
            file=sys.stderr,
        )
        return 1
    print(
        f"[TOOL-SHIM] PASS: top-level tools are <= {MAX_TOOL_LINES} lines or baselined."
    )
    return 0
