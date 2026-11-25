#!/usr/bin/env python3
"""Classify changed paths for CI job selection."""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

LIGHTWEIGHT_EXACT = {
    "AGENTS.md",
    "README.md",
    "vision.md",
    ".github/copilot-instructions.md",
    ".github/workflows/docs.yml",
}
LIGHTWEIGHT_PREFIXES = ("docs/",)

IMAGE_BUILD_EXACT = frozenset(
    {
        "apps/backend/.dockerignore",
        "apps/backend/Dockerfile",
        "apps/backend/alembic.ini",
        "apps/backend/pyproject.toml",
        "apps/backend/uv.lock",
        "apps/frontend/.dockerignore",
        "apps/frontend/Dockerfile",
        "apps/frontend/next.config.mjs",
        "apps/frontend/package-lock.json",
        "apps/frontend/package.json",
        "apps/frontend/postcss.config.mjs",
        "apps/frontend/tailwind.config.ts",
        "apps/frontend/tsconfig.json",
    }
)
IMAGE_BUILD_PREFIXES = ("apps/backend/scripts/",)

FRONTEND_PREFIXES = ("apps/frontend/",)

# Fail-closed cross-layer test selection (#2996, #3215).
# - Vitest skips only when EVERY changed path starts with VITEST_SKIP_PREFIXES.
# - Backend jobs skip on PRs only when EVERY changed path starts with BACKEND_TESTS_SKIP_PREFIXES.
VITEST_SKIP_PREFIXES = ("apps/backend/",)
BACKEND_TESTS_SKIP_PREFIXES = ("apps/frontend/",)

TOOLING_LANE_PREFIXES: tuple[str, ...] = (
    "tools/",
    "tests/",
    "common/",
    "docs/reference/",
    "apps/",
    ".github/",
    ".agents/",
    ".claude/",
    ".gemini/",
    ".moon/",
    ".opencode/",
    ".ws-publish/",
)
TOOLING_LANE_EXACT: frozenset[str] = frozenset(
    {
        "README.md",
        "readme.md",
        "vision.md",
        "moon.yml",
        "AGENTS.md",
        "GEMINI.md",
        "Makefile",
        "pytest.ini",
        "docker-compose.yml",
        "toolchain.toml",
        "mkdocs.yml",
        "docs/hooks.py",
        "docs/user-guide/reports.md",
        "runtime-hooks.manifest.json",
        "opencode.json",
        ".env.example",
        ".gitattributes",
        ".gitignore",
        ".mcp.json",
        ".node-version",
        ".npmrc",
        ".nvmrc",
        ".pre-commit-config.yaml",
        ".python-version",
        ".tool-versions",
    }
)

CI_DEFINITION_PATHS = frozenset(
    {
        ".github/workflows/ci.yml",
        "common/testing/change_classifier.py",
        "tools/ci_change_classifier.py",
    }
)


@dataclass(frozen=True)
class ChangeClassification:
    files: tuple[str, ...]
    heavy_files: tuple[str, ...]
    heavy_required: bool
    reason: str
    image_build_files: tuple[str, ...]
    image_build_required: bool
    frontend_changed: bool

    def _runs_unless_all_in(self, skip_prefixes: tuple[str, ...]) -> bool:
        return (
            not self.files
            or any(path in CI_DEFINITION_PATHS for path in self.files)
            or not all(path.startswith(skip_prefixes) for path in self.files)
        )

    @property
    def vitest_required(self) -> bool:
        return self._runs_unless_all_in(VITEST_SKIP_PREFIXES)

    @property
    def backend_required(self) -> bool:
        return self._runs_unless_all_in(BACKEND_TESTS_SKIP_PREFIXES)

    @property
    def tooling_required(self) -> bool:
        return (
            not self.files
            or any(path in CI_DEFINITION_PATHS for path in self.files)
            or any(
                path in TOOLING_LANE_EXACT or path.startswith(TOOLING_LANE_PREFIXES)
                for path in self.files
            )
        )


def normalize_path(path: str) -> str:
    return path.strip().replace("\\", "/")


def is_image_build_relevant(path: str) -> bool:
    normalized = normalize_path(path)
    return normalized in IMAGE_BUILD_EXACT or normalized.startswith(
        IMAGE_BUILD_PREFIXES
    )


def is_lightweight(path: str) -> bool:
    normalized = normalize_path(path)
    return normalized in LIGHTWEIGHT_EXACT or normalized.startswith(
        LIGHTWEIGHT_PREFIXES
    )


def classify_changed_paths(paths: Iterable[str]) -> ChangeClassification:
    files = tuple(path for raw in paths if (path := normalize_path(raw)))
    heavy_files = tuple(path for path in files if not is_lightweight(path))
    heavy_required = bool(heavy_files or not files)
    image_build_files = tuple(path for path in files if is_image_build_relevant(path))
    reason = (
        "runtime-or-ci-paths-changed"
        if heavy_files
        else "no-changed-files-detected"
        if not files
        else "lightweight-docs-or-docs-workflow-only"
    )
    frontend_changed = (
        not files
        or any(path in CI_DEFINITION_PATHS for path in files)
        or any(path.startswith(FRONTEND_PREFIXES) for path in files)
    )
    return ChangeClassification(
        files=files,
        heavy_files=heavy_files,
        heavy_required=heavy_required,
        reason=reason,
        image_build_files=image_build_files,
        image_build_required=bool(image_build_files or not files),
        frontend_changed=frontend_changed,
    )


def write_github_outputs(
    classification: ChangeClassification, output_path: Path
) -> None:
    pairs = [
        ("heavy_required", str(classification.heavy_required).lower()),
        ("image_build_required", str(classification.image_build_required).lower()),
        ("reason", classification.reason),
        ("frontend_changed", str(classification.frontend_changed).lower()),
        ("vitest_required", str(classification.vitest_required).lower()),
        ("backend_required", str(classification.backend_required).lower()),
        ("tooling_required", str(classification.tooling_required).lower()),
    ]
    with output_path.open("a", encoding="utf-8") as fh:
        fh.writelines(f"{k}={v}\n" for k, v in pairs)


def write_github_summary(
    classification: ChangeClassification, summary_path: Path
) -> None:
    with summary_path.open("a", encoding="utf-8") as fh:
        fh.write(
            "## Change Classification\n\n"
            f"- Heavy CI required: `{str(classification.heavy_required).lower()}`\n"
            f"- Reason: `{classification.reason}`\n"
            f"- Image build required: `{str(classification.image_build_required).lower()}`\n"
            f"- Frontend changed: `{str(classification.frontend_changed).lower()}`\n"
            f"- Vitest required: `{str(classification.vitest_required).lower()}`\n"
            f"- Backend required: `{str(classification.backend_required).lower()}`\n"
            f"- Tooling required: `{str(classification.tooling_required).lower()}`\n"
            f"- Changed files: `{len(classification.files)}`\n"
        )
        if classification.heavy_files:
            fh.write("\nHeavy-triggering files:\n\n")
            for path in classification.heavy_files[:50]:
                fh.write(f"- `{path}`\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changed-files", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--github-summary", type=Path)
    args = parser.parse_args(argv)

    classification = classify_changed_paths(
        args.changed_files.read_text(encoding="utf-8").splitlines()
    )
    if args.github_output:
        write_github_outputs(classification, args.github_output)
    if args.github_summary:
        write_github_summary(classification, args.github_summary)

    for line in (
        f"heavy_required={str(classification.heavy_required).lower()}",
        f"reason={classification.reason}",
        f"image_build_required={str(classification.image_build_required).lower()}",
        f"frontend_changed={str(classification.frontend_changed).lower()}",
        f"vitest_required={str(classification.vitest_required).lower()}",
        f"backend_required={str(classification.backend_required).lower()}",
        f"tooling_required={str(classification.tooling_required).lower()}",
        f"changed_files={len(classification.files)}",
    ):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
