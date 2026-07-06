"""Tests for CI metrics coverage and AC traceability contracts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from common.meta.extension import metrics_contract as contract  # noqa: E402
from common.meta.extension.metrics_contract import (  # noqa: E402
    _has_code_files,
    _validate_policy_shape,
    _validate_repo_contract_files,
    discover_source_roots,
    find_uncovered_source_roots,
    main,
    run_contract,
)
from common.testing.coverage.policy import CoverageComponent  # noqa: E402


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
    _write(tmp_path, "tools/build.py")

    components = (
        _component("backend", "apps/backend", "src", ".py"),
        _component("frontend", "apps/frontend", "src", ".tsx"),
        _component("tools", "", "tools", ".py"),
    )

    roots = discover_source_roots(tmp_path)
    assert "apps/new_service/src" in roots
    assert find_uncovered_source_roots(tmp_path, components) == ["apps/new_service/src"]
    assert run_contract(tmp_path, components=components) == 1


def test_AC8_13_53_root_common_source_root_must_be_in_coverage_policy(tmp_path):
    """AC8.13.53: Root common modules cannot bypass unified coverage policy."""
    _write(tmp_path, "common/shared.py")
    _write(tmp_path, "tools/build.py")

    components = (_component("tools", "", "tools", ".py"),)

    roots = discover_source_roots(tmp_path)
    assert "common" in roots
    assert find_uncovered_source_roots(tmp_path, components) == ["common"]
    assert run_contract(tmp_path, components=components) == 1


def test_AC8_13_56_root_tools_source_root_must_be_in_coverage_policy(tmp_path):
    """AC8.13.56: Root tools command modules cannot bypass coverage policy."""
    _write(tmp_path, "common/shared.py")
    _write(tmp_path, "tools/build.py")

    components = (_component("common", "", "common", ".py"),)

    roots = discover_source_roots(tmp_path)
    assert "tools" in roots
    assert find_uncovered_source_roots(tmp_path, components) == ["tools"]
    assert run_contract(tmp_path, components=components) == 1


def test_AC8_13_26_current_source_roots_are_fully_governed_by_metrics_contract():
    """AC8.13.26: Current source roots, policy components, and workflow gates align."""
    assert run_contract(ROOT) == 0


def test_AC8_13_26_ci_workflow_runs_metrics_contract_and_defines_metric_semantics():
    """AC8.13.26 AC8.13.35: CI enforces one metrics contract and documents its limits."""
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    ci_cd = (ROOT / "docs/ssot/ci-cd.md").read_text(encoding="utf-8")
    traceability = (ROOT / "common/testing/build_ac_traceability.py").read_text(
        encoding="utf-8"
    )

    assert "tools/check_ci_metrics_contract.py" in workflow
    assert "tools/check_toolchain_contract.py" in workflow
    assert "tools/ci_change_classifier.py" in workflow
    assert "tools/github_workflow_timing_summary.py" in workflow
    lint_block = workflow.split("  lint:", 1)[1].split("  backend:", 1)[0]
    tooling_coverage_block = workflow.split("  tooling-coverage:", 1)[1].split(
        "  unified-coverage:", 1
    )[0]
    unified_coverage_block = workflow.split("  unified-coverage:", 1)[1].split(
        "  ac-traceability:", 1
    )[0]
    assert "uv run ruff check src tests" in lint_block
    assert "uv run ruff format src tests --check" in lint_block
    assert "tools/check_ci_metrics_contract.py" in lint_block
    assert "Tooling/Common Coverage" in tooling_coverage_block
    assert "Run tooling tests with coverage" in tooling_coverage_block
    assert "Upload tooling coverage context" in tooling_coverage_block
    assert "coverage-tooling" in workflow
    assert "Download tooling coverage" in unified_coverage_block
    assert "tools/check_ci_metrics_contract.py" not in unified_coverage_block
    assert workflow.index("tools/check_ci_metrics_contract.py") < workflow.index(
        "tools/check_coverage_policy.py"
    )
    assert "Backend Tests (Shard ${{ matrix.shard }}/5)" in workflow
    assert "shard: [1, 2, 3, 4, 5]" in workflow
    assert "--splits 5" in workflow
    assert "--splitting-algorithm=least_duration" in workflow
    assert "--durations-path ci/backend-test-durations.json" in workflow
    assert "Loaded pytest-split duration seed" in workflow
    assert "Upload main unified coverage to Coveralls" in workflow
    coveralls_block = workflow.split(
        "- name: Upload main unified coverage to Coveralls", 1
    )[1].split("  ac-traceability:", 1)[0]
    assert (
        "if: github.event_name == 'push' && github.ref == 'refs/heads/main'"
        in coveralls_block
    )
    assert "Upload backend to Coveralls (per-flag)" not in workflow
    assert "Upload frontend to Coveralls (per-flag)" not in workflow
    assert "Write coverage gate summary" in workflow
    assert "Authoritative coverage gate" in workflow
    assert "Pull requests do not publish Coveralls status contexts" in workflow
    assert "coverage/coveralls-unified.lcov" in workflow
    assert "coverage/coveralls-backend.lcov" not in workflow
    assert "coverage/coveralls-frontend.lcov" not in workflow
    assert "Write coverage debug context" in workflow
    assert "Upload unified coverage context" in workflow
    assert "unified-coverage-context" in workflow
    assert "coverage/coverage-context.txt" in workflow
    assert "event_name=${{ github.event_name }}" in workflow
    assert "run_attempt=${{ github.run_attempt }}" in workflow
    assert "--junit-xml=test-results/backend-shard-${{ matrix.shard }}.xml" in workflow
    assert "backend-shard-${{ matrix.shard }}-test-context" in workflow
    assert "backend-integration-test-context" in workflow
    assert "backend-tier1-e2e-test-context" in workflow
    assert (
        "--reporter=default --reporter=junit --outputFile.junit=test-results/vitest-junit.xml"
        in workflow
    )
    assert "--reporter=line,html" in workflow
    assert "frontend-vitest-test-context" in workflow
    assert "frontend-playwright-test-context" in workflow
    assert "frontend-telemetry-test-context" in workflow
    assert "$RUNNER_TEMP/AC-TRACEABILITY-CONTEXT.md" in workflow
    assert "Gate Status" in workflow
    global_permissions = workflow.split("env:", 1)[0]
    assert "statuses: write" not in global_permissions
    assert "statuses: write" not in unified_coverage_block
    assert "Mark Coveralls statuses reporting-only" not in workflow
    assert "tools/mark_coveralls_reporting_status.py" not in workflow
    # The standalone check_ac_traceability / check_critical_proof_matrix gate
    # STEPS are retired (AC8.13.141): their contracts are folded into the single
    # check_ac_index gate, which is what CI must now require.
    assert "tools/check_ac_traceability.py" not in workflow
    assert "tools/check_critical_proof_matrix.py" not in workflow
    assert "tools/check_ac_index.py" in workflow
    assert "--cov=common" in workflow
    assert "--cov=tools" in workflow
    assert "coverage/common.lcov" in workflow
    assert "coverage/tools.lcov" in workflow
    assert "single CI metrics contract" in ci_cd
    assert "AC traceability is a reference metric, not behavioral coverage" in ci_cd
    assert "README EPIC map drift" in ci_cd
    assert "unclassified E2E-like assets outside declared roots" in ci_cd
    assert "trivial placeholder assertions" in ci_cd
    assert "Coveralls uploads are main-only reporting" in ci_cd
    assert "coverage gate summary" in ci_cd
    assert "CI observability artifacts" in ci_cd
    assert "Coverage scope is deny-list based within each governed source root" in ci_cd
    assert "strip branch records before upload" in ci_cd
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
        "tools/check_coverage_policy.py\ntools/check_ci_metrics_contract.py\n",
    )
    _write(
        tmp_path,
        "docs/ssot/ci-cd.md",
        "single CI metrics contract\n",
    )
    _write(tmp_path, "common/testing/build_ac_traceability.py", "reference metric\n")

    errors = _validate_repo_contract_files(tmp_path)

    assert any("tools/calculate_unified_coverage.py" in error for error in errors)
    assert any("tools/check_ac_index.py" in error for error in errors)
    assert any("--cov=common" in error for error in errors)
    assert any("--cov=tools" in error for error in errors)
    assert any("coverage/common.lcov" in error for error in errors)
    assert any("coverage/tools.lcov" in error for error in errors)
    assert any("tools/build_ac_traceability.py --output" in error for error in errors)
    assert any("Upload main unified coverage to Coveralls" in error for error in errors)
    assert any("Write coverage gate summary" in error for error in errors)
    assert "CI metrics contract must run before coverage policy audit" in errors
    assert any("AC traceability is a reference metric" in error for error in errors)
    assert any("README EPIC map drift" in error for error in errors)
    assert any("unclassified E2E-like assets" in error for error in errors)
    assert any("Coveralls uploads are main-only reporting" in error for error in errors)
    assert any("coverage gate summary" in error for error in errors)
    assert any("CI observability artifacts" in error for error in errors)
    assert any("New `apps/*/src`" in error for error in errors)
    assert any("not behavioral coverage" in error for error in errors)


def test_AC8_13_68_repo_contract_requires_e2e_before_audit_artifact(tmp_path):
    """AC8.13.68 AC8.13.141: CI must run E2E EPIC traceability before the audit.

    The former "AC traceability gate must run before E2E" ordering rule is gone:
    the standalone check_ac_traceability gate STEP is retired (its contract is
    folded into the single check_ac_index gate). The surviving structural rule is
    that the E2E EPIC traceability gate runs before the audit-artifact build.
    """
    _write(
        tmp_path,
        ".github/workflows/ci.yml",
        "\n".join(
            [
                "tools/check_ci_metrics_contract.py",
                "tools/check_coverage_policy.py",
                "tools/calculate_unified_coverage.py",
                "tools/ci_change_classifier.py",
                "tools/github_workflow_timing_summary.py",
                "Backend Tests (Shard ${{ matrix.shard }}/5)",
                "shard: [1, 2, 3, 4, 5]",
                "--splits 5",
                "--splitting-algorithm=least_duration",
                "--durations-path ci/backend-test-durations.json",
                "Loaded pytest-split duration seed",
                "Upload main unified coverage to Coveralls",
                "github.event_name == 'push' && github.ref == 'refs/heads/main'",
                "Write coverage gate summary",
                "Authoritative coverage gate",
                "Pull requests do not publish Coveralls status contexts",
                "coverage/coveralls-unified.lcov",
                "--cov=common",
                "--cov=tools",
                "coverage/common.lcov",
                "coverage/tools.lcov",
                # E2E traceability AFTER the audit build => ordering violation.
                'tools/build_ac_traceability.py --output "$RUNNER_TEMP/AC-TEST-TRACEABILITY-AUDIT.md"',
                "tools/check_e2e_epic_traceability.py",
                "Build Backend SHA image",
                "Build Frontend SHA image",
                "push: ${{ github.event_name == 'push' && github.ref == 'refs/heads/main' }}",
                "Container image validation failed",
            ]
        ),
    )
    _write(
        tmp_path,
        "docs/ssot/ci-cd.md",
        "single CI metrics contract\n"
        "AC traceability is a reference metric, not behavioral coverage\n"
        "README EPIC map drift\n"
        "unclassified E2E-like assets outside declared roots\n"
        "trivial placeholder assertions\n"
        "Coveralls uploads are main-only reporting\n"
        "coverage gate summary\n"
        "Coverage scope is deny-list based within each governed source root\n"
        "New `apps/*/src`\n"
        "strip branch records before upload\n",
    )
    _write(
        tmp_path,
        "common/testing/build_ac_traceability.py",
        "not behavioral coverage\nplaceholder assertions\nreference metric\n",
    )

    errors = _validate_repo_contract_files(tmp_path)

    assert (
        "E2E EPIC traceability gate must run before audit artifact generation" in errors
    )


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
