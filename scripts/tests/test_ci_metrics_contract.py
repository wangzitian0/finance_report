"""Tests for CI metrics coverage and AC traceability contracts."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import check_ci_metrics_contract as contract  # noqa: E402
from check_ci_metrics_contract import (  # noqa: E402
    _has_code_files,
    _validate_policy_shape,
    _validate_repo_contract_files,
    discover_source_roots,
    find_uncovered_source_roots,
    main,
    run_contract,
)
from coverage_policy import CoverageComponent  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def _write(root: Path, relative_path: str, content: str = "x = 1\n") -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _component(name: str, root: str, subdir: str, extension: str) -> CoverageComponent:
    return CoverageComponent(
        name=name,
        component_root=root,
        source_subdir=subdir,
        extensions=(extension,),
        ci_lcov_path=f"coverage/{name}.lcov",
        local_lcov_paths=(),
        exclude_patterns=(),
    )


def test_AC8_13_26_future_app_source_roots_must_be_in_coverage_policy(tmp_path):
    """AC8.13.26: New app source roots cannot bypass unified coverage policy."""
    _write(tmp_path, "apps/backend/src/service.py")
    _write(tmp_path, "apps/frontend/src/page.tsx", "export const Page = () => null\n")
    _write(tmp_path, "apps/new_service/src/main.py")
    _write(tmp_path, "scripts/build.py")

    components = (
        _component("backend", "apps/backend", "src", ".py"),
        _component("frontend", "apps/frontend", "src", ".tsx"),
        _component("scripts", "", "scripts", ".py"),
    )

    roots = discover_source_roots(tmp_path)
    assert "apps/new_service/src" in roots
    assert find_uncovered_source_roots(tmp_path, components) == ["apps/new_service/src"]
    assert run_contract(tmp_path, components=components) == 1


def test_AC8_13_26_current_source_roots_are_fully_governed_by_metrics_contract():
    """AC8.13.26: Current source roots, policy components, and workflow gates align."""
    assert run_contract(ROOT) == 0


def test_AC8_13_26_ci_workflow_runs_metrics_contract_and_defines_metric_semantics():
    """AC8.13.26 AC8.13.35: CI enforces one metrics contract and documents its limits."""
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    ci_cd = (ROOT / "docs/ssot/ci-cd.md").read_text(encoding="utf-8")
    traceability = (ROOT / "scripts/build_ac_traceability.py").read_text(
        encoding="utf-8"
    )

    assert "scripts/check_ci_metrics_contract.py" in workflow
    assert workflow.index("scripts/check_ci_metrics_contract.py") < workflow.index(
        "scripts/check_coverage_policy.py"
    )
    assert "Backend Tests (Shard ${{ matrix.shard }}/6)" in workflow
    assert "shard: [1, 2, 3, 4, 5, 6]" in workflow
    assert "--splits 6" in workflow
    assert "--failure-confirmation-seconds" in workflow
    assert "scripts/check_ac_traceability.py" in workflow
    assert workflow.index("scripts/check_ac_traceability.py") < workflow.index(
        "scripts/build_ac_traceability.py --output"
    )
    assert "single CI metrics contract" in ci_cd
    assert "AC traceability is a reference metric, not behavioral coverage" in ci_cd
    assert "trivial placeholder assertions" in ci_cd
    assert "not behavioral coverage" in traceability
    assert "placeholder assertions" in traceability


def test_AC8_13_26_code_discovery_ignores_missing_non_code_and_test_trees(tmp_path):
    """AC8.13.26: Source discovery only counts eligible implementation files."""
    assert not _has_code_files(tmp_path / "missing")

    _write(tmp_path, "src/tests/helper.py")
    _write(tmp_path, "src/readme.txt", "notes\n")
    assert not _has_code_files(tmp_path / "src")

    _write(tmp_path, "src/service.py")
    assert _has_code_files(tmp_path / "src")


def test_AC8_13_26_policy_shape_reports_duplicate_and_invalid_components(tmp_path):
    """AC8.13.26: Invalid coverage policy shape fails closed."""
    _write(tmp_path, "apps/backend/src/service.py")

    components = (
        CoverageComponent(
            name="duplicate",
            component_root="apps/backend",
            source_subdir="src",
            extensions=(".py",),
            ci_lcov_path="coverage/shared.lcov",
            local_lcov_paths=(),
            exclude_patterns=(),
        ),
        CoverageComponent(
            name="duplicate",
            component_root="apps/backend",
            source_subdir="src",
            extensions=(),
            ci_lcov_path="coverage/shared.lcov",
            local_lcov_paths=(),
            exclude_patterns=(),
        ),
        CoverageComponent(
            name="missing",
            component_root="apps/missing",
            source_subdir="src",
            extensions=(".py",),
            ci_lcov_path="coverage/missing.lcov",
            local_lcov_paths=(),
            exclude_patterns=(),
        ),
    )

    errors = _validate_policy_shape(tmp_path, components)

    assert "duplicate coverage component name: duplicate" in errors
    assert "duplicate coverage source root: apps/backend/src" in errors
    assert "duplicate CI LCOV path: coverage/shared.lcov" in errors
    assert "coverage component source root does not exist: apps/missing/src" in errors
    assert "coverage component has no file extensions: duplicate" in errors


def test_AC8_13_26_repo_contract_reports_missing_tokens(tmp_path):
    """AC8.13.26: Workflow and SSOT token drift is reported explicitly."""
    _write(
        tmp_path,
        ".github/workflows/ci.yml",
        "scripts/check_coverage_policy.py\nscripts/check_ci_metrics_contract.py\n",
    )
    _write(
        tmp_path,
        "docs/ssot/ci-cd.md",
        "single CI metrics contract\n",
    )
    _write(tmp_path, "scripts/build_ac_traceability.py", "reference metric\n")

    errors = _validate_repo_contract_files(tmp_path)

    assert any("scripts/calculate_unified_coverage.py" in error for error in errors)
    assert any("scripts/check_ac_traceability.py" in error for error in errors)
    assert any("scripts/build_ac_traceability.py --output" in error for error in errors)
    assert "CI metrics contract must run before coverage policy audit" in errors
    assert any("AC traceability is a reference metric" in error for error in errors)
    assert any("New `apps/*/src`" in error for error in errors)
    assert any("not behavioral coverage" in error for error in errors)


def test_AC8_13_26_main_exits_with_contract_result(
    tmp_path,
    monkeypatch,
):
    """AC8.13.26: CLI returns the contract result code."""
    called_with: list[Path] = []

    def fake_run_contract(repo_root: Path) -> int:
        called_with.append(repo_root)
        return 7

    monkeypatch.setattr(contract, "run_contract", fake_run_contract)
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_ci_metrics_contract.py", "--repo-root", str(tmp_path)],
    )

    try:
        main()
    except SystemExit as exc:
        assert exc.code == 7

    assert called_with == [tmp_path]
