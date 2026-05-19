"""Tests for the shared coverage policy and source tree audit."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from check_coverage_policy import compare_component, run_audit  # noqa: E402
from coverage_policy import CoverageComponent, parse_lcov_sources  # noqa: E402


def _component(tmp_path: Path, *, exclude_patterns: tuple[str, ...] = ()) -> CoverageComponent:
    return CoverageComponent(
        name="sample",
        component_root="apps/backend",
        source_subdir="src",
        extensions=(".py",),
        ci_lcov_path="coverage/sample.lcov",
        local_lcov_paths=(),
        exclude_patterns=exclude_patterns,
    )


def _write(tmp_path: Path, relative_path: str, content: str = "x = 1\n") -> Path:
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_expected_sources_include_new_modules_by_default(tmp_path):
    """AC8.13.15: New source modules are included in the coverage policy automatically."""
    component = _component(tmp_path)
    _write(tmp_path, "apps/backend/src/services/new_module.py")

    assert component.expected_sources(tmp_path) == {"src/services/new_module.py"}


def test_compare_component_fails_when_source_file_is_missing_from_lcov(tmp_path):
    """AC8.13.15: Tree-vs-LCOV audit catches modules missing from coverage reports."""
    component = _component(tmp_path)
    _write(tmp_path, "apps/backend/src/services/new_module.py")
    _write(tmp_path, "coverage/sample.lcov", "SF:src/services/old_module.py\nDA:1,1\nLH:1\nLF:1\nend_of_record\n")

    missing, unexpected = compare_component(component, tmp_path)

    assert missing == ["src/services/new_module.py"]
    assert unexpected == ["src/services/old_module.py"]


def test_compare_component_fails_when_excluded_file_appears_in_lcov(tmp_path):
    """AC8.13.15: Excluded files cannot silently enter the measured LCOV set."""
    component = _component(tmp_path, exclude_patterns=("src/main.py",))
    _write(tmp_path, "apps/backend/src/main.py")
    _write(tmp_path, "coverage/sample.lcov", "SF:src/main.py\nDA:1,1\nLH:1\nLF:1\nend_of_record\n")

    missing, unexpected = compare_component(component, tmp_path)

    assert missing == []
    assert unexpected == ["src/main.py"]


def test_run_audit_passes_when_tree_and_lcov_match(tmp_path):
    """AC8.13.15: Matching source/report sets pass the policy gate."""
    component = _component(tmp_path)
    _write(tmp_path, "apps/backend/src/services/new_module.py")
    _write(
        tmp_path,
        "coverage/sample.lcov",
        "SF:src/services/new_module.py\nDA:1,1\nLH:1\nLF:1\nend_of_record\n",
    )

    assert run_audit(tmp_path, (component,)) == 0


def test_lcov_sources_normalize_component_prefixed_paths(tmp_path):
    """AC8.13.15: LCOV path normalization keeps CI and local reports comparable."""
    component = _component(tmp_path)
    lcov = _write(
        tmp_path,
        "coverage/sample.lcov",
        "SF:apps/backend/src/services/new_module.py\nDA:1,1\nLH:1\nLF:1\nend_of_record\n",
    )

    assert parse_lcov_sources(lcov, component, tmp_path) == {"src/services/new_module.py"}


def test_scripts_policy_does_not_expect_shell_files(tmp_path):
    """AC8.13.15: Scripts LCOV tracks Python modules and does not require shell files."""
    component = CoverageComponent(
        name="scripts",
        component_root="",
        source_subdir="scripts",
        extensions=(".py",),
        ci_lcov_path="coverage/scripts.lcov",
        local_lcov_paths=(),
        exclude_patterns=("scripts/tests/**",),
    )
    _write(tmp_path, "scripts/build.py")
    _write(tmp_path, "scripts/deploy.sh", "#!/usr/bin/env bash\n")
    _write(tmp_path, "scripts/tests/test_build.py")

    assert component.expected_sources(tmp_path) == {"scripts/build.py"}
