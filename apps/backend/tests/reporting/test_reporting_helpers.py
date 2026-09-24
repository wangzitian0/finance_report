"""Tests for reporting helper utilities."""

from datetime import date
from decimal import Decimal

import pytest

from src.config import settings
from src.ledger import AccountType, Direction
from src.reporting import (
    ReportError,
    _add_months,
    _iter_periods,
    _month_end,
    _month_start,
    _normalize_currency,
    _quantize_money,
    _quarter_start,
    _signed_amount,
)


def test_normalize_currency_defaults_to_base() -> None:
    assert _normalize_currency(None) == settings.base_currency.upper()
    assert _normalize_currency(" usd ") == "USD"


def test_signed_amount_respects_account_direction() -> None:
    assert _signed_amount(AccountType.ASSET, Direction.DEBIT, Decimal("10")) == Decimal("10")
    assert _signed_amount(AccountType.ASSET, Direction.CREDIT, Decimal("10")) == Decimal("-10")
    assert _signed_amount(AccountType.LIABILITY, Direction.CREDIT, Decimal("10")) == Decimal("10")
    assert _signed_amount(AccountType.LIABILITY, Direction.DEBIT, Decimal("10")) == Decimal("-10")


def test_quantize_money_handles_ints() -> None:
    assert _quantize_money(5) == Decimal("5.00")
    assert _quantize_money(Decimal("5.1")) == Decimal("5.10")


def test_month_helpers() -> None:
    sample = date(2024, 2, 15)
    assert _month_start(sample) == date(2024, 2, 1)
    assert _month_end(sample) == date(2024, 2, 29)
    assert _quarter_start(sample) == date(2024, 1, 1)


def test_add_months_caps_day() -> None:
    assert _add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert _add_months(date(2024, 1, 31), 2) == date(2024, 3, 31)


def test_iter_periods_daily_weekly_monthly() -> None:
    daily = _iter_periods(date(2024, 1, 1), date(2024, 1, 3), "daily")
    assert [span.start for span in daily] == [
        date(2024, 1, 1),
        date(2024, 1, 2),
        date(2024, 1, 3),
    ]

    weekly = _iter_periods(date(2024, 1, 3), date(2024, 1, 10), "weekly")
    assert weekly[0].start == date(2024, 1, 1)
    assert weekly[0].end == date(2024, 1, 7)
    assert weekly[1].start == date(2024, 1, 8)
    assert weekly[1].end == date(2024, 1, 10)

    monthly = _iter_periods(date(2024, 1, 15), date(2024, 2, 2), "monthly")
    assert monthly[0].start == date(2024, 1, 1)
    assert monthly[0].end == date(2024, 1, 31)
    assert monthly[1].start == date(2024, 2, 1)
    assert monthly[1].end == date(2024, 2, 2)


def test_iter_periods_rejects_invalid_period() -> None:
    with pytest.raises(ReportError, match="Unsupported period"):
        _iter_periods(date(2024, 1, 1), date(2024, 1, 2), "yearly")


def test_validate_internal_action_href_parity() -> None:
    """AC-reporting-workflow-href-parity: Validate that reporting and workflow
    internal action href validation logic are strictly aligned.
    """
    from src.schemas.reporting import _validate_internal_action_href as reporting_val
    from src.workflow.base.types import _validate_internal_action_href as workflow_val

    valid_cases = ["/reports/balance-sheet", "/workflow/session/1", "/api/v1/export?format=csv"]
    invalid_cases = [
        "https://external.example.com",
        "http://malicious.org",
        "//protocol-relative.com",
        "relative/path/without/slash",
        "javascript://alert(1)",
    ]

    for case in valid_cases:
        assert reporting_val(case) == case
        assert workflow_val(case) == case

    for case in invalid_cases:
        with pytest.raises(ValueError, match="action_href must be an internal relative path"):
            reporting_val(case)
        with pytest.raises(ValueError, match="action_href must be an internal relative path"):
            workflow_val(case)
