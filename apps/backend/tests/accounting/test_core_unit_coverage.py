"""Unit coverage for core financial helpers (no DB).

Covers small pure-logic branches in reporting helpers and investment-accounting
validation that integration tests do not exercise directly.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from src.audit import JournalEntrySourceType
from src.ledger import Direction
from src.portfolio import (
    InvestmentAccountingService,
    InvestmentAccountingValidationError,
)
from src.reporting.extension.reporting_calc import (
    _provenance_from_source_type,
    _quantize_money,
    income_bucket,
)
from src.schemas.journal import JournalEntryCreate, JournalLineCreate


class TestReportingHelpers:
    """AC11.8.1: income classification and amount provenance helpers."""

    def test_income_bucket_classifies_known_keywords(self):
        assert income_bucket("Monthly Salary") == "salary"
        assert income_bucket("Annual Bonus") == "bonus"
        assert income_bucket("Dividend payout") == "dividend"

    def test_income_bucket_returns_none_for_unknown(self):
        assert income_bucket("grocery refund") is None

    def test_quantize_money_coerces_int(self):
        """Canonical money rounding accepts int and quantizes to 2dp."""
        result = _quantize_money(5)
        assert result == Decimal("5.00")

    def test_quantize_money_rounds_decimal(self):
        assert _quantize_money(Decimal("1.005")) == Decimal("1.00")  # banker's rounding

    @pytest.mark.parametrize(
        ("source_type", "expected"),
        [
            (JournalEntrySourceType.MANUAL, "manual"),
            # bank_statement was retired from the enum in 0040 (#896); the raw
            # string still classifies as imported via normalize_source_type.
            ("bank_statement", "imported"),
            (JournalEntrySourceType.SYSTEM, "derived"),
            (JournalEntrySourceType.FX_REVALUATION, "derived"),
            ("manual", "manual"),
            (None, None),
            ("not-a-valid-source", None),
        ],
    )
    def test_provenance_from_source_type(self, source_type, expected):
        assert _provenance_from_source_type(source_type) == expected


class TestJournalEntrySchema:
    """Schema preserves FX input while ledger owns financial validation."""

    def test_cross_currency_entry_preserves_fx_rate(self):
        """FX metadata passes through the schema for ledger validation."""
        debit, credit = uuid4(), uuid4()
        entry = JournalEntryCreate(
            entry_date=date(2026, 1, 1),
            memo="SGD<->USD transfer",
            lines=[
                JournalLineCreate(
                    account_id=debit,
                    direction=Direction.DEBIT,
                    amount=Decimal("135.00"),
                    currency="SGD",
                ),
                JournalLineCreate(
                    account_id=credit,
                    direction=Direction.CREDIT,
                    amount=Decimal("100.00"),
                    currency="USD",
                    fx_rate=Decimal("1.350000"),
                ),
            ],
        )
        assert len(entry.lines) == 2
        assert entry.lines[1].fx_rate == Decimal("1.350000")

    def test_cross_currency_entry_defers_missing_fx_validation_to_ledger(self):
        """Missing FX reaches the ledger service instead of reading process config here."""
        entry = JournalEntryCreate(
            entry_date=date(2026, 1, 1),
            memo="ledger validates FX",
            lines=[
                JournalLineCreate(
                    account_id=uuid4(),
                    direction=Direction.DEBIT,
                    amount=Decimal("100.00"),
                    currency="USD",
                ),
                JournalLineCreate(
                    account_id=uuid4(),
                    direction=Direction.CREDIT,
                    amount=Decimal("100.00"),
                    currency="USD",
                ),
            ],
        )
        assert all(line.fx_rate is None for line in entry.lines)


class TestInvestmentValidation:
    """AC-portfolio.1.2: investment transaction amount validation guards."""

    def test_validate_positive_rejects_zero(self):
        service = InvestmentAccountingService()
        with pytest.raises(InvestmentAccountingValidationError, match="must be positive"):
            service._validate_positive(Decimal("0"), "quantity")

    def test_validate_positive_accepts_positive(self):
        InvestmentAccountingService()._validate_positive(Decimal("1"), "quantity")

    def test_validate_non_negative_rejects_negative(self):
        service = InvestmentAccountingService()
        with pytest.raises(InvestmentAccountingValidationError, match="cannot be negative"):
            service._validate_non_negative(Decimal("-1"), "fees")

    def test_validate_non_negative_accepts_zero(self):
        InvestmentAccountingService()._validate_non_negative(Decimal("0"), "fees")
