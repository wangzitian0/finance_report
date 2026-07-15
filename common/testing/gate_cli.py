"""Shared command-line runner for repository policy gates."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

ViolationFn = Callable[[Path], Iterable[str]]


def escape_workflow_command(message: str) -> str:
    """Escape untrusted data embedded in a GitHub Actions workflow command."""

    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def run_gate(
    name: str,
    violations_fn: ViolationFn,
    argv: Sequence[str] | None = None,
    *,
    annotation_title: str | None = None,
) -> int:
    """Run a repo-root policy gate with consistent annotations and summaries."""

    parser = argparse.ArgumentParser(description=f"Run the {name} repository gate.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)

    findings = list(violations_fn(args.repo_root.resolve()))
    if findings:
        title = annotation_title or name
        for finding in findings:
            print(
                f"::error title={title}::{escape_workflow_command(finding)}",
                file=sys.stderr,
            )
        print(
            f"[{name}] FAILED: {len(findings)} violation(s).",
            file=sys.stderr,
        )
        return 1

    print(f"[{name}] PASSED.")
    return 0
