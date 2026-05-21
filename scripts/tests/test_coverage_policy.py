"""Tests for the shared coverage policy and source tree audit."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import check_coverage_policy as check_policy  # noqa: E402
from check_coverage_policy import compare_component, main, run_audit  # noqa: E402
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


def test_run_audit_reports_missing_and_unexpected_files(tmp_path, capsys):
    """AC8.13.15: Coverage policy failures enumerate source/report drift."""
    component = _component(tmp_path)
    missing_paths = [f"apps/backend/src/services/missing_{index}.py" for index in range(51)]
    unexpected_records = [
        f"SF:src/services/unexpected_{index}.py\nDA:1,1\nLH:1\nLF:1\nend_of_record\n"
        for index in range(51)
    ]
    for path in missing_paths:
        _write(tmp_path, path)
    _write(tmp_path, "coverage/sample.lcov", "".join(unexpected_records))

    assert run_audit(tmp_path, (component,)) == 1

    out = capsys.readouterr().out
    assert "::error title=sample coverage missing files::51 source files are absent from LCOV" in out
    assert "::error title=sample coverage unexpected files::51 LCOV files are outside the coverage policy" in out
    assert "... 1 more missing files" in out
    assert "... 1 more unexpected files" in out


def test_main_exits_with_audit_result(tmp_path, monkeypatch):
    """AC8.13.15: Coverage policy CLI returns the audit result code."""
    called_with: list[Path] = []

    def fake_run_audit(repo_root: Path) -> int:
        called_with.append(repo_root)
        return 9

    monkeypatch.setattr(check_policy, "run_audit", fake_run_audit)
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_coverage_policy.py", "--repo-root", str(tmp_path)],
    )

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 9
    assert called_with == [tmp_path.resolve()]


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
