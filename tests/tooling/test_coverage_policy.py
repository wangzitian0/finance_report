"""Tests for the shared coverage policy and source tree audit."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from common.testing.coverage import (  # noqa: E402
    build_unified_lcov,
    check_policy,
)
from common.testing.coverage.check_policy import (  # noqa: E402
    audit_unregistered_sources,
    compare_component,
    main,
    run_audit,
    tracked_source_files,
)
from common.testing.coverage.policy import (  # noqa: E402
    CoverageComponent,
    find_unregistered_sources,
    is_registered_source,
    parse_lcov_sources,
)


def _component(
    tmp_path: Path, *, exclude_patterns: tuple[str, ...] = ()
) -> CoverageComponent:
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


def test_expected_sources_recursively_include_all_eligible_files_except_exclusions(
    tmp_path,
):
    """AC8.13.15: Coverage scope is recursive and deny-list based."""
    component = _component(
        tmp_path,
        exclude_patterns=(
            "src/__init__.py",
            "src/**/__init__.py",
            "src/generated/**",
        ),
    )
    _write(tmp_path, "apps/backend/src/domain/service.py")
    _write(tmp_path, "apps/backend/src/domain/deep/worker.py")
    _write(tmp_path, "apps/backend/src/presentation/page.py")
    _write(tmp_path, "apps/backend/src/__init__.py")
    _write(tmp_path, "apps/backend/src/domain/__init__.py")
    _write(tmp_path, "apps/backend/src/generated/client.py")

    assert component.expected_sources(tmp_path) == {
        "src/domain/deep/worker.py",
        "src/domain/service.py",
        "src/presentation/page.py",
    }


def test_compare_component_fails_when_source_file_is_missing_from_lcov(tmp_path):
    """AC8.13.15: Tree-vs-LCOV audit catches modules missing from coverage reports."""
    component = _component(tmp_path)
    _write(tmp_path, "apps/backend/src/services/new_module.py")
    _write(
        tmp_path,
        "coverage/sample.lcov",
        "SF:src/services/old_module.py\nDA:1,1\nLH:1\nLF:1\nend_of_record\n",
    )

    missing, unexpected = compare_component(component, tmp_path)

    assert missing == ["src/services/new_module.py"]
    assert unexpected == ["src/services/old_module.py"]


def test_compare_component_fails_when_excluded_file_appears_in_lcov(tmp_path):
    """AC8.13.15: Excluded files cannot silently enter the measured LCOV set."""
    component = _component(tmp_path, exclude_patterns=("src/main.py",))
    _write(tmp_path, "apps/backend/src/main.py")
    _write(
        tmp_path,
        "coverage/sample.lcov",
        "SF:src/main.py\nDA:1,1\nLH:1\nLF:1\nend_of_record\n",
    )

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
    missing_paths = [
        f"apps/backend/src/services/missing_{index}.py" for index in range(51)
    ]
    unexpected_records = [
        f"SF:src/services/unexpected_{index}.py\nDA:1,1\nLH:1\nLF:1\nend_of_record\n"
        for index in range(51)
    ]
    for path in missing_paths:
        _write(tmp_path, path)
    _write(tmp_path, "coverage/sample.lcov", "".join(unexpected_records))

    assert run_audit(tmp_path, (component,)) == 1

    out = capsys.readouterr().out
    assert (
        "::error title=sample coverage missing files::51 source files are absent from LCOV"
        in out
    )
    assert (
        "::error title=sample coverage unexpected files::51 LCOV files are outside the coverage policy"
        in out
    )
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

    assert parse_lcov_sources(lcov, component, tmp_path) == {
        "src/services/new_module.py"
    }


def test_lcov_path_prefers_ci_then_local_fallback(tmp_path):
    """AC8.13.15: Coverage policy uses local LCOV only when CI LCOV is absent."""
    component = CoverageComponent(
        name="sample",
        component_root="",
        source_subdir="tools",
        extensions=(".py",),
        ci_lcov_path="coverage/ci.lcov",
        local_lcov_paths=("coverage/local.lcov",),
        exclude_patterns=(),
    )
    local_lcov = _write(tmp_path, "coverage/local.lcov", "")

    assert component.lcov_path(tmp_path) == local_lcov

    ci_lcov = _write(tmp_path, "coverage/ci.lcov", "")
    assert component.lcov_path(tmp_path) == ci_lcov


def test_normalize_absolute_lcov_source_outside_component_root(tmp_path):
    """AC8.13.15: External absolute LCOV sources stay unchanged for diagnostics."""
    component = _component(tmp_path)
    external = tmp_path.parent / "outside.py"

    assert component.normalize_lcov_source(str(external), tmp_path) == str(external)


def test_expected_sources_handles_missing_roots_and_directory_matches(tmp_path):
    """AC8.13.15: Missing roots and directory matches do not enter expected files."""
    component = CoverageComponent(
        name="sample",
        component_root="",
        source_subdir="missing",
        extensions=(".py",),
        ci_lcov_path="coverage/sample.lcov",
        local_lcov_paths=(),
        exclude_patterns=(),
    )
    assert component.expected_sources(tmp_path) == set()

    component = CoverageComponent(
        name="sample",
        component_root="",
        source_subdir="tools",
        extensions=(".py",),
        ci_lcov_path="coverage/sample.lcov",
        local_lcov_paths=(),
        exclude_patterns=(),
    )
    (tmp_path / "tools" / "package.py").mkdir(parents=True)
    assert component.expected_sources(tmp_path) == set()


def test_parse_lcov_sources_missing_file_returns_empty(tmp_path):
    """AC8.13.15: Missing LCOV reports produce an empty source set."""
    component = _component(tmp_path)

    assert (
        parse_lcov_sources(tmp_path / "coverage" / "missing.lcov", component, tmp_path)
        == set()
    )


def test_tools_policy_does_not_expect_shell_files(tmp_path):
    """AC8.13.15: Tools LCOV tracks Python modules and does not require shell files."""
    component = CoverageComponent(
        name="tools",
        component_root="",
        source_subdir="tools",
        extensions=(".py",),
        ci_lcov_path="coverage/tools.lcov",
        local_lcov_paths=(),
        exclude_patterns=("tests/tooling/**",),
    )
    _write(tmp_path, "tools/build.py")
    _write(tmp_path, "tools/deploy.sh", "#!/usr/bin/env bash\n")
    _write(tmp_path, "tests/tooling/test_build.py")

    assert component.expected_sources(tmp_path) == {"tools/build.py"}


def test_build_unified_lcov_main_exits_with_builder_result(tmp_path, monkeypatch):
    """AC8.13.15: Unified LCOV CLI passes repo root and output into the builder."""
    calls: list[tuple[Path, Path, bool]] = []

    def fake_build_unified_lcov(
        output: Path, repo_root: Path, strip_branches: bool = False
    ) -> int:
        calls.append((output, repo_root, strip_branches))
        return 4

    monkeypatch.setattr(
        build_unified_lcov,
        "build_unified_lcov",
        fake_build_unified_lcov,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_unified_lcov.py",
            str(tmp_path / "coverage" / "unified.lcov"),
            "--repo-root",
            str(tmp_path),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        build_unified_lcov.main()

    assert exc.value.code == 4
    assert calls == [
        (tmp_path / "coverage" / "unified.lcov", tmp_path.resolve(), False)
    ]


def test_unregistered_guard_flags_code_outside_every_component():
    """A new top-level package or loose module outside src is flagged."""
    orphans = find_unregistered_sources(
        [
            "apps/backend/src/services/ok.py",  # claimed by backend
            "apps/frontend/src/lib/ok.ts",  # claimed by frontend
            "tools/ok.py",  # claimed by tools
            "common/ok.py",  # claimed by common
            "apps/worker/src/handler.py",  # ORPHAN: new app
            "libs/util.py",  # ORPHAN: new top-level package
            "apps/backend/rogue.py",  # ORPHAN: inside component dir but outside src
        ]
    )
    assert orphans == [
        "apps/backend/rogue.py",
        "apps/worker/src/handler.py",
        "libs/util.py",
    ]


def test_unregistered_guard_exempts_tests_config_and_non_product_trees():
    """Test files, config, migrations, skills and docs are not product source."""
    candidates = [
        "apps/backend/tests/test_x.py",
        "tests/tooling/test_y.py",
        "apps/frontend/src/__tests__/z.test.tsx",
        "apps/frontend/playwright/flow.spec.ts",
        "apps/frontend/vitest.config.ts",
        "apps/frontend/vitest.setup.ts",
        "apps/backend/migrations/versions/0001_x.py",
        ".opencode/skills/domain/development/scripts/gen.py",
        "docs/hooks.py",
        "newpkg/foo.go",  # not a tracked source extension we measure
    ]
    assert find_unregistered_sources(candidates) == []


def test_is_registered_source_distinguishes_covered_from_orphan():
    assert is_registered_source("apps/backend/src/main.py") is True
    assert is_registered_source("common/testing/coverage/policy.py") is True
    assert is_registered_source("apps/newservice/handler.py") is False


def test_real_repo_has_no_unregistered_source_trees():
    """Live gate: every tracked source file is covered or explicitly exempt.

    If this fails, a code directory was added without registering it for
    coverage. Either move it under a coverage component source root, or add an
    explicit, justified entry to COVERAGE_EXEMPT_PATTERNS.
    """
    orphans = find_unregistered_sources(tracked_source_files(ROOT), ROOT)
    assert orphans == [], "Unregistered source trees escape coverage: " + ", ".join(
        orphans
    )


def test_audit_unregistered_sources_passes_on_current_repo():
    assert audit_unregistered_sources(ROOT) == 0


def test_AC8_13_56_tools_policy_tracks_python_command_entrypoints(tmp_path):
    """AC8.13.56: Tools command modules are covered as their own source root."""
    component = CoverageComponent(
        name="tools",
        component_root="",
        source_subdir="tools",
        extensions=(".py",),
        ci_lcov_path="coverage/tools.lcov",
        local_lcov_paths=(),
        exclude_patterns=(
            "tools/__init__.py",
            "tools/**/__init__.py",
            "tools/tests/**",
        ),
    )
    _write(tmp_path, "tools/calculate.py")
    _write(tmp_path, "tools/__init__.py")
    _write(tmp_path, "tools/tests/test_calculate.py")

    assert component.expected_sources(tmp_path) == {"tools/calculate.py"}
