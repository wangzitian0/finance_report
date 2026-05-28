#!/usr/bin/env python3
"""Validate that CI metrics apply to the whole project source surface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common.coverage.policy import COMPONENTS, ROOT_DIR, CoverageComponent

CODE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx"}
DISCOVERED_APP_ROOTS = ("apps", "packages")
DISCOVERED_ROOT_SOURCE_DIRS = ("common", "scripts", "tools")
EXCLUDED_DIR_NAMES = {
    ".git",
    ".next",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
    "tests",
    "__tests__",
}


def _repo_rel(path: Path, repo_root: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def _is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_DIR_NAMES for part in path.parts)


def _has_code_files(path: Path) -> bool:
    if not path.exists():
        return False
    for file_path in path.rglob("*"):
        if not file_path.is_file() or _is_excluded(file_path):
            continue
        if file_path.suffix in CODE_EXTENSIONS:
            return True
    return False


def discover_source_roots(repo_root: Path = ROOT_DIR) -> list[str]:
    """Discover source roots that must be governed by coverage policy."""
    roots: set[str] = set()

    for container_name in DISCOVERED_APP_ROOTS:
        container = repo_root / container_name
        if not container.exists():
            continue
        for child in sorted(container.iterdir()):
            source_root = child / "src"
            if source_root.is_dir() and _has_code_files(source_root):
                roots.add(_repo_rel(source_root, repo_root))

    for root_name in DISCOVERED_ROOT_SOURCE_DIRS:
        source_root = repo_root / root_name
        if source_root.is_dir() and _has_code_files(source_root):
            roots.add(root_name)

    return sorted(roots)


def policy_source_roots(
    repo_root: Path = ROOT_DIR,
    components: tuple[CoverageComponent, ...] = COMPONENTS,
) -> list[str]:
    return sorted(
        _repo_rel(component.source_path(repo_root), repo_root)
        for component in components
    )


def find_uncovered_source_roots(
    repo_root: Path = ROOT_DIR,
    components: tuple[CoverageComponent, ...] = COMPONENTS,
) -> list[str]:
    discovered = set(discover_source_roots(repo_root))
    governed = set(policy_source_roots(repo_root, components))
    return sorted(discovered - governed)


def _duplicate_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def _validate_policy_shape(
    repo_root: Path,
    components: tuple[CoverageComponent, ...],
) -> list[str]:
    errors: list[str] = []
    names = [component.name for component in components]
    source_roots = policy_source_roots(repo_root, components)
    ci_lcov_paths = [component.ci_lcov_path for component in components]

    for duplicate in _duplicate_values(names):
        errors.append(f"duplicate coverage component name: {duplicate}")
    for duplicate in _duplicate_values(source_roots):
        errors.append(f"duplicate coverage source root: {duplicate}")
    for duplicate in _duplicate_values(ci_lcov_paths):
        errors.append(f"duplicate CI LCOV path: {duplicate}")

    for component in components:
        source_root = _repo_rel(component.source_path(repo_root), repo_root)
        if not component.source_path(repo_root).exists():
            errors.append(
                f"coverage component source root does not exist: {source_root}"
            )
        if not component.extensions:
            errors.append(
                f"coverage component has no file extensions: {component.name}"
            )

    missing_roots = find_uncovered_source_roots(repo_root, components)
    if missing_roots:
        errors.append(
            "source roots are not governed by common/coverage/policy.py: "
            + ", ".join(missing_roots)
        )

    return errors


def _validate_repo_contract_files(repo_root: Path) -> list[str]:
    errors: list[str] = []
    workflow = repo_root / ".github" / "workflows" / "ci.yml"
    ci_cd = repo_root / "docs" / "ssot" / "ci-cd.md"
    traceability = repo_root / "common" / "ssot" / "build_ac_traceability.py"

    if workflow.exists():
        workflow_text = workflow.read_text(encoding="utf-8")
        required_workflow_tokens = (
            "tools/ci/check_ci_metrics_contract.py",
            "tools/ci/check_toolchain_contract.py",
            "tools/ci/ci_change_classifier.py",
            "tools/ci/github_workflow_timing_summary.py",
            "tools/coverage/check_coverage_policy.py",
            "tools/coverage/calculate_unified_coverage.py",
            "tools/ssot/lint_doc_consistency.py",
            "tools/ssot/check_ssot_ownership.py",
            "tools/ssot/check_manifest.py",
            "tools/ssot/generate_ac_registry.py --check",
            "tools/ssot/check_ac_traceability.py",
            'tools/ssot/build_ac_traceability.py --output "$RUNNER_TEMP/AC-TEST-TRACEABILITY-AUDIT.md"',
            "--cov=common",
            "--cov=tools",
            "coverage/common.lcov",
            "coverage/tools.lcov",
            "Upload unified coverage to Coveralls",
            "Upload backend to Coveralls (per-flag)",
            "Upload frontend to Coveralls (per-flag)",
            "Backend Tests (Shard ${{ matrix.shard }}/6)",
            "--splits 6",
            "container-images:",
            "Build Backend SHA image",
            "Build Frontend SHA image",
            "push: ${{ github.event_name == 'push' && github.ref == 'refs/heads/main' }}",
            "Container image validation failed",
        )
        for token in required_workflow_tokens:
            if token not in workflow_text:
                errors.append(f"CI workflow is missing metrics token: {token}")
        if (
            "tools/ci/check_ci_metrics_contract.py" in workflow_text
            and "tools/coverage/check_coverage_policy.py" in workflow_text
            and workflow_text.index("tools/ci/check_ci_metrics_contract.py")
            > workflow_text.index("tools/coverage/check_coverage_policy.py")
        ):
            errors.append("CI metrics contract must run before coverage policy audit")
        if (
            "tools/ssot/check_ac_traceability.py" in workflow_text
            and "tools/ssot/build_ac_traceability.py --output" in workflow_text
            and workflow_text.index("tools/ssot/check_ac_traceability.py")
            > workflow_text.index("tools/ssot/build_ac_traceability.py --output")
        ):
            errors.append(
                "AC traceability gate must run before audit artifact generation"
            )

    if ci_cd.exists():
        ci_cd_text = ci_cd.read_text(encoding="utf-8")
        for token in (
            "single CI metrics contract",
            "AC traceability is a reference metric, not behavioral coverage",
            "trivial placeholder assertions",
            "Coveralls uploads are reporting-only and do not block CI pass/fail",
            "PR CI dry-runs staging image builds before merge",
            "Main push CI is the only path that pushes SHA-tagged images",
            "New `apps/*/src`, `packages/*/src`, or root shared source roots fail CI",
        ):
            if token not in ci_cd_text:
                errors.append(f"CI/CD SSOT is missing metrics semantics: {token}")

    if traceability.exists():
        traceability_text = traceability.read_text(encoding="utf-8")
        if "not behavioral coverage" not in traceability_text:
            errors.append(
                "AC traceability builder must state that references are not behavioral coverage"
            )
        if "placeholder assertions" not in traceability_text:
            errors.append(
                "AC traceability builder must distinguish placeholder assertions from real references"
            )

    return errors


def run_contract(
    repo_root: Path = ROOT_DIR,
    components: tuple[CoverageComponent, ...] = COMPONENTS,
) -> int:
    repo_root = repo_root.resolve()
    errors = _validate_policy_shape(repo_root, components)
    errors.extend(_validate_repo_contract_files(repo_root))

    print("CI metrics contract")
    print(f"  discovered source roots: {', '.join(discover_source_roots(repo_root))}")
    print(
        f"  policy source roots: {', '.join(policy_source_roots(repo_root, components))}"
    )

    if errors:
        for error in errors:
            print(f"::error title=CI metrics contract::{error}")
        return 1

    print("CI metrics contract passed.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate CI metrics contracts.")
    parser.add_argument("--repo-root", type=Path, default=ROOT_DIR)
    args = parser.parse_args()
    sys.exit(run_contract(args.repo_root))


if __name__ == "__main__":
    main()
