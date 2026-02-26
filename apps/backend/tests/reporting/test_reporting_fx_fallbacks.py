"""Tests for reporting.py and reports router coverage gaps."""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession\nfrom sqlalchemy.orm import selectinload\nfrom sqlalchemy.orm import selectinload

from src.models import (
    Account,
    AccountType,
    Direction,
    FxRate,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
)
from src.services.reporting import (
    ReportError,
    _aggregate_balances_sql,
    _aggregate_net_income_sql,
    generate_balance_sheet,
    generate_cash_flow,
    generate_income_statement,
    get_account_trend,
    get_category_breakdown,
)


@pytest.fixture
def user_id():
    return uuid4()


@pytest.fixture
async def accounts(db: AsyncSession, user_id):
    accs = [
        Account(user_id=user_id, name="SGD Cash", type=AccountType.ASSET, currency="SGD"),
        Account(user_id=user_id, name="USD Savings", type=AccountType.ASSET, currency="USD"),
        Account(user_id=user_id, name="Capital", type=AccountType.EQUITY, currency="SGD"),
        Account(user_id=user_id, name="Salary", type=AccountType.INCOME, currency="SGD"),
        Account(user_id=user_id, name="Dining", type=AccountType.EXPENSE, currency="SGD"),
    ]
    db.add_all(accs)
    await db.commit()
    for a in accs:
        await db.refresh(a)
    return accs


@pytest.mark.asyncio
async def test_aggregate_balances_with_start_date(db: AsyncSession, accounts, user_id):
    """
    GIVEN entries before and during a date range
    WHEN _aggregate_balances_sql is called with start_date
    THEN only entries after start_date are included
    """
    sgd_cash, _, capital, salary, _ = accounts

    entry_before = JournalEntry(
        user_id=user_id,
        entry_date=date(2025, 1, 1),
        memo="Before period",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry_before)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry_before.id,
                account_id=sgd_cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("500.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_before.id,
                account_id=capital.id,
                direction=Direction.CREDIT,
                amount=Decimal("500.00"),
                currency="SGD",
            ),
        ]
    )

    entry_during = JournalEntry(
        user_id=user_id,
        entry_date=date(2025, 2, 1),
        memo="During period",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry_during)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry_during.id,
                account_id=sgd_cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("300.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_during.id,
                account_id=capital.id,
                direction=Direction.CREDIT,
                amount=Decimal("300.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    balances_all = await _aggregate_balances_sql(db, user_id, (AccountType.ASSET,), "SGD", date(2025, 3, 1))
    assert balances_all[sgd_cash.id] == Decimal("800.00")

    balances_filtered = await _aggregate_balances_sql(
        db, user_id, (AccountType.ASSET,), "SGD", date(2025, 3, 1), start_date=date(2025, 1, 15)
    )
    assert balances_filtered[sgd_cash.id] == Decimal("300.00")


@pytest.mark.asyncio
async def test_aggregate_net_income_with_start_date(db: AsyncSession, accounts, user_id):
    """
    GIVEN income entries before and during a date range
    WHEN _aggregate_net_income_sql is called with start_date
    THEN only entries after start_date are included
    """
    sgd_cash, _, _, salary, dining = accounts

    entry_before = JournalEntry(
        user_id=user_id,
        entry_date=date(2025, 1, 1),
        memo="Old income",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry_before)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry_before.id,
                account_id=sgd_cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("1000.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_before.id,
                account_id=salary.id,
                direction=Direction.CREDIT,
                amount=Decimal("1000.00"),
                currency="SGD",
            ),
        ]
    )

    entry_during = JournalEntry(
        user_id=user_id,
        entry_date=date(2025, 2, 15),
        memo="New income",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry_during)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry_during.id,
                account_id=sgd_cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("500.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_during.id,
                account_id=salary.id,
                direction=Direction.CREDIT,
                amount=Decimal("500.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    net_all = await _aggregate_net_income_sql(db, user_id, "SGD", date(2025, 3, 1))
    assert net_all == Decimal("1500.00")

    net_filtered = await _aggregate_net_income_sql(db, user_id, "SGD", date(2025, 3, 1), start_date=date(2025, 2, 1))
    assert net_filtered == Decimal("500.00")


@pytest.mark.asyncio
async def test_net_income_fx_data_consistency_error(db: AsyncSession, accounts, user_id):
    """
    GIVEN a multi-currency entry with FX rate gap
    WHEN _aggregate_net_income_sql encounters missing fx_rate_map key
    THEN ReportError is raised
    """
    sgd_cash, _, _, salary, _ = accounts

    entry = JournalEntry(
        user_id=user_id,
        entry_date=date(2025, 1, 15),
        memo="Income",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=sgd_cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
                currency="USD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=salary.id,
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
                currency="USD",
            ),
        ]
    )

    db.add(
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.35"),
            rate_date=date(2025, 1, 31),
            source="test",
        )
    )
    await db.commit()

    with patch("src.services.reporting._aggregate_net_income_sql") as mock_func:
        mock_func.side_effect = ReportError("Missing FX rate for USD/SGD on 2025-01-15 - data consistency error")
        with pytest.raises(ReportError, match="data consistency error"):
            await generate_balance_sheet(db, user_id, as_of_date=date(2025, 1, 31), currency="SGD")


@pytest.mark.asyncio
async def test_balance_sheet_sqlalchemy_error_on_aggregation(db: AsyncSession, accounts, user_id):
    """
    GIVEN _aggregate_balances_sql raises SQLAlchemyError
    WHEN generate_balance_sheet is called
    THEN ReportError is raised wrapping the DB error
    """
    with patch(
        "src.services.reporting._aggregate_balances_sql",
        new_callable=AsyncMock,
    ) as mock_agg:
        mock_agg.side_effect = SQLAlchemyError("DB connection lost")

        with pytest.raises(ReportError, match="DB connection lost"):
            await generate_balance_sheet(db, user_id, as_of_date=date(2025, 1, 31), currency="SGD")


@pytest.mark.asyncio
async def test_balance_sheet_sqlalchemy_error_on_net_income(db: AsyncSession, accounts, user_id):
    """
    GIVEN _aggregate_net_income_sql raises SQLAlchemyError
    WHEN generate_balance_sheet is called
    THEN ReportError is raised wrapping the DB error
    """
    with patch(
        "src.services.reporting._aggregate_net_income_sql",
        new_callable=AsyncMock,
    ) as mock_net:
        mock_net.side_effect = SQLAlchemyError("Timeout during net income calc")

        with pytest.raises(ReportError, match="Timeout during net income calc"):
            await generate_balance_sheet(db, user_id, as_of_date=date(2025, 1, 31), currency="SGD")


@pytest.mark.asyncio
async def test_income_statement_fx_average_to_spot_fallback(db: AsyncSession, accounts, user_id):
    """
    GIVEN a USD income entry with SGD target currency
    WHEN PrefetchedFxRates returns None and average rate convert fails
    THEN fallback to spot rate conversion succeeds
    """
    sgd_cash, _, _, salary, _ = accounts

    entry = JournalEntry(
        user_id=user_id,
        entry_date=date(2025, 1, 15),
        memo="USD Income",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=sgd_cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
                currency="USD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=salary.id,
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
                currency="USD",
            ),
        ]
    )

    db.add(
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.35"),
            rate_date=date(2025, 1, 31),
            source="test",
        )
    )
    await db.commit()

    from src.services.fx import FxRateError

    with patch("src.services.reporting.PrefetchedFxRates") as MockPrefetched:
        mock_instance = AsyncMock()
        mock_instance.prefetch = AsyncMock()

        def mock_get_rate(currency, target, rate_date, avg_start=None, avg_end=None):
            return None

        mock_instance.get_rate = mock_get_rate
        MockPrefetched.return_value = mock_instance

        async def mock_convert(db, amount, currency, target_currency, rate_date, **kwargs):
            if kwargs.get("average_start") is not None:
                raise FxRateError("No average rate available")
            return amount * Decimal("1.35")

        with patch("src.services.reporting.convert_amount", side_effect=mock_convert):
            report = await generate_income_statement(
                db, user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
            )
            assert report["total_income"] == Decimal("135.00")


@pytest.mark.asyncio
async def test_income_statement_fx_all_fallbacks_fail(db: AsyncSession, accounts, user_id):
    """
    GIVEN a USD income entry with SGD target currency
    WHEN both average and spot FX lookups fail
    THEN ReportError is raised
    """
    sgd_cash, _, _, salary, _ = accounts

    entry = JournalEntry(
        user_id=user_id,
        entry_date=date(2025, 1, 15),
        memo="USD Income",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=sgd_cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
                currency="USD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=salary.id,
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
                currency="USD",
            ),
        ]
    )
    db.add(
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.35"),
            rate_date=date(2025, 1, 31),
            source="test",
        )
    )
    await db.commit()

    from src.services.fx import FxRateError

    with patch("src.services.reporting.PrefetchedFxRates") as MockPrefetched:
        mock_instance = AsyncMock()
        mock_instance.prefetch = AsyncMock()
        mock_instance.get_rate = lambda *args, **kwargs: None
        MockPrefetched.return_value = mock_instance

        async def mock_convert_fail(db, amount, currency, target_currency, rate_date, **kwargs):
            raise FxRateError("No rate available at all")

        with patch("src.services.reporting.convert_amount", side_effect=mock_convert_fail):
            with pytest.raises(ReportError, match="FX conversion failed"):
                await generate_income_statement(
                    db, user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
                )


@pytest.mark.asyncio
async def test_trend_same_currency_rate_none_fallback(db: AsyncSession, accounts, user_id):
    """
    GIVEN a same-currency (SGD/SGD) account trend request
    WHEN PrefetchedFxRates.get_rate returns None
    THEN fallback to Decimal("1") rate succeeds
    """
    sgd_cash, _, _, salary, _ = accounts

    entry = JournalEntry(
        user_id=user_id,
        entry_date=date.today(),
        memo="SGD Income",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=sgd_cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("200.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=salary.id,
                direction=Direction.CREDIT,
                amount=Decimal("200.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    with patch("src.services.reporting.PrefetchedFxRates") as MockPrefetched:
        mock_instance = AsyncMock()
        mock_instance.prefetch = AsyncMock()
        mock_instance.get_rate = lambda *args, **kwargs: None
        MockPrefetched.return_value = mock_instance

        result = await get_account_trend(db, user_id, account_id=sgd_cash.id, period="daily", currency="SGD")
        assert isinstance(result["points"], list)


@pytest.mark.asyncio
async def test_breakdown_same_currency_rate_none_fallback(db: AsyncSession, accounts, user_id):
    """
    GIVEN a same-currency (SGD/SGD) category breakdown request
    WHEN PrefetchedFxRates.get_rate returns None
    THEN fallback to Decimal("1") rate succeeds
    """
    _, _, _, salary, _ = accounts

    entry = JournalEntry(
        user_id=user_id,
        entry_date=date.today(),
        memo="SGD Income",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=salary.id,
                direction=Direction.CREDIT,
                amount=Decimal("300.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    with patch("src.services.reporting.PrefetchedFxRates") as MockPrefetched:
        mock_instance = AsyncMock()
        mock_instance.prefetch = AsyncMock()
        mock_instance.get_rate = lambda *args, **kwargs: None
        MockPrefetched.return_value = mock_instance

        result = await get_category_breakdown(
            db, user_id, breakdown_type=AccountType.INCOME, period="monthly", currency="SGD"
        )
        assert isinstance(result["items"], list)


@pytest.mark.asyncio
async def test_cash_flow_same_currency_rate_none_fallback(db: AsyncSession, accounts, user_id):
    """
    GIVEN same-currency (SGD/SGD) cash flow entries before and during period
    WHEN PrefetchedFxRates.get_rate returns None for both periods
    THEN fallback to Decimal("1") rate succeeds for both
    """
    sgd_cash, _, capital, salary, _ = accounts
    sgd_cash.name = "SGD Bank Cash"
    db.add(sgd_cash)

    entry_before = JournalEntry(
        user_id=user_id,
        entry_date=date(2024, 12, 15),
        memo="Before period",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry_before)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry_before.id,
                account_id=sgd_cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("500.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_before.id,
                account_id=capital.id,
                direction=Direction.CREDIT,
                amount=Decimal("500.00"),
                currency="SGD",
            ),
        ]
    )

    entry_during = JournalEntry(
        user_id=user_id,
        entry_date=date(2025, 1, 15),
        memo="During period",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry_during)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry_during.id,
                account_id=sgd_cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("300.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry_during.id,
                account_id=salary.id,
                direction=Direction.CREDIT,
                amount=Decimal("300.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    with patch("src.services.reporting.PrefetchedFxRates") as MockPrefetched:
        mock_instance = AsyncMock()
        mock_instance.prefetch = AsyncMock()
        mock_instance.get_rate = lambda *args, **kwargs: None
        MockPrefetched.return_value = mock_instance

        result = await generate_cash_flow(
            db, user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
        )
        assert isinstance(result["summary"], dict)


@pytest.mark.asyncio
async def test_currencies_endpoint_inserts_base_currency(client, db, test_user):
    """
    GIVEN no FX rates exist in the database
    WHEN GET /reports/currencies is called
    THEN base_currency (SGD) is present in the result
    """
    response = await client.get("/reports/currencies")
    assert response.status_code == 200
    currencies = response.json()
    assert "SGD" in currencies


@pytest.mark.asyncio
async def test_currencies_endpoint_with_rates_not_including_base(client, db, test_user):
    """
    GIVEN FX rates exist only between non-base currencies (JPY/KRW)
    WHEN GET /reports/currencies is called
    THEN base_currency (SGD) is prepended to the list
    """
    db.add(
        FxRate(
            base_currency="JPY",
            quote_currency="KRW",
            rate=Decimal("10.00"),
            rate_date=date(2025, 1, 1),
            source="test",
        )
    )
    await db.commit()

    response = await client.get("/reports/currencies")
    assert response.status_code == 200
    currencies = response.json()
    assert currencies[0] == "SGD"
    assert "JPY" in currencies
    assert "KRW" in currencies
