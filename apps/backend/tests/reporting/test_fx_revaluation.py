from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.ledger import Account, AccountType, Direction
from src.ledger.extension.fx_revaluation import (
    RevaluationError,
    calculate_account_balance_in_currency,
    calculate_unrealized_fx_for_account,
    calculate_unrealized_fx_gains,
    get_foreign_currency_accounts,
)
from src.pricing import PricingError
from tests.reporting._report_fixtures import post_lines, seed_accounts, seed_fx_rates


@pytest.fixture
async def fx_reval_accounts(db: AsyncSession, test_user_id):
    return await seed_accounts(
        db,
        test_user_id,
        ("USD Savings", AccountType.ASSET, "USD", {"code": "ASSET-USD-001"}),
        ("SGD Savings", AccountType.ASSET, "SGD", {"code": "ASSET-SGD-001"}),
        ("Salary Income", AccountType.INCOME, "SGD", {"code": "INCOME-001"}),
        commit=True,
    )


async def test_get_foreign_currency_accounts_filters_types_and_currency(
    db: AsyncSession, test_user_id, fx_reval_accounts
) -> None:
    await seed_accounts(db, test_user_id, ("USD Income", AccountType.INCOME, "USD"), commit=True)
    accounts = await get_foreign_currency_accounts(db, test_user_id, base_currency="SGD")
    assert "USD" in [a.currency for a in accounts] and "SGD" not in [a.currency for a in accounts]
    assert all(a.type in (AccountType.ASSET, AccountType.LIABILITY) for a in accounts)


async def test_calculate_unrealized_fx_gains_empty_and_none_skipped(
    db: AsyncSession, test_user_id, fx_reval_accounts
) -> None:
    res = await calculate_unrealized_fx_gains(db, test_user_id, date(2025, 1, 31), base_currency="SGD")
    assert (res.accounts_revalued, res.total_unrealized_gain_loss) == ([], Decimal("0"))
    with patch(
        "src.ledger.extension.fx_revaluation.calculate_unrealized_fx_for_account",
        new_callable=AsyncMock,
        return_value=None,
    ):
        res_none = await calculate_unrealized_fx_gains(db, test_user_id, date(2025, 1, 31), base_currency="SGD")
        assert (res_none.accounts_revalued, res_none.total_unrealized_gain_loss) == ([], Decimal("0"))


async def test_calculate_unrealized_fx_revaluation_and_reval_entry_isolation(
    db: AsyncSession, test_user_id, fx_reval_accounts
) -> None:
    usd_acc, sgd_acc, _ = fx_reval_accounts
    assert await calculate_unrealized_fx_for_account(db, usd_acc, date(2025, 1, 31), "SGD") is None
    await seed_fx_rates(db, ("USD", "SGD", "1.35", date(2025, 1, 31)))
    await post_lines(
        db,
        test_user_id,
        date(2025, 1, 15),
        "USD deposit",
        [
            (usd_acc, Direction.DEBIT, "1000", "USD", Decimal("1.30")),
            (sgd_acc, Direction.CREDIT, "1300", "SGD", Decimal("1")),
        ],
    )
    await post_lines(
        db,
        test_user_id,
        date(2025, 1, 31),
        "FX Reval",
        [(usd_acc, Direction.DEBIT, "50", "SGD", Decimal("1")), (sgd_acc, Direction.CREDIT, "50", "SGD", Decimal("1"))],
        source_type=JournalEntrySourceType.FX_REVALUATION,
        commit=True,
    )

    gains = await calculate_unrealized_fx_gains(db, test_user_id, date(2025, 1, 31), base_currency="SGD")
    assert (gains.revaluation_date, gains.base_currency, gains.accounts_revalued[0].account_id) == (
        date(2025, 1, 31),
        "SGD",
        usd_acc.id,
    )
    r = await calculate_unrealized_fx_for_account(db, usd_acc, date(2025, 1, 31), "SGD")
    assert (
        r.account_currency,
        r.original_balance,
        r.fx_rate_used,
        r.original_balance_base,
        r.revalued_balance_base,
        r.unrealized_gain_loss,
    ) == ("USD", Decimal("1000"), Decimal("1.35"), Decimal("1300"), Decimal("1350"), Decimal("50"))


@pytest.mark.parametrize("mock_pricing", [False, True])
async def test_calculate_unrealized_fx_missing_rate_raises(
    db: AsyncSession, test_user_id, fx_reval_accounts, mock_pricing: bool
) -> None:
    _, sgd_acc, _ = fx_reval_accounts
    ccy = "USD" if mock_pricing else "EUR"
    [foreign] = await seed_accounts(db, test_user_id, (f"{ccy} Savings", AccountType.ASSET, ccy), commit=True)
    await post_lines(
        db,
        test_user_id,
        date(2025, 1, 15),
        "Dep",
        [
            (foreign, Direction.DEBIT, "1000", ccy, Decimal("1.30")),
            (sgd_acc, Direction.CREDIT, "1300", "SGD", Decimal("1")),
        ],
        commit=True,
    )
    if mock_pricing:
        with (
            patch(
                "src.ledger.extension.fx_revaluation.get_exchange_rate", side_effect=PricingError("No rate")
            ) as mock_get,
            pytest.raises(RevaluationError, match="Missing FX rate for USD/SGD"),
        ):
            await calculate_unrealized_fx_for_account(db, foreign, date(2025, 1, 31), "SGD")
        mock_get.assert_called_once()
    else:
        with pytest.raises(RevaluationError, match="Missing FX rate for EUR/SGD"):
            await calculate_unrealized_fx_for_account(db, foreign, date(2025, 1, 31), "SGD")


async def test_calculate_account_balance_in_currency_asset_zero_and_liability(
    db: AsyncSession, test_user_id, fx_reval_accounts
) -> None:
    usd_acc, sgd_acc, _ = fx_reval_accounts
    assert await calculate_account_balance_in_currency(db, usd_acc) == Decimal("0")
    await post_lines(
        db,
        test_user_id,
        date(2025, 1, 15),
        "Dep",
        [
            (usd_acc, Direction.DEBIT, "500", "USD", Decimal("1.30")),
            (sgd_acc, Direction.CREDIT, "650", "SGD", Decimal("1")),
        ],
        commit=True,
    )
    assert await calculate_account_balance_in_currency(db, usd_acc) == Decimal("500")

    loan, offset = await seed_accounts(
        db, test_user_id, ("Loan USD", AccountType.LIABILITY, "USD"), ("Offset USD", AccountType.ASSET, "USD")
    )
    await post_lines(
        db,
        test_user_id,
        date(2025, 1, 1),
        "Liab",
        [
            (loan, Direction.DEBIT, "200", "USD", Decimal("1")),
            (loan, Direction.CREDIT, "500", "USD", Decimal("1")),
            (offset, Direction.DEBIT, "300", "USD", Decimal("1")),
        ],
        commit=True,
    )
    assert await calculate_account_balance_in_currency(db, loan) == Decimal("300")
