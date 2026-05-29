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

PR_PREVIEW_EXACT = {
    "docker-compose.yml",
    "scripts/smoke_test.sh",
}
PR_PREVIEW_PREFIXES = (
    "apps/backend/",
    "apps/frontend/",
    ".github/actions/setup-e2e-tests/",
    "scripts/pdf_fixtures/",
    "tests/e2e/",
)

STAGING_EXACT = {
    ".github/workflows/ci.yml",
    ".github/workflows/staging-deploy.yml",
    ".github/workflows/staging-ai-ocr-gate.yml",
    ".node-version",
    ".python-version",
    "docker-compose.yml",
    "scripts/check_ghcr_image_tag.sh",
    "scripts/dokploy_deploy.sh",
    "scripts/health_check.sh",
    "scripts/smoke_test.sh",
    "toolchain.toml",
    "repo",
}
STAGING_PREFIXES = (
    "apps/backend/",
    "apps/frontend/",
    ".github/actions/setup-e2e-tests/",
    "repo/",
    "scripts/pdf_fixtures/",
    "tests/e2e/",
)


@dataclass(frozen=True)
class ChangeClassification:
    files: tuple[str, ...]
    heavy_files: tuple[str, ...]
    heavy_required: bool
    reason: str
    pr_preview_files: tuple[str, ...]
    pr_preview_required: bool
    pr_preview_reason: str
    staging_files: tuple[str, ...]
    staging_required: bool
    staging_reason: str


def normalize_path(path: str) -> str:
    return path.strip().replace("\\", "/")


def is_lightweight(path: str) -> bool:
    normalized = normalize_path(path)
    if normalized in LIGHTWEIGHT_EXACT:
        return True
    return normalized.startswith(LIGHTWEIGHT_PREFIXES)


def is_pr_preview_relevant(path: str) -> bool:
    normalized = normalize_path(path)
    if normalized in PR_PREVIEW_EXACT:
        return True
    return normalized.startswith(PR_PREVIEW_PREFIXES)


def is_staging_relevant(path: str) -> bool:
    normalized = normalize_path(path)
    if normalized in STAGING_EXACT:
        return True
    return normalized.startswith(STAGING_PREFIXES)


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
    pr_preview_files = tuple(path for path in files if is_pr_preview_relevant(path))
    pr_preview_required = bool(pr_preview_files or not files)
    pr_preview_reason = (
        "pr-preview-paths-changed"
        if pr_preview_files
        else "no-changed-files-detected"
        if not files
        else "no-pr-preview-paths-changed"
    )
    staging_files = tuple(path for path in files if is_staging_relevant(path))
    staging_required = bool(staging_files or not files)
    staging_reason = (
        "staging-paths-changed"
        if staging_files
        else "no-changed-files-detected"
        if not files
        else "no-staging-paths-changed"
    )
    return ChangeClassification(
        files=files,
        heavy_files=heavy_files,
        heavy_required=heavy_required,
        reason=reason,
        pr_preview_files=pr_preview_files,
        pr_preview_required=pr_preview_required,
        pr_preview_reason=pr_preview_reason,
        staging_files=staging_files,
        staging_required=staging_required,
        staging_reason=staging_reason,
    )


def write_github_outputs(
    classification: ChangeClassification, output_path: Path
) -> None:
    with output_path.open("a", encoding="utf-8") as fh:
        fh.write(f"heavy_required={str(classification.heavy_required).lower()}\n")
        fh.write(f"reason={classification.reason}\n")
        fh.write(
            f"pr_preview_required={str(classification.pr_preview_required).lower()}\n"
        )
        fh.write(f"pr_preview_reason={classification.pr_preview_reason}\n")
        fh.write(f"staging_required={str(classification.staging_required).lower()}\n")
        fh.write(f"staging_reason={classification.staging_reason}\n")


def write_github_summary(
    classification: ChangeClassification, summary_path: Path
) -> None:
    with summary_path.open("a", encoding="utf-8") as fh:
        fh.write("## Change Classification\n\n")
        fh.write(
            f"- Heavy CI required: `{str(classification.heavy_required).lower()}`\n"
        )
        fh.write(f"- Reason: `{classification.reason}`\n")
        fh.write(
            f"- PR preview required: `{str(classification.pr_preview_required).lower()}`\n"
        )
        fh.write(f"- PR preview reason: `{classification.pr_preview_reason}`\n")
        fh.write(
            f"- Staging deploy required: `{str(classification.staging_required).lower()}`\n"
        )
        fh.write(f"- Staging reason: `{classification.staging_reason}`\n")
        fh.write(f"- Changed files: `{len(classification.files)}`\n")
        if classification.heavy_files:
            fh.write("\nHeavy-triggering files:\n\n")
            for path in classification.heavy_files[:50]:
                fh.write(f"- `{path}`\n")
        if classification.pr_preview_files:
            fh.write("\nPR preview-triggering files:\n\n")
            for path in classification.pr_preview_files[:50]:
                fh.write(f"- `{path}`\n")
        if classification.staging_files:
            fh.write("\nStaging-triggering files:\n\n")
            for path in classification.staging_files[:50]:
                fh.write(f"- `{path}`\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changed-files", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--github-summary", type=Path)
    args = parser.parse_args()

    classification = classify_changed_paths(
        args.changed_files.read_text(encoding="utf-8").splitlines()
    )

    if args.github_output:
        write_github_outputs(classification, args.github_output)
    if args.github_summary:
        write_github_summary(classification, args.github_summary)

    print(f"heavy_required={str(classification.heavy_required).lower()}")
    print(f"reason={classification.reason}")
    print(f"pr_preview_required={str(classification.pr_preview_required).lower()}")
    print(f"pr_preview_reason={classification.pr_preview_reason}")
    print(f"staging_required={str(classification.staging_required).lower()}")
    print(f"staging_reason={classification.staging_reason}")
    print(f"changed_files={len(classification.files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
