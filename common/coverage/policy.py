#!/usr/bin/env python3
"""Shared coverage policy for CI coverage calculation and LCOV audits."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]


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

    def normalize_lcov_source(self, source_file: str, repo_root: Path = ROOT_DIR) -> str:
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
        name="scripts",
        component_root="",
        source_subdir="scripts",
        extensions=(".py",),
        ci_lcov_path="coverage/scripts.lcov",
        local_lcov_paths=("coverage-scripts.lcov",),
        exclude_patterns=(
            "scripts/tests/**",
            "scripts/**/__pycache__/**",
            "scripts/**/test_*.py",
            "scripts/**/*_test.py",
            "conftest.py",
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
            "tools/**/test_*.py",
            "tools/**/*_test.py",
        ),
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
            "common/**/test_*.py",
            "common/**/*_test.py",
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
