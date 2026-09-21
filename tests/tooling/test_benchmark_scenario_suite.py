"""Unit tests for the financial scenario benchmark suite and staging smoke gate."""

from __future__ import annotations

import csv
import io
from decimal import Decimal
from pathlib import Path

from common.testing.matrix import STAGING_CORE_E2E_MARKER
from tools._lib.benchmarks.run_financial_scenario_benchmark import (
    generate_standard_operations_csv,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_staging_core_e2e_marker_contract() -> None:
    """AC-testing.deploy-gates.39: Staging deployment Phase 2 validation is scoped to fast fail-closed smoke."""
    assert STAGING_CORE_E2E_MARKER == "smoke and not llm"
    deploy_yml = (REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text(
        encoding="utf-8"
    )
    expected_cmd = 'pytest tests/e2e -v -m "smoke and not llm" -n 4 --junit-xml=test-results/staging-core-e2e.xml'
    assert expected_cmd in deploy_yml


def test_generate_standard_operations_csv_identity() -> None:
    """Benchmark Case 2: standard operations CSV generation maintains strict 3-statement reconciliation."""
    opening = Decimal("10000.00")
    csv_bytes = generate_standard_operations_csv(opening_balance=opening)
    assert isinstance(csv_bytes, bytes)
    text = csv_bytes.decode("utf-8")

    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    assert len(rows) == 4

    total_delta = Decimal("0.00")
    for row in rows:
        assert row["Statement Currency"] == "SGD"
        assert row["Statement Period Start"] == "2025-04-01"
        assert row["Statement Period End"] == "2025-04-30"
        assert Decimal(row["Statement Opening Balance"]) == opening
        assert Decimal(row["Statement Closing Balance"]) == opening + Decimal("2800.00")
        total_delta += Decimal(row["Amount"])

    assert total_delta == Decimal("2800.00")
    expected_closing = opening + total_delta
    assert expected_closing == Decimal("12800.00")
