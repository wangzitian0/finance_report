"""Tests for the unrealized FX calculation (read-only; no revaluation entry is booked)."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.ledger.extension.fx_revaluation import (
    RevaluationError,
    calculate_account_balance_in_currency,
    calculate_unrealized_fx_for_account,
    calculate_unrealized_fx_gains,
    get_foreign_currency_accounts,
)
from src.pricing import PricingError
from src.pricing.orm.market_data import FxRate


@pytest.fixture
async def usd_asset_account(db: AsyncSession, test_user_id):
    account = Account(
        user_id=test_user_id,
        name="USD Savings",
        code="ASSET-USD-001",
        type=AccountType.ASSET,
        currency="USD",
        is_active=True,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


@pytest.fixture
async def sgd_asset_account(db: AsyncSession, test_user_id):
    account = Account(
        user_id=test_user_id,
        name="SGD Savings",
        code="ASSET-SGD-001",
        type=AccountType.ASSET,
        currency="SGD",
        is_active=True,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


@pytest.fixture
async def income_account(db: AsyncSession, test_user_id):
    account = Account(
        user_id=test_user_id,
        name="Salary Income",
        code="INCOME-001",
        type=AccountType.INCOME,
        currency="SGD",
        is_active=True,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


@pytest.fixture
async def fx_rate_usd_sgd(db: AsyncSession):
    rate = FxRate(
        base_currency="USD",
        quote_currency="SGD",
        rate=Decimal("1.35"),
        rate_date=date(2025, 1, 31),
        source="test",
    )
    db.add(rate)
    await db.commit()
    return rate


class TestGetForeignCurrencyAccounts:
    async def test_returns_only_foreign_currency_asset_liability(
        self, db: AsyncSession, test_user_id, usd_asset_account, sgd_asset_account
    ):
        accounts = await get_foreign_currency_accounts(db, test_user_id)

        account_currencies = [a.currency for a in accounts]
        assert "USD" in account_currencies
        assert "SGD" not in account_currencies

    async def test_excludes_income_expense_accounts(self, db: AsyncSession, test_user_id, income_account):
        usd_income = Account(
            user_id=test_user_id,
            name="USD Income",
            type=AccountType.INCOME,
            currency="USD",
            is_active=True,
        )
        db.add(usd_income)
        await db.commit()

        accounts = await get_foreign_currency_accounts(db, test_user_id)

        assert all(a.type in (AccountType.ASSET, AccountType.LIABILITY) for a in accounts)


class TestCalculateUnrealizedFxGains:
    async def test_returns_empty_for_no_foreign_accounts(self, db: AsyncSession, test_user_id, sgd_asset_account):
        result = await calculate_unrealized_fx_gains(db, test_user_id, date(2025, 1, 31))

        assert result.accounts_revalued == []
        assert result.total_unrealized_gain_loss == Decimal("0")

    async def test_calculates_gains_for_foreign_accounts_with_balance(
        self, db: AsyncSession, test_user_id, usd_asset_account, sgd_asset_account, fx_rate_usd_sgd
    ):
        entry = JournalEntry(
            user_id=test_user_id,
            entry_date=date(2025, 1, 15),
            memo="USD deposit",
            source_type=JournalEntrySourceType.MANUAL,
            status=JournalEntryStatus.POSTED,
        )
        db.add(entry)
        await db.flush()

        lines = [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=usd_asset_account.id,
                direction=Direction.DEBIT,
                amount=Decimal("1000"),
                currency="USD",
                fx_rate=Decimal("1.30"),
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=sgd_asset_account.id,
                direction=Direction.CREDIT,
                amount=Decimal("1300"),
                currency="SGD",
                fx_rate=Decimal("1"),
            ),
        ]
        db.add_all(lines)
        await db.commit()

        result = await calculate_unrealized_fx_gains(db, test_user_id, date(2025, 1, 31))

        assert result.revaluation_date == date(2025, 1, 31)
        assert result.base_currency == "SGD"
        assert len(result.accounts_revalued) == 1
        assert result.accounts_revalued[0].account_id == usd_asset_account.id


class TestCalculateUnrealizedFxForAccount:
    async def test_returns_none_for_zero_balance(self, db: AsyncSession, test_user_id, usd_asset_account):
        """Account with no transactions should return None."""
        result = await calculate_unrealized_fx_for_account(db, usd_asset_account, date(2025, 1, 31), "SGD")
        assert result is None

    async def test_raises_error_when_fx_rate_not_found(self, db: AsyncSession, test_user_id):
        """Account with balance but no FX rate should raise RevaluationError."""
        # Create EUR account (no FX rate will exist for EUR)
        eur_account = Account(
            user_id=test_user_id,
            name="EUR Savings",
            code="ASSET-EUR-001",
            type=AccountType.ASSET,
            currency="EUR",
            is_active=True,
        )
        db.add(eur_account)
        await db.commit()
        await db.refresh(eur_account)

        # Create entry to give account a balance
        sgd_account = Account(
            user_id=test_user_id,
            name="SGD Account",
            code="ASSET-SGD-002",
            type=AccountType.ASSET,
            currency="SGD",
            is_active=True,
        )
        db.add(sgd_account)
        await db.commit()

        entry = JournalEntry(
            user_id=test_user_id,
            entry_date=date(2025, 1, 15),
            memo="EUR deposit",
            source_type=JournalEntrySourceType.MANUAL,
            status=JournalEntryStatus.POSTED,
        )
        db.add(entry)
        await db.flush()

        lines = [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=eur_account.id,
                direction=Direction.DEBIT,
                amount=Decimal("1000"),
                currency="EUR",
                fx_rate=Decimal("1.50"),
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=sgd_account.id,
                direction=Direction.CREDIT,
                amount=Decimal("1500"),
                currency="SGD",
                fx_rate=Decimal("1"),
            ),
        ]
        db.add_all(lines)
        await db.commit()

        # No EUR/SGD rate exists, should raise RevaluationError
        with pytest.raises(RevaluationError, match="Missing FX rate for EUR/SGD"):
            await calculate_unrealized_fx_for_account(db, eur_account, date(2025, 1, 31), "SGD")

    @patch("src.ledger.extension.fx_revaluation.get_exchange_rate")
    async def test_handles_fx_rate_error_exception(
        self, mock_get_rate, db: AsyncSession, test_user_id, usd_asset_account, sgd_asset_account
    ):
        """Test that a PricingError (FX miss) is re-raised as RevaluationError."""
        mock_get_rate.side_effect = PricingError("No rate found for USD/SGD")

        entry = JournalEntry(
            user_id=test_user_id,
            entry_date=date(2025, 1, 15),
            memo="USD deposit",
            source_type=JournalEntrySourceType.MANUAL,
            status=JournalEntryStatus.POSTED,
        )
        db.add(entry)
        await db.flush()

        lines = [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=usd_asset_account.id,
                direction=Direction.DEBIT,
                amount=Decimal("1000"),
                currency="USD",
                fx_rate=Decimal("1.30"),
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=sgd_asset_account.id,
                direction=Direction.CREDIT,
                amount=Decimal("1300"),
                currency="SGD",
                fx_rate=Decimal("1"),
            ),
        ]
        db.add_all(lines)
        await db.commit()

        with pytest.raises(RevaluationError, match="Missing FX rate for USD/SGD"):
            await calculate_unrealized_fx_for_account(db, usd_asset_account, date(2025, 1, 31), "SGD")
        mock_get_rate.assert_called_once()

    async def test_calculates_revaluation_with_fx_rate(
        self, db: AsyncSession, test_user_id, usd_asset_account, sgd_asset_account, fx_rate_usd_sgd
    ):
        """Account with balance and FX rate should return revaluation."""
        # Create entry to give USD account a balance
        entry = JournalEntry(
            user_id=test_user_id,
            entry_date=date(2025, 1, 15),
            memo="USD deposit",
            source_type=JournalEntrySourceType.MANUAL,
            status=JournalEntryStatus.POSTED,
        )
        db.add(entry)
        await db.flush()

        lines = [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=usd_asset_account.id,
                direction=Direction.DEBIT,
                amount=Decimal("1000"),
                currency="USD",
                fx_rate=Decimal("1.30"),
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=sgd_asset_account.id,
                direction=Direction.CREDIT,
                amount=Decimal("1300"),
                currency="SGD",
                fx_rate=Decimal("1"),
            ),
        ]
        db.add_all(lines)
        await db.commit()
        await db.refresh(usd_asset_account)

        result = await calculate_unrealized_fx_for_account(db, usd_asset_account, date(2025, 1, 31), "SGD")

        assert result is not None
        assert result.account_id == usd_asset_account.id
        assert result.account_currency == "USD"
        assert result.original_balance == Decimal("1000")
        assert result.fx_rate_used == Decimal("1.35")

        # New assertions for historical cost logic
        # Cost basis: 1000 * 1.30 = 1300
        # Current value: 1000 * 1.35 = 1350
        # Gain: 50
        assert result.original_balance_base == Decimal("1300")
        assert result.revalued_balance_base == Decimal("1350")
        assert result.unrealized_gain_loss == Decimal("50")

    async def test_revaluation_entries_do_not_change_native_balance_or_historical_cost(
        self, db: AsyncSession, test_user_id, usd_asset_account, sgd_asset_account, fx_rate_usd_sgd
    ):
        """AC5.1.2: Posted FX revaluation entries are excluded from native balance and historical cost."""
        deposit = JournalEntry(
            user_id=test_user_id,
            entry_date=date(2025, 1, 15),
            memo="USD deposit",
            source_type=JournalEntrySourceType.MANUAL,
            status=JournalEntryStatus.POSTED,
        )
        db.add(deposit)
        await db.flush()
        db.add_all(
            [
                JournalLine(
                    journal_entry_id=deposit.id,
                    account_id=usd_asset_account.id,
                    direction=Direction.DEBIT,
                    amount=Decimal("1000"),
                    currency="USD",
                    fx_rate=Decimal("1.30"),
                ),
                JournalLine(
                    journal_entry_id=deposit.id,
                    account_id=sgd_asset_account.id,
                    direction=Direction.CREDIT,
                    amount=Decimal("1300"),
                    currency="SGD",
                    fx_rate=Decimal("1"),
                ),
            ]
        )

        revaluation = JournalEntry(
            user_id=test_user_id,
            entry_date=date(2025, 1, 31),
            memo="FX Revaluation",
            source_type=JournalEntrySourceType.FX_REVALUATION,
            status=JournalEntryStatus.POSTED,
        )
        db.add(revaluation)
        await db.flush()
        db.add_all(
            [
                JournalLine(
                    journal_entry_id=revaluation.id,
                    account_id=usd_asset_account.id,
                    direction=Direction.DEBIT,
                    amount=Decimal("50"),
                    currency="SGD",
                    fx_rate=Decimal("1"),
                ),
                JournalLine(
                    journal_entry_id=revaluation.id,
                    account_id=sgd_asset_account.id,
                    direction=Direction.CREDIT,
                    amount=Decimal("50"),
                    currency="SGD",
                    fx_rate=Decimal("1"),
                ),
            ]
        )
        await db.commit()

        result = await calculate_unrealized_fx_for_account(db, usd_asset_account, date(2025, 1, 31), "SGD")

        assert result is not None
        assert result.original_balance == Decimal("1000")
        assert result.original_balance_base == Decimal("1300")
        assert result.revalued_balance_base == Decimal("1350")
        assert result.unrealized_gain_loss == Decimal("50")


class TestCalculateAccountBalanceInCurrency:
    async def test_returns_balance_for_account_with_entries(
        self, db: AsyncSession, test_user_id, usd_asset_account, sgd_asset_account
    ):
        """Test balance calculation for account with journal entries."""
        # Create entry
        entry = JournalEntry(
            user_id=test_user_id,
            entry_date=date(2025, 1, 15),
            memo="Deposit",
            source_type=JournalEntrySourceType.MANUAL,
            status=JournalEntryStatus.POSTED,
        )
        db.add(entry)
        await db.flush()

        lines = [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=usd_asset_account.id,
                direction=Direction.DEBIT,
                amount=Decimal("500"),
                currency="USD",
                fx_rate=Decimal("1.30"),
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=sgd_asset_account.id,
                direction=Direction.CREDIT,
                amount=Decimal("650"),
                currency="SGD",
                fx_rate=Decimal("1"),
            ),
        ]
        db.add_all(lines)
        await db.commit()

        balance = await calculate_account_balance_in_currency(db, usd_asset_account)
        assert balance == Decimal("500")

    async def test_returns_zero_for_account_without_entries(self, db: AsyncSession, test_user_id, usd_asset_account):
        """Test balance is zero for account with no entries."""
        balance = await calculate_account_balance_in_currency(db, usd_asset_account)
        assert balance == Decimal("0")


# ---------------------------------------------------------------------------
# Additional coverage tests – AC8.12.x
# ---------------------------------------------------------------------------


class TestCalculateAccountBalanceInCurrencyLiability:
    """Test liability/equity accounts return negated balance (line 141 else branch)."""

    async def test_returns_negated_balance_for_liability_account(self, db: AsyncSession, test_user_id):
        """AC-ledger.fxrevaluation.1: AC8.12.1 – Liability accounts return -net_balance so coverage hits else branch."""
        liability_account = Account(
            user_id=test_user_id,
            name="Loan USD",
            code="LIAB-USD-001",
            type=AccountType.LIABILITY,
            currency="USD",
            is_active=True,
        )
        offset_account = Account(
            user_id=test_user_id,
            name="Liability Offset USD",
            code="ASSET-USD-OFFSET",
            type=AccountType.ASSET,
            currency="USD",
            is_active=True,
        )
        db.add_all([liability_account, offset_account])
        await db.flush()

        entry = JournalEntry(
            user_id=test_user_id,
            entry_date=date(2025, 1, 1),
            memo="Liability test",
            status=JournalEntryStatus.POSTED,
            source_type=JournalEntrySourceType.MANUAL,
        )
        db.add(entry)
        await db.flush()

        debit_line = JournalLine(
            journal_entry_id=entry.id,
            account_id=liability_account.id,
            direction=Direction.DEBIT,
            amount=Decimal("200"),
            currency="USD",
            fx_rate=Decimal("1"),
        )
        credit_line = JournalLine(
            journal_entry_id=entry.id,
            account_id=liability_account.id,
            direction=Direction.CREDIT,
            amount=Decimal("500"),
            currency="USD",
            fx_rate=Decimal("1"),
        )
        offset_line = JournalLine(
            journal_entry_id=entry.id,
            account_id=offset_account.id,
            direction=Direction.DEBIT,
            amount=Decimal("300"),
            currency="USD",
            fx_rate=Decimal("1"),
        )
        db.add_all([debit_line, credit_line, offset_line])
        await db.commit()

        balance = await calculate_account_balance_in_currency(db, liability_account)
        # net_balance = debit - credit = 200 - 500 = -300; liability => return -(-300) = 300
        assert balance == Decimal("300")


class TestCalculateUnrealizedFxGainsNoneFiltering:
    """Test that accounts where reval is None are filtered out (line 209 branch)."""

    async def test_none_revaluation_skipped(self, db: AsyncSession, test_user_id, usd_asset_account):
        """AC-ledger.fxrevaluation.3: AC8.12.3 – Accounts that return None from calculate_unrealized_fx_for_account are skipped."""
        from unittest.mock import AsyncMock, patch

        with patch(
            "src.ledger.extension.fx_revaluation.calculate_unrealized_fx_for_account",
            new_callable=AsyncMock,
        ) as mock_calc:
            mock_calc.return_value = None

            result = await calculate_unrealized_fx_gains(db, test_user_id, date(2025, 1, 31))

        assert result.accounts_revalued == []
        assert result.total_unrealized_gain_loss == Decimal("0")
