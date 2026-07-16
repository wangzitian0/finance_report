"""Layer-zero command runner shared by repository policy gates."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

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
    failure_status: int = 1,
) -> int:
    """Run a repo-root policy gate with consistent annotations and summaries."""

    parser = argparse.ArgumentParser(description=f"Run the {name} repository gate.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1

    findings = list(violations_fn(args.repo_root.resolve()))
    if findings:
        title = escape_workflow_command(annotation_title or name)
        for finding in findings:
            print(
                f"::error title={title}::{escape_workflow_command(finding)}",
                file=sys.stderr,
            )
        print(
            f"[{name}] FAILED: {len(findings)} violation(s).",
            file=sys.stderr,
        )
        return failure_status

    print(f"[{name}] PASSED.")
    return 0
