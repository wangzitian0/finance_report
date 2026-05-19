"""Tests for repository-root-relative Coveralls LCOV generation."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from build_unified_lcov import build_unified_lcov, repo_relative_source  # noqa: E402
from coverage_policy import CoverageComponent  # noqa: E402


def _component(
    name: str,
    component_root: str,
    source_subdir: str,
    lcov_path: str,
) -> CoverageComponent:
    return CoverageComponent(
        name=name,
        component_root=component_root,
        source_subdir=source_subdir,
        extensions=(".py",),
        ci_lcov_path=lcov_path,
        local_lcov_paths=(),
        exclude_patterns=(),
    )


def test_repo_relative_source_prefixes_component_root(tmp_path):
    """AC8.13.15: Unified LCOV paths are repository-root relative for Coveralls."""
    component = _component("backend", "apps/backend", "src", "coverage/backend.lcov")

    assert repo_relative_source(component, "src/services/example.py", tmp_path) == (
        "apps/backend/src/services/example.py"
    )


def test_build_unified_lcov_rewrites_component_source_paths(tmp_path):
    """AC8.13.15: Backend, frontend, and scripts reports share one repo-root path space."""
    backend = _component("backend", "apps/backend", "src", "coverage/backend.lcov")
    frontend = _component("frontend", "apps/frontend", "src", "coverage/frontend.lcov")
    scripts = _component("scripts", "", "scripts", "coverage/scripts.lcov")

    coverage_dir = tmp_path / "coverage"
    coverage_dir.mkdir()
    (coverage_dir / "backend.lcov").write_text("SF:src/api.py\nDA:1,1\nLH:1\nLF:1\nend_of_record\n")
    (coverage_dir / "frontend.lcov").write_text("SF:src/app/page.tsx\nDA:1,1\nLH:1\nLF:1\nend_of_record\n")
    (coverage_dir / "scripts.lcov").write_text("SF:scripts/check.py\nDA:1,1\nLH:1\nLF:1\nend_of_record\n")

    output = coverage_dir / "unified.lcov"

    assert build_unified_lcov(output, tmp_path, (backend, frontend, scripts)) == 0
    content = output.read_text()
    assert "SF:apps/backend/src/api.py" in content
    assert "SF:apps/frontend/src/app/page.tsx" in content
    assert "SF:scripts/check.py" in content


def test_build_unified_lcov_fails_when_no_reports_exist(tmp_path):
    """AC8.13.15: Empty unified reports fail instead of uploading misleading data."""
    component = _component("backend", "apps/backend", "src", "coverage/backend.lcov")

    assert build_unified_lcov(tmp_path / "coverage" / "unified.lcov", tmp_path, (component,)) == 1
