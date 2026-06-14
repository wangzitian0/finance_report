"""AC5.32: income module typed currency + typed-intermediate response construction.

Covers the EPIC-005 AC5.32 tech-debt slice for ``routers/income.py``:
- currency is a validated/normalized typed code (not a soft ``str``);
- the response is built from a typed intermediate, not a string-keyed dict;
- the FX-failure response is an explicitly declared error model.
"""

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.schemas.base import normalize_currency_code
from src.schemas.income import AnnualizedIncomeResponse, FxConversionErrorResponse
from src.services.reporting import AnnualizedIncomeTotals, resolve_line_currency


def test_AC5_32_1_currency_code_type_validates_and_normalizes():
    """AC5.32.1: AnnualizedIncomeResponse.currency is a typed, normalized currency code."""
    # The schema field reuses the shared CurrencyCode type: Pydantic flattens the
    # Annotated alias, so assert on the carried metadata (length bounds + the
    # shared normalizer) rather than identity of the alias object.
    field = AnnualizedIncomeResponse.model_fields["currency"]
    assert field.annotation is str
    assert any(getattr(m, "min_length", None) == 3 for m in field.metadata)
    assert any(getattr(m, "max_length", None) == 3 for m in field.metadata)
    assert any(getattr(m, "func", None) is normalize_currency_code for m in field.metadata)

    # Soft input is normalized (strip + upper) at the schema boundary.
    response = AnnualizedIncomeResponse(
        annualized_salary=Decimal("1.00"),
        annualized_bonus=Decimal("0.00"),
        annualized_dividend=Decimal("0.00"),
        annualized_total=Decimal("1.00"),
        currency=" sgd ",
        as_of=date(2026, 5, 20),
    )
    assert response.currency == "SGD"

    # Length is enforced — a non 3-letter code is rejected.
    with pytest.raises(ValidationError):
        AnnualizedIncomeResponse(
            annualized_salary=Decimal("1.00"),
            annualized_bonus=Decimal("0.00"),
            annualized_dividend=Decimal("0.00"),
            annualized_total=Decimal("1.00"),
            currency="SGDX",
            as_of=date(2026, 5, 20),
        )


def test_AC5_32_2_annualized_income_totals_is_typed_intermediate():
    """AC5.32.2: AnnualizedIncomeTotals is a typed Decimal accumulator, not a str-keyed dict."""
    totals = AnnualizedIncomeTotals()
    assert (totals.salary, totals.bonus, totals.dividend, totals.total) == (
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("0.00"),
    )

    totals.add("salary", Decimal("120000.00"))
    totals.add("bonus", Decimal("15000.00"))
    totals.add(None, Decimal("300.00"))  # unbucketed income still hits the total

    assert totals.salary == Decimal("120000.00")
    assert totals.bonus == Decimal("15000.00")
    assert totals.dividend == Decimal("0.00")
    assert totals.total == Decimal("135300.00")
    # Decimal throughout — never float.
    assert all(isinstance(v, Decimal) for v in (totals.salary, totals.bonus, totals.dividend, totals.total))


def test_AC5_32_3_resolve_line_currency_uses_canonical_fallback_chain():
    """AC5.32.3: resolve_line_currency centralizes line||account||base resolution + normalization."""
    account = Account(name="Salary", type=AccountType.INCOME, currency="usd")
    line_with_currency = JournalLine(direction=Direction.CREDIT, amount=Decimal("1.00"), currency="eur")
    line_no_currency = JournalLine(direction=Direction.CREDIT, amount=Decimal("1.00"), currency=None)

    assert resolve_line_currency(line_with_currency, account, base_currency="SGD") == "EUR"
    assert resolve_line_currency(line_no_currency, account, base_currency="SGD") == "USD"

    account_no_currency = Account(name="Salary", type=AccountType.INCOME, currency=None)
    assert resolve_line_currency(line_no_currency, account_no_currency, base_currency="sgd") == "SGD"


def test_AC5_32_4_fx_conversion_error_response_model_declared():
    """AC5.32.4: an explicit FX-error response model exists for the income endpoint."""
    err = FxConversionErrorResponse(detail="no FX rate for USD/SGD")
    assert err.detail == "no FX rate for USD/SGD"


def test_AC5_32_5_normalize_currency_code_is_shared_helper():
    """AC5.32.5: the currency normalizer is a single shared helper (no duplicated .strip().upper())."""
    assert normalize_currency_code("  sgd ") == "SGD"
    assert normalize_currency_code("usd") == "USD"


async def test_AC5_32_6_endpoint_returns_normalized_currency_for_soft_base_config(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
):
    """AC5.32.6: endpoint normalizes a soft (lower-case) base currency setting in its response."""
    from src import config

    monkeypatch.setattr(config.settings, "base_currency", "sgd")

    salary = Account(user_id=test_user.id, name="Salary Income", type=AccountType.INCOME, currency="SGD")
    cash = Account(user_id=test_user.id, name="Cash", type=AccountType.ASSET, currency="SGD")
    db.add_all([salary, cash])
    await db.flush()
    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date(2026, 5, 1),
        memo="income",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=salary.id,
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    response = await client.get("/income/annualized?as_of=2026-05-20")
    assert response.status_code == 200
    data = response.json()
    assert data["currency"] == "SGD"
    assert data["annualized_salary"] == "100.00"
    assert data["annualized_total"] == "100.00"
