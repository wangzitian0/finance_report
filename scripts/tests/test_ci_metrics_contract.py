"""Tests for CI metrics coverage and AC traceability contracts."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from check_ci_metrics_contract import (  # noqa: E402
    discover_source_roots,
    find_uncovered_source_roots,
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
    assert find_uncovered_source_roots(tmp_path, components) == [
        "apps/new_service/src"
    ]
    assert run_contract(tmp_path, components=components) == 1


def test_AC8_13_26_current_source_roots_are_fully_governed_by_metrics_contract():
    """AC8.13.26: Current source roots, policy components, and workflow gates align."""
    assert run_contract(ROOT) == 0


def test_AC8_13_26_ci_workflow_runs_metrics_contract_and_defines_metric_semantics():
    """AC8.13.26: CI enforces one metrics contract and documents its limits."""
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    ci_cd = (ROOT / "docs/ssot/ci-cd.md").read_text(encoding="utf-8")
    traceability = (ROOT / "scripts/build_ac_traceability.py").read_text(
        encoding="utf-8"
    )

    assert "scripts/check_ci_metrics_contract.py" in workflow
    assert workflow.index("scripts/check_ci_metrics_contract.py") < workflow.index(
        "scripts/check_coverage_policy.py"
    )
    assert "single CI metrics contract" in ci_cd
    assert "AC traceability is a reference metric, not behavioral coverage" in ci_cd
    assert "not behavioral coverage" in traceability
