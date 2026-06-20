"""Migration-cleanup guards for base package adoption (EPIC-012 AC12.31)."""

from __future__ import annotations

import re
import sys
from decimal import Decimal
from pathlib import Path

import pytest
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

BACKEND_QUANTITY_ADAPTER_FILES = [
    Path("apps/backend/src/services/assets.py"),
    Path("apps/backend/src/services/investment_accounting.py"),
    Path("apps/backend/src/services/market_data.py"),
    Path("apps/backend/src/services/portfolio.py"),
    Path("apps/backend/src/services/reporting.py"),
]


def _read(path: Path) -> str:
    return (REPO / path).read_text(encoding="utf-8")


def _ensure_backend_src_importable() -> None:
    backend_path = str(REPO / "apps/backend")
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
    loaded_src = sys.modules.get("src")
    if loaded_src is not None and not hasattr(loaded_src, "__path__"):
        del sys.modules["src"]


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
        assert re.search(r"from src\.money import [^\n]*to_money", src), (
            f"{path} must import the backend Money adapter"
        )
        assert "def _money(" not in src, f"{path} still defines a local money adapter"
        assert not re.search(r"(?<!to)_money\(", src), (
            f"{path} still calls a local money adapter"
        )

    performance_report = _read(Path("apps/backend/src/services/performance_report.py"))
    assert "percentage=_percent(row.percentage)" in performance_report
    assert "percentage=_money(row.percentage)" not in performance_report


@ac_proof(
    proof_id="test_base_package_confidence_percent_wrapper_retired",
    ac_ids=["AC12.31.6"],
    ci_tier="pr_ci",
)
def test_AC12_31_6_confidence_percent_wrapper_is_retired():
    """AC12.31.6: confidence UI calls Ratio formatting directly, with no local percent facade."""
    confidence = _read(Path("apps/frontend/src/lib/confidence.ts"))
    confidence_test = _read(Path("apps/frontend/src/__tests__/confidence.test.ts"))
    page = _read(Path("apps/frontend/src/app/(main)/confidence/page.tsx"))

    assert "formatProportionPercent" not in confidence
    assert "formatProportionPercent" not in confidence_test
    assert "formatProportionPercent" not in page
    assert (
        "formatPercentFromRatioValue(replay.proportion_before, { dp: 1 })" in confidence
    )
    assert (
        "formatPercentFromRatioValue(current.low_confidence_proportion, { dp: 1 })"
        in page
    )


@ac_proof(
    proof_id="test_base_package_ssot_fx_examples_use_money_exchange_rate",
    ac_ids=["AC12.31.6"],
    ci_tier="pr_ci",
)
def test_AC12_31_6_ssot_fx_examples_use_money_exchange_rate():
    """AC12.31.6: SSOT examples teach the base-package FX primitive, not Decimal math."""
    for path in [Path("docs/ssot/market_data.md"), Path("docs/ssot/reporting.md")]:
        src = _read(path)
        assert "ExchangeRate(" in src, f"{path} must show typed FX rates"
        assert "Money(" in src, f"{path} must show typed money conversion"
        assert "amount * rate).quantize" not in src
        assert "amount_sgd * fx_rate" not in src


@ac_proof(
    proof_id="test_base_package_backend_quantity_value_type_cleanup",
    ac_ids=["AC12.31.7"],
    ci_tier="pr_ci",
)
def test_AC12_31_7_backend_quantity_business_code_uses_value_type():
    """AC12.31.7: backend services hold Quantity objects in business calculations."""
    quantity_api = _read(Path("apps/backend/src/quantity/__init__.py"))
    for helper in [
        "quantized_quantity_value",
        "quantity_is_zero",
        "quantity_zero_value",
    ]:
        assert helper not in quantity_api

    forbidden_local_adapters = [
        "def _quantity(",
        "def _quantity_is_zero(",
        "def _quantity_value(",
        "def _quantized_quantity(",
        "def _quantity_zero(",
    ]
    for path in BACKEND_QUANTITY_ADAPTER_FILES:
        src = _read(path)
        assert "from src.quantity import Quantity" in src, (
            f"{path} must use the Quantity value type"
        )
        for needle in forbidden_local_adapters:
            assert needle not in src, (
                f"{path} still defines local Quantity adapter {needle}"
            )
        for helper in [
            "quantized_quantity_value",
            "quantity_is_zero",
            "quantity_zero_value",
        ]:
            assert helper not in src, (
                f"{path} still calls package-level Decimal facade {helper}"
            )

    investment = _read(Path("apps/backend/src/services/investment_accounting.py"))
    assert (
        "trade_quantity = Quantity(quantity, INVESTMENT_QUANTITY_UNIT).quantize()"
        in investment
    )
    assert "trade_quantity.is_zero()" in investment
    assert "quantity=trade_quantity.value" in investment
    # unit price now flows through the UnitPrice value type (#1253 / AC12.32),
    # keeping trade_quantity a Quantity object in the money calculation.
    assert "buy_price * trade_quantity" in investment

    portfolio = _read(Path("apps/backend/src/services/portfolio.py"))
    assert (
        "position_quantity = Quantity(position.quantity, PORTFOLIO_QUANTITY_UNIT).quantize()"
        in portfolio
    )
    assert "snapshot_quantity.is_zero()" in portfolio

    reporting = _read(Path("apps/backend/src/services/reporting.py"))
    assert (
        "position_quantity = Quantity(position.quantity, REPORTING_QUANTITY_UNIT).quantize()"
        in reporting
    )


@ac_proof(
    proof_id="test_base_package_backend_quantity_value_type_storage_edges",
    ac_ids=["AC12.31.7"],
    ci_tier="pr_ci",
)
def test_AC12_31_7_backend_quantity_value_type_handles_storage_edges():
    """AC12.31.7: Quantity itself owns storage-edge rounding and zero semantics."""
    _ensure_backend_src_importable()

    from src.quantity import FloatNotAllowedError, Quantity

    assert Quantity(Decimal("1.2345675"), "units").quantize().value == Decimal(
        "1.234568"
    )
    assert Quantity(1, "units").quantize().value == Decimal("1.000000")
    assert Quantity.zero("units").quantize().value == Decimal("0.000000")
    assert Quantity(Decimal("0.0000004"), "units").quantize().is_zero()
    assert not Quantity(Decimal("0.0000005"), "units").quantize().is_zero()
    with pytest.raises(FloatNotAllowedError):
        Quantity(0.1, "units")
    with pytest.raises(FloatNotAllowedError):
        Quantity(True, "units")
