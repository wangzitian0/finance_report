"""EPIC-025 AC25.1.1: reporting calculation primitives have a single owner."""

from datetime import date
from decimal import Decimal

from src.models.account import AccountType
from src.models.journal import Direction
from src.services import reporting as reporting_service, reporting_calc


def test_reporting_calc_extraction():
    """AC25.1.1: pure reporting math lives in ``services.reporting_calc`` and is
    re-used by ``services.reporting`` (same objects, not copies), so accounting
    sign rules, period boundaries, income-bucket classification, money
    quantization, and confidence-tier rollup are unchanged."""
    # The orchestration module re-exports the extracted primitives — identical
    # objects, guaranteeing no behavioral fork between the two modules.
    for name in (
        "ReportError",
        "_signed_amount",
        "_quantize_money",
        "_combine_provenance",
        "_worst_confidence_tier",
        "_iter_periods",
        "_month_start",
        "_month_end",
        "_add_months",
    ):
        assert getattr(reporting_service, name) is getattr(reporting_calc, name), name

    # Accounting sign rule: assets/expenses increase on DEBIT, the rest on CREDIT.
    assert reporting_calc._signed_amount(AccountType.ASSET, Direction.DEBIT, Decimal("5.00")) == Decimal("5.00")
    assert reporting_calc._signed_amount(AccountType.ASSET, Direction.CREDIT, Decimal("5.00")) == Decimal("-5.00")
    assert reporting_calc._signed_amount(AccountType.INCOME, Direction.CREDIT, Decimal("5.00")) == Decimal("5.00")
    assert reporting_calc._signed_amount(AccountType.LIABILITY, Direction.DEBIT, Decimal("5.00")) == Decimal("-5.00")

    # Money quantization stays at 2dp Decimal (never float), using the canonical
    # ROUND_HALF_EVEN rule: 10.005 rounds to the even 10.00.
    quantized = reporting_calc._quantize_money(Decimal("10.005"))
    assert isinstance(quantized, Decimal)
    assert quantized == Decimal("10.00")

    # Income-bucket classification.
    assert reporting_calc.income_bucket("Monthly Salary") == "salary"
    assert reporting_calc.income_bucket("Year-end Bonus") == "bonus"
    assert reporting_calc.income_bucket("Dividend payout") == "dividend"
    assert reporting_calc.income_bucket("Groceries") is None

    # Confidence-tier worst-input rollup and provenance combination.
    assert reporting_calc._worst_confidence_tier(["HIGH", "LOW", "TRUSTED"]) == "LOW"
    assert reporting_calc._worst_confidence_tier([None, None]) is None
    assert reporting_calc._combine_provenance(["imported", "imported"]) == "imported"
    assert reporting_calc._combine_provenance(["imported", "manual"]) == "derived"

    # Period boundary math.
    assert reporting_calc._month_start(date(2026, 2, 14)) == date(2026, 2, 1)
    assert reporting_calc._month_end(date(2026, 2, 14)) == date(2026, 2, 28)
    assert reporting_calc._add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    spans = reporting_calc._iter_periods(date(2026, 1, 1), date(2026, 1, 3), "daily")
    assert [(s.start, s.end) for s in spans] == [
        (date(2026, 1, 1), date(2026, 1, 1)),
        (date(2026, 1, 2), date(2026, 1, 2)),
        (date(2026, 1, 3), date(2026, 1, 3)),
    ]
