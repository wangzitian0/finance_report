"""Zero-debt line-count and alias contract for top-level Python tool entry points."""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAX_TOOL_LINES = 40


def _scan_tools(repo_root: Path) -> tuple[dict[str, int], list[str]]:
    tools_dir = repo_root / "tools"
    fat_tools: dict[str, int] = {}
    alias_findings: list[str] = []
    for path in sorted(tools_dir.glob("*.py")):
        rel = path.relative_to(repo_root).as_posix()
        text = path.read_text(encoding="utf-8")
        line_count = len(text.splitlines())
        if line_count > MAX_TOOL_LINES:
            fat_tools[rel] = line_count
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    if alias.asname == alias.name:
                        alias_findings.append(
                            f"pass-through re-export in tool shim: {rel} ({alias.name})"
                        )
    return fat_tools, alias_findings


def findings(repo_root: Path) -> list[str]:
    """Return every tool entry point over MAX_TOOL_LINES or using pass-through aliases."""
    current, alias_findings = _scan_tools(repo_root)
    fat_findings = [
        f"fat tool: {path} ({current[path]} lines; maximum {MAX_TOOL_LINES})"
        for path in sorted(current)
    ]
    return fat_findings + alias_findings


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    found = findings(args.repo_root.resolve())
    if found:
        for finding in found:
            print(f"::error title=Tool shim contract::{finding}", file=sys.stderr)
        print(f"[TOOL-SHIM] FAILED: {len(found)} violation(s).", file=sys.stderr)
        return 1
    print(f"[TOOL-SHIM] PASS: top-level tools are <= {MAX_TOOL_LINES} lines.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
