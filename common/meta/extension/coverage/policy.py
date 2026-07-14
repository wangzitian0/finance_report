#!/usr/bin/env python3
"""Shared coverage policy for CI coverage calculation and LCOV audits."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[4]


# --- Coverage tiers (#923) ----------------------------------------------------
#
# Guiding rule: a tool tree is gated at high coverage *iff* it is CI-critical —
# its silent failure can false-green the pipeline or break a gate/deploy.
# Everything else (audits, registry/report generators, dev servers, one-off
# fixtures) is best-effort: its coverage artifact is still merged when present,
# but a missing best-effort artifact must not hard-fail the aggregation. The
# unified no-regression gate continues to apply to whatever LCOV is present.
CI_CRITICAL = "ci-critical"
BEST_EFFORT = "best-effort"
COVERAGE_TIERS = (CI_CRITICAL, BEST_EFFORT)


@dataclass(frozen=True)
class CoverageComponent:
    """A coverage component with one source tree and one LCOV report."""

    name: str
    component_root: str
    source_subdir: str
    extensions: tuple[str, ...]
    ci_lcov_path: str
    local_lcov_paths: tuple[str, ...]
    exclude_patterns: tuple[str, ...]
    # Coverage tier (#923). Defaults to CI_CRITICAL so any new component is
    # strictly gated until it is explicitly justified as best-effort.
    tier: str = CI_CRITICAL

    def __post_init__(self) -> None:
        if self.tier not in COVERAGE_TIERS:
            raise ValueError(
                f"{self.name}: tier must be one of {COVERAGE_TIERS}, got {self.tier!r}"
            )

    @property
    def is_ci_critical(self) -> bool:
        return self.tier == CI_CRITICAL

    def root_path(self, repo_root: Path = ROOT_DIR) -> Path:
        return repo_root / self.component_root if self.component_root else repo_root

    def source_path(self, repo_root: Path = ROOT_DIR) -> Path:
        return self.root_path(repo_root) / self.source_subdir

    def lcov_path(self, repo_root: Path = ROOT_DIR) -> Path:
        ci_path = repo_root / self.ci_lcov_path
        if ci_path.exists():
            return ci_path
        for local_path in self.local_lcov_paths:
            candidate = repo_root / local_path
            if candidate.exists():
                return candidate
        return ci_path

    def to_lcov_source(self, file_path: Path, repo_root: Path = ROOT_DIR) -> str:
        return file_path.relative_to(self.root_path(repo_root)).as_posix()

    def normalize_lcov_source(
        self, source_file: str, repo_root: Path = ROOT_DIR
    ) -> str:
        source = source_file.replace("\\", "/")
        root = self.root_path(repo_root)
        if Path(source).is_absolute():
            try:
                return Path(source).relative_to(root).as_posix()
            except ValueError:
                return source

        component_prefix = f"{self.component_root}/" if self.component_root else ""
        if component_prefix and source.startswith(component_prefix):
            return source[len(component_prefix) :]
        return source

    def is_excluded(self, component_relative_path: str) -> bool:
        path = component_relative_path.replace("\\", "/")
        basename = path.rsplit("/", 1)[-1]
        for pattern in self.exclude_patterns:
            if fnmatch(path, pattern) or fnmatch(basename, pattern):
                return True
        return False

    def expected_sources(self, repo_root: Path = ROOT_DIR) -> set[str]:
        source_root = self.source_path(repo_root)
        if not source_root.exists():
            return set()

        expected: set[str] = set()
        for extension in self.extensions:
            for file_path in source_root.rglob(f"*{extension}"):
                if not file_path.is_file():
                    continue
                lcov_source = self.to_lcov_source(file_path, repo_root)
                if not self.is_excluded(lcov_source):
                    expected.add(lcov_source)
        return expected


COMPONENTS: tuple[CoverageComponent, ...] = (
    CoverageComponent(
        name="backend",
        component_root="apps/backend",
        source_subdir="src",
        extensions=(".py",),
        ci_lcov_path="coverage/backend.lcov",
        local_lcov_paths=("apps/backend/coverage.lcov",),
        exclude_patterns=(
            "src/__init__.py",
            "src/**/__init__.py",
            "src/main.py",
        ),
    ),
    CoverageComponent(
        name="frontend",
        component_root="apps/frontend",
        source_subdir="src",
        extensions=(".ts", ".tsx"),
        ci_lcov_path="coverage/frontend.lcov",
        local_lcov_paths=("apps/frontend/coverage/lcov.info",),
        exclude_patterns=(
            "src/__tests__/**",
            "src/**/__tests__/**",
            "src/tests/**",
            "src/**/tests/**",
            "src/**/*.test.ts",
            "src/**/*.test.tsx",
            "src/**/*.spec.ts",
            "src/**/*.spec.tsx",
            "src/**/types/**",
            "src/**/*.config.*",
        ),
    ),
    CoverageComponent(
        name="tools",
        component_root="",
        source_subdir="tools",
        extensions=(".py",),
        ci_lcov_path="coverage/tools.lcov",
        local_lcov_paths=("coverage-tools.lcov",),
        exclude_patterns=(
            "tools/__init__.py",
            "tools/**/__init__.py",
            "tools/**/__pycache__/**",
            "tools/tests/**",
            "tools/wait_for_cheap_ci.py",
        ),
        # tools/ is largely one-off governance / CI glue (thin shims over
        # common/). Best-effort tier (#923): its LCOV is merged when present and
        # still subject to the no-regression gate, but a missing tools artifact
        # does not hard-fail the aggregation. CI-critical logic lives in common/.
        tier=BEST_EFFORT,
    ),
    CoverageComponent(
        name="common",
        component_root="",
        source_subdir="common",
        extensions=(".py",),
        ci_lcov_path="coverage/common.lcov",
        local_lcov_paths=("coverage-common.lcov",),
        exclude_patterns=(
            "common/__init__.py",
            "common/**/__init__.py",
            "common/**/__pycache__/**",
            "common/tests/**",
            # Long-poll CI waiter: no meaningful unit coverage (moved from tools/_lib/ci).
            "common/testing/wait_for_cheap_ci.py",
        ),
    ),
)

COMPONENT_BY_NAME = {component.name: component for component in COMPONENTS}


def get_component(name: str) -> CoverageComponent:
    return COMPONENT_BY_NAME[name]


def parse_lcov_sources(
    lcov_path: Path, component: CoverageComponent, repo_root: Path = ROOT_DIR
) -> set[str]:
    if not lcov_path.exists():
        return set()

    sources: set[str] = set()
    with open(lcov_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("SF:"):
                sources.add(component.normalize_lcov_source(line[3:], repo_root))
    return sources


# --- Coverage registration guard ---------------------------------------------
#
# `expected_sources()` makes each component recursive, so a new file *inside* a
# component source root (e.g. apps/backend/src/<anything>) is automatically
# measured. The remaining bypass is code placed *outside* every component root
# (a new top-level package, apps/<new-app>/, or a loose module next to src/).
# Such a tree is invisible to the per-component audit, so it could ship with
# zero coverage while the gate stays green.
#
# `find_unregistered_sources()` closes that hole: every tracked source file must
# be either (a) under a CoverageComponent source root, or (b) matched by an
# explicit exempt pattern below. Adding an unlisted code directory makes the
# guard fail until the author either moves it under a covered root or registers
# it here in a reviewable diff — coverage cannot be skipped by "not registering".

SOURCE_EXTENSIONS: tuple[str, ...] = (".py", ".ts", ".tsx")

# Repo-relative globs (matched against the full path and the basename) for
# source that is intentionally NOT subject to line coverage. Keep this list
# minimal and justified — broadening it re-opens the bypass.
COVERAGE_EXEMPT_PATTERNS: tuple[str, ...] = (
    # Test code — gated behaviorally, not counted as product source.
    "test_*.py",
    "conftest.py",
    "*.test.ts",
    "*.test.tsx",
    "*.spec.ts",
    "*.spec.tsx",
    "tests/**",
    "**/tests/**",
    "**/__tests__/**",
    "apps/frontend/playwright/**",
    # Build/runtime configuration and type declarations, not product logic.
    "*.config.ts",
    "*.config.js",
    "*.config.mjs",
    "*.config.cjs",
    "*.d.ts",
    "apps/frontend/vitest.setup.ts",
    # Alembic data migrations.
    "apps/backend/migrations/**",
    # Container entrypoint/deployment glue (Prefect deployment registration,
    # worker/API startup scripts) — ops plumbing, not product behavior. Still
    # covered by structural tests (tests/tooling/test_prefect_deployment_registration.py),
    # just not counted toward the line-coverage percentage.
    "apps/backend/scripts/**",
    # Agent tooling / skills — not shipped product runtime.
    ".opencode/**",
    # Docs build tooling.
    "docs/**",
    # Vendored submodule — owns its own coverage in its own repo.
    "repo/**",
)


def component_source_prefixes(repo_root: Path = ROOT_DIR) -> tuple[str, ...]:
    """Repo-relative, slash-terminated source roots of every coverage component."""
    return tuple(
        component.source_path(repo_root).relative_to(repo_root).as_posix().rstrip("/")
        + "/"
        for component in COMPONENTS
    )


def is_registered_source(rel_path: str, repo_root: Path = ROOT_DIR) -> bool:
    """True if a repo-relative source path is claimed by a component or exempt.

    "Claimed" means it lives under a component source root (covered, even if the
    component then excludes it from the percentage — it is still visible). Files
    matched by ``COVERAGE_EXEMPT_PATTERNS`` are deliberately out of scope.
    """
    path = rel_path.replace("\\", "/")
    if any(path.startswith(prefix) for prefix in component_source_prefixes(repo_root)):
        return True
    basename = path.rsplit("/", 1)[-1]
    return any(
        fnmatch(path, pattern) or fnmatch(basename, pattern)
        for pattern in COVERAGE_EXEMPT_PATTERNS
    )


def find_unregistered_sources(
    candidate_files: Iterable[str], repo_root: Path = ROOT_DIR
) -> list[str]:
    """Return source files that escape both component scopes and the exempt list.

    ``candidate_files`` is an iterable of repo-relative paths (e.g. ``git
    ls-files`` output). Non-source extensions are ignored. A non-empty result
    means coverage could be bypassed by those paths.
    """
    orphans = [
        path.replace("\\", "/")
        for raw in candidate_files
        if (path := raw.replace("\\", "/")).endswith(SOURCE_EXTENSIONS)
        and not is_registered_source(path, repo_root)
    ]
    return sorted(orphans)
