"""Regression tests for archive residual ownership.

These checks keep removed archive backlog items inside the active
README -> EPIC -> AC -> test management chain instead of issue-only prose.
"""

from __future__ import annotations

from pathlib import Path

from common.ssot.ac_registry_format import load_registry_entries

REPO_ROOT = Path(__file__).resolve().parents[2]


def read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def registry_ids(rel_path: str) -> set[str]:
    return {entry["id"] for entry in load_registry_entries(REPO_ROOT / rel_path)}


def test_AC8_13_61_visual_regression_residual_is_epic_owned() -> None:
    """AC8.13.61: Visual regression residuals are owned by EPIC-008."""
    epic = read("docs/project/EPIC-008.testing-strategy.md")
    registry = registry_ids("docs/ac_registry.yaml")

    assert "AC8.13.61" in epic
    assert "Visual regression residual is explicitly owned by EPIC-008" in epic
    assert "P3 future testing capability" in epic
    assert "AC8.13.61" in registry


def test_AC8_13_62_test_observability_residual_is_epic_owned() -> None:
    """AC8.13.62: Test observability residuals are owned by EPIC-008."""
    epic = read("docs/project/EPIC-008.testing-strategy.md")
    registry = registry_ids("docs/ac_registry.yaml")

    assert "AC8.13.62" in epic
    assert "test report dashboard" in epic
    assert "failure notification" in epic
    assert "trend analysis" in epic
    assert "AC8.13.62" in registry


def test_AC8_13_63_performance_testing_residual_is_epic_owned() -> None:
    """AC8.13.63: Performance testing residuals are owned by EPIC-008."""
    epic = read("docs/project/EPIC-008.testing-strategy.md")
    registry = registry_ids("docs/ac_registry.yaml")

    assert "AC8.13.63" in epic
    assert "Performance testing residual is explicitly owned by EPIC-008" in epic
    assert "Locust" in epic
    assert "P95 trend gate" in epic
    assert "AC8.13.63" in registry


def test_AC12_25_1_uuid_logging_residual_is_epic_owned() -> None:
    """AC12.25.1: UUID logging serialization residual is owned by EPIC-012."""
    epic = read("docs/project/EPIC-012.foundation-libs.md")
    registry = registry_ids("docs/infra_registry.yaml")

    assert "AC12.25.1" in epic
    assert "UUID auto-serialization structlog processor" in epic
    assert "P2 backlog" in epic
    assert "tests/tooling/test_archive_residual_epic_ownership.py" in epic
    assert "scripts/tests/test_archive_residual_epic_ownership.py" not in epic
    assert "AC12.25.1" in registry


def test_AC4_8_1_reconciliation_benchmark_residual_is_epic_owned() -> None:
    """AC4.8.1: Reconciliation benchmark residual closure is owned by EPIC-004."""
    epic = read("docs/project/EPIC-004.reconciliation-engine.md")
    registry = registry_ids("docs/ac_registry.yaml")

    assert "AC4.8.1" in epic
    assert "Archive baseline benchmark residual is explicitly owned by EPIC-004" in epic
    assert "now closed through AC4.10.3" in epic
    assert "100-transaction manual false-positive audit" in epic
    assert "10,000-transaction" in epic
    assert "benchmark evidence" in epic
    assert "fails CI" in epic
    assert "0.1 USD Threshold**" in epic
    assert "Done (AC4.6.1)" in epic
    assert "tests/tooling/test_archive_residual_epic_ownership.py" in epic
    assert "python tools/analyze_test_ac_coverage.py --stdout" in epic
    assert "python tools/check_ac_traceability.py" in epic
    assert "scripts/tests/test_archive_residual_epic_ownership.py" not in epic
    assert "python scripts/" not in epic
    assert "AC4.8.1" in registry
