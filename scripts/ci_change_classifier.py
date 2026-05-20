#!/usr/bin/env python3
"""Classify changed paths for CI job selection."""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

LIGHTWEIGHT_EXACT = {
    "AGENTS.md",
    "README.md",
    "vision.md",
    ".github/copilot-instructions.md",
    ".github/workflows/docs.yml",
}
LIGHTWEIGHT_PREFIXES = (
    "docs/",
    ".github/ISSUE_TEMPLATE/",
)


@dataclass(frozen=True)
class ChangeClassification:
    files: tuple[str, ...]
    heavy_files: tuple[str, ...]
    heavy_required: bool
    reason: str


def normalize_path(path: str) -> str:
    return path.strip().replace("\\", "/")


def is_lightweight(path: str) -> bool:
    normalized = normalize_path(path)
    if normalized in LIGHTWEIGHT_EXACT:
        return True
    return normalized.startswith(LIGHTWEIGHT_PREFIXES)


def classify_changed_paths(paths: Iterable[str]) -> ChangeClassification:
    files = tuple(path for raw in paths if (path := normalize_path(raw)))
    heavy_files = tuple(path for path in files if not is_lightweight(path))
    heavy_required = bool(heavy_files or not files)
    reason = (
        "runtime-or-ci-paths-changed"
        if heavy_files
        else "no-changed-files-detected"
        if not files
        else "lightweight-docs-or-docs-workflow-only"
    )
    return ChangeClassification(
        files=files,
        heavy_files=heavy_files,
        heavy_required=heavy_required,
        reason=reason,
    )


def write_github_outputs(classification: ChangeClassification, output_path: Path) -> None:
    with output_path.open("a", encoding="utf-8") as fh:
        fh.write(f"heavy_required={str(classification.heavy_required).lower()}\n")
        fh.write(f"reason={classification.reason}\n")


def write_github_summary(classification: ChangeClassification, summary_path: Path) -> None:
    with summary_path.open("a", encoding="utf-8") as fh:
        fh.write("## Change Classification\n\n")
        fh.write(f"- Heavy CI required: `{str(classification.heavy_required).lower()}`\n")
        fh.write(f"- Reason: `{classification.reason}`\n")
        fh.write(f"- Changed files: `{len(classification.files)}`\n")
        if classification.heavy_files:
            fh.write("\nHeavy-triggering files:\n\n")
            for path in classification.heavy_files[:50]:
                fh.write(f"- `{path}`\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changed-files", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--github-summary", type=Path)
    args = parser.parse_args()

    classification = classify_changed_paths(args.changed_files.read_text(encoding="utf-8").splitlines())

    if args.github_output:
        write_github_outputs(classification, args.github_output)
    if args.github_summary:
        write_github_summary(classification, args.github_summary)

    print(f"heavy_required={str(classification.heavy_required).lower()}")
    print(f"reason={classification.reason}")
    print(f"changed_files={len(classification.files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
