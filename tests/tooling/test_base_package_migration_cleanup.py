"""Migration-cleanup guards for base package adoption (EPIC-012 AC12.31)."""

from __future__ import annotations

import re
from pathlib import Path

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]

MONEY_FIXTURE_FILES = [
    Path("tests/e2e/test_market_data_price_paths.py"),
    Path("tests/e2e/test_personal_financial_report_package.py"),
    Path("tests/e2e/test_four_asset_net_worth_golden_path.py"),
    Path("tests/e2e/test_brokerage_upload_to_portfolio_value.py"),
    Path("tests/e2e/test_vision_upload_to_dashboard_hard_gate.py"),
    Path("tools/_lib/fixtures/personal_report_package.py"),
    Path("tools/_lib/fixtures/portfolio_audit_package.py"),
]

FRONTEND_PERCENT_FILES = [
    Path("apps/frontend/src/components/portfolio/PerformanceCard.tsx"),
    Path("apps/frontend/src/components/portfolio/InvestmentPerformanceSchedule.tsx"),
    Path("apps/frontend/src/components/portfolio/HoldingsTable.tsx"),
    Path("apps/frontend/src/components/portfolio/AllocationChart.tsx"),
    Path("apps/frontend/src/app/(main)/portfolio/page.tsx"),
    Path("apps/frontend/src/app/(main)/portfolio/[ticker]/page.tsx"),
    Path("apps/frontend/src/app/(main)/page.tsx"),
    Path("apps/frontend/src/app/(main)/reports/page.tsx"),
    Path("apps/frontend/src/components/reconciliation/Workbench.tsx"),
]

BACKEND_MONEY_ADAPTER_FILES = [
    Path("apps/backend/src/services/investment_accounting.py"),
    Path("apps/backend/src/services/performance_report.py"),
]


def _read(path: Path) -> str:
    return (REPO / path).read_text(encoding="utf-8")


@ac_proof(
    proof_id="test_base_package_money_fixture_cleanup",
    ac_ids=["AC12.31.5"],
    ci_tier="pr_ci",
)
def test_AC12_31_5_money_fixture_helpers_route_through_base_package():
    """AC12.31.5: E2E/fixture money adapters use one shared Money-backed helper."""
    helper = _read(Path("common/testing/base_values.py"))
    assert "from common.money import FloatNotAllowedError, Money" in helper
    assert "Money(Decimal(str(value)), currency).quantize().amount" in helper

    for path in MONEY_FIXTURE_FILES:
        src = _read(path)
        assert "from common.testing import money_amount" in src, (
            f"{path} must import the shared helper"
        )
        assert "def _money(" not in src, f"{path} still defines a local money adapter"
        assert 'Decimal(str(value)).quantize(Decimal("0.01"))' not in src, (
            f"{path} still hand-rolls money quantization"
        )

    portfolio_audit_fixture = _read(
        Path("tools/_lib/fixtures/portfolio_audit_package.py")
    )
    assert (
        "report_package_market_value_sgd(self) -> Decimal:\n        return money_amount("
        in portfolio_audit_fixture
    )
    assert "reporting_market_value_sgd=money_amount(" in portfolio_audit_fixture
    assert portfolio_audit_fixture.count('currency="SGD"') >= 2


@ac_proof(
    proof_id="test_base_package_frontend_percent_cleanup",
    ac_ids=["AC12.31.5"],
    ci_tier="pr_ci",
)
def test_AC12_31_5_frontend_percent_formatters_are_not_duplicated():
    """AC12.31.5: frontend percent display/calculation calls Ratio format helpers directly."""
    for path in FRONTEND_PERCENT_FILES:
        src = _read(path)
        assert "@/lib/ratio/format" in src, f"{path} must use Ratio format helpers"
        assert "function formatReturnPercent(" not in src
        assert "function formatAllocationPercent(" not in src
        assert "function formatPercent(" not in src
        assert "function formatPnlPercent(" not in src
        assert "Math.round((clean / total) * 100)" not in src
        assert "Math.round(stats.match_rate" not in src
        assert "Math.round((value / maxBucket) * 100)" not in src

    allocation = _read(
        Path("apps/frontend/src/components/portfolio/AllocationChart.tsx")
    )
    assert "formatPercentFromPercentValue(d.percentage, { dp: 1 })" in allocation
    assert "formatAmount(d.percentage, 1)}%" not in allocation

    ratio_format = _read(Path("apps/frontend/src/lib/ratio/format.ts"))
    assert "export function percentNumberFromParts(" in ratio_format


@ac_proof(
    proof_id="test_base_package_backend_money_adapter_cleanup",
    ac_ids=["AC12.31.5"],
    ci_tier="pr_ci",
)
def test_AC12_31_5_backend_money_adapters_are_not_duplicated():
    """AC12.31.5: backend services use the shared Money rounding adapter directly."""
    for path in BACKEND_MONEY_ADAPTER_FILES:
        src = _read(path)
        assert "from src.money import to_money" in src, (
            f"{path} must import the backend Money adapter"
        )
        assert "def _money(" not in src, f"{path} still defines a local money adapter"
        assert not re.search(r"(?<!to)_money\(", src), (
            f"{path} still calls a local money adapter"
        )

    performance_report = _read(Path("apps/backend/src/services/performance_report.py"))
    assert "percentage=_percent(row.percentage)" in performance_report
    assert "percentage=_money(row.percentage)" not in performance_report
