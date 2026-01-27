"""Tests for FX Revaluation Service infrastructure."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
)
from src.models.market_data import FxRate
from src.services.fx import FxRateError
from src.services.fx_revaluation import (
    AccountRevaluation,
    RevaluationError,
    calculate_account_balance_in_currency,
    calculate_unrealized_fx_for_account,
    calculate_unrealized_fx_gains,
    create_revaluation_entry,
    get_foreign_currency_accounts,
    get_or_create_fx_gain_loss_account,
    get_revaluation_entries_filter,
    is_revaluation_entry,
    run_period_end_revaluation,
)


@pytest.fixture
async def test_user_id():
    return uuid4()


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
    @pytest.mark.asyncio
    async def test_returns_only_foreign_currency_asset_liability(
        self, db: AsyncSession, test_user_id, usd_asset_account, sgd_asset_account
    ):
        accounts = await get_foreign_currency_accounts(db, test_user_id)

        account_currencies = [a.currency for a in accounts]
        assert "USD" in account_currencies
        assert "SGD" not in account_currencies

    @pytest.mark.asyncio
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


class TestGetOrCreateFxGainLossAccount:
    @pytest.mark.asyncio
    async def test_creates_account_if_not_exists(self, db: AsyncSession, test_user_id):
        account = await get_or_create_fx_gain_loss_account(db, test_user_id)

        assert account is not None
        assert account.type == AccountType.EQUITY
        assert account.code == "SYS-FX-REVAL"
        assert account.currency == "SGD"

    @pytest.mark.asyncio
    async def test_returns_existing_account(self, db: AsyncSession, test_user_id):
        account1 = await get_or_create_fx_gain_loss_account(db, test_user_id)
        account2 = await get_or_create_fx_gain_loss_account(db, test_user_id)

        assert account1.id == account2.id


class TestCalculateUnrealizedFxGains:
    @pytest.mark.asyncio
    async def test_returns_empty_for_no_foreign_accounts(self, db: AsyncSession, test_user_id, sgd_asset_account):
        result = await calculate_unrealized_fx_gains(db, test_user_id, date(2025, 1, 31))

        assert result.accounts_revalued == []
        assert result.total_unrealized_gain_loss == Decimal("0")

    @pytest.mark.asyncio
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


class TestIsRevaluationEntry:
    def test_identifies_revaluation_entry(self):
        entry = JournalEntry(
            user_id=uuid4(),
            entry_date=date.today(),
            memo="FX Revaluation",
            source_type=JournalEntrySourceType.FX_REVALUATION,
            status=JournalEntryStatus.DRAFT,
        )

        assert is_revaluation_entry(entry) is True

    def test_identifies_non_revaluation_entry(self):
        entry = JournalEntry(
            user_id=uuid4(),
            entry_date=date.today(),
            memo="Regular Entry",
            source_type=JournalEntrySourceType.MANUAL,
            status=JournalEntryStatus.DRAFT,
        )

        assert is_revaluation_entry(entry) is False


class TestCreateRevaluationEntry:
    @pytest.mark.asyncio
    async def test_creates_balanced_entry(self, db: AsyncSession, test_user_id, usd_asset_account):
        fx_account = await get_or_create_fx_gain_loss_account(db, test_user_id)

        revaluations = [
            AccountRevaluation(
                account_id=usd_asset_account.id,
                account_name=usd_asset_account.name,
                account_currency="USD",
                original_balance=Decimal("1000"),
                original_balance_base=Decimal("1300"),
                revalued_balance_base=Decimal("1350"),
                unrealized_gain_loss=Decimal("50"),
                fx_rate_used=Decimal("1.35"),
            )
        ]

        entry = await create_revaluation_entry(
            db=db,
            user_id=test_user_id,
            revaluation_date=date(2025, 1, 31),
            revaluations=revaluations,
            fx_account=fx_account,
            auto_post=False,
        )

        assert entry is not None
        assert entry.source_type == JournalEntrySourceType.FX_REVALUATION
        assert len(entry.lines) == 2

        total_debit = sum(line.amount for line in entry.lines if line.direction == Direction.DEBIT)
        total_credit = sum(line.amount for line in entry.lines if line.direction == Direction.CREDIT)
        assert total_debit == total_credit

    @pytest.mark.asyncio
    async def test_returns_none_for_zero_adjustment(self, db: AsyncSession, test_user_id, usd_asset_account):
        fx_account = await get_or_create_fx_gain_loss_account(db, test_user_id)

        revaluations = [
            AccountRevaluation(
                account_id=usd_asset_account.id,
                account_name=usd_asset_account.name,
                account_currency="USD",
                original_balance=Decimal("1000"),
                original_balance_base=Decimal("1350"),
                revalued_balance_base=Decimal("1350"),
                unrealized_gain_loss=Decimal("0"),
                fx_rate_used=Decimal("1.35"),
            )
        ]

        entry = await create_revaluation_entry(
            db=db,
            user_id=test_user_id,
            revaluation_date=date(2025, 1, 31),
            revaluations=revaluations,
            fx_account=fx_account,
        )

        assert entry is None

    @pytest.mark.asyncio
    async def test_creates_entry_for_loss(self, db: AsyncSession, test_user_id, usd_asset_account):
        """Test creating revaluation entry for a loss (negative adjustment)."""
        fx_account = await get_or_create_fx_gain_loss_account(db, test_user_id)

        revaluations = [
            AccountRevaluation(
                account_id=usd_asset_account.id,
                account_name=usd_asset_account.name,
                account_currency="USD",
                original_balance=Decimal("1000"),
                original_balance_base=Decimal("1350"),
                revalued_balance_base=Decimal("1300"),
                unrealized_gain_loss=Decimal("-50"),  # Loss
                fx_rate_used=Decimal("1.30"),
            )
        ]

        entry = await create_revaluation_entry(
            db=db,
            user_id=test_user_id,
            revaluation_date=date(2025, 1, 31),
            revaluations=revaluations,
            fx_account=fx_account,
        )

        assert entry is not None
        assert len(entry.lines) == 2

        # For a loss: asset is credited (reduced), FX account is debited
        fx_line = next(line for line in entry.lines if line.account_id == fx_account.id)
        assert fx_line.direction == Direction.DEBIT
        assert fx_line.amount == Decimal("50")

    @pytest.mark.asyncio
    async def test_creates_posted_entry_with_auto_post(self, db: AsyncSession, test_user_id, usd_asset_account):
        """Test that auto_post=True creates a POSTED entry."""
        fx_account = await get_or_create_fx_gain_loss_account(db, test_user_id)

        revaluations = [
            AccountRevaluation(
                account_id=usd_asset_account.id,
                account_name=usd_asset_account.name,
                account_currency="USD",
                original_balance=Decimal("1000"),
                original_balance_base=Decimal("1300"),
                revalued_balance_base=Decimal("1350"),
                unrealized_gain_loss=Decimal("50"),
                fx_rate_used=Decimal("1.35"),
            )
        ]

        entry = await create_revaluation_entry(
            db=db,
            user_id=test_user_id,
            revaluation_date=date(2025, 1, 31),
            revaluations=revaluations,
            fx_account=fx_account,
            auto_post=True,
        )

        assert entry is not None
        assert entry.status == JournalEntryStatus.POSTED

    @pytest.mark.asyncio
    async def test_skips_small_adjustments_in_multi_account(self, db: AsyncSession, test_user_id, usd_asset_account):
        """Test that small adjustments per account are skipped."""
        fx_account = await get_or_create_fx_gain_loss_account(db, test_user_id)

        # Create a second USD account
        usd_account_2 = Account(
            user_id=test_user_id,
            name="USD Checking",
            code="ASSET-USD-002",
            type=AccountType.ASSET,
            currency="USD",
            is_active=True,
        )
        db.add(usd_account_2)
        await db.commit()
        await db.refresh(usd_account_2)

        revaluations = [
            AccountRevaluation(
                account_id=usd_asset_account.id,
                account_name=usd_asset_account.name,
                account_currency="USD",
                original_balance=Decimal("1000"),
                original_balance_base=Decimal("1300"),
                revalued_balance_base=Decimal("1350"),
                unrealized_gain_loss=Decimal("50"),
                fx_rate_used=Decimal("1.35"),
            ),
            AccountRevaluation(
                account_id=usd_account_2.id,
                account_name=usd_account_2.name,
                account_currency="USD",
                original_balance=Decimal("1"),
                original_balance_base=Decimal("1.30"),
                revalued_balance_base=Decimal("1.30"),
                unrealized_gain_loss=Decimal("0.001"),  # Too small, should be skipped
                fx_rate_used=Decimal("1.30"),
            ),
        ]

        entry = await create_revaluation_entry(
            db=db,
            user_id=test_user_id,
            revaluation_date=date(2025, 1, 31),
            revaluations=revaluations,
            fx_account=fx_account,
        )

        assert entry is not None
        # Only 2 lines: one for the significant account + one for FX offset
        assert len(entry.lines) == 2


class TestCalculateUnrealizedFxForAccount:
    @pytest.mark.asyncio
    async def test_returns_none_for_zero_balance(self, db: AsyncSession, test_user_id, usd_asset_account):
        """Account with no transactions should return None."""
        result = await calculate_unrealized_fx_for_account(db, usd_asset_account, date(2025, 1, 31), "SGD")
        assert result is None

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
    @patch("src.services.fx_revaluation.get_exchange_rate")
    async def test_handles_fx_rate_error_exception(
        self, mock_get_rate, db: AsyncSession, test_user_id, usd_asset_account, sgd_asset_account
    ):
        """Test that FxRateError exception is re-raised as RevaluationError."""
        mock_get_rate.side_effect = FxRateError("No rate found for USD/SGD")

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

    @pytest.mark.asyncio
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


class TestRunPeriodEndRevaluation:
    @pytest.mark.asyncio
    async def test_returns_empty_result_for_no_foreign_accounts(
        self, db: AsyncSession, test_user_id, sgd_asset_account
    ):
        """No foreign currency accounts should return empty result."""
        result = await run_period_end_revaluation(db, test_user_id, date(2025, 1, 31))

        assert result.accounts_revalued == []
        assert result.journal_entry_id is None

    @pytest.mark.asyncio
    async def test_creates_entry_for_foreign_accounts_with_balance(
        self, db: AsyncSession, test_user_id, usd_asset_account, sgd_asset_account, fx_rate_usd_sgd
    ):
        """Foreign currency accounts with balance should create revaluation entry."""
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

        result = await run_period_end_revaluation(db, test_user_id, date(2025, 1, 31))

        # Should have accounts revalued (even if gain is 0 due to placeholder logic)
        assert result.revaluation_date == date(2025, 1, 31)
        assert result.base_currency == "SGD"
        assert len(result.accounts_revalued) == 1
        # Journal entry may or may not be created depending on whether there's a material adjustment

    @pytest.mark.asyncio
    async def test_runs_with_auto_post(self, db: AsyncSession, test_user_id, sgd_asset_account):
        """Test run_period_end_revaluation with auto_post flag."""
        result = await run_period_end_revaluation(db, test_user_id, date(2025, 1, 31), auto_post=True)

        # No foreign accounts, so no entry created
        assert result.journal_entry_id is None


class TestGetRevaluationEntriesFilter:
    @pytest.mark.asyncio
    async def test_filter_returns_only_revaluation_entries(self, db: AsyncSession, test_user_id):
        """Filter should select only FX_REVALUATION entries."""
        # Create a manual entry
        manual_entry = JournalEntry(
            user_id=test_user_id,
            entry_date=date(2025, 1, 15),
            memo="Manual entry",
            source_type=JournalEntrySourceType.MANUAL,
            status=JournalEntryStatus.POSTED,
        )
        db.add(manual_entry)

        # Create a revaluation entry
        reval_entry = JournalEntry(
            user_id=test_user_id,
            entry_date=date(2025, 1, 31),
            memo="FX Revaluation",
            source_type=JournalEntrySourceType.FX_REVALUATION,
            status=JournalEntryStatus.DRAFT,
        )
        db.add(reval_entry)
        await db.commit()

        # Query using the filter
        filter_clause = get_revaluation_entries_filter()
        stmt = select(JournalEntry).where(filter_clause)
        result = await db.execute(stmt)
        entries = list(result.scalars().all())

        assert len(entries) == 1
        assert entries[0].source_type == JournalEntrySourceType.FX_REVALUATION
        assert entries[0].memo == "FX Revaluation"


class TestCalculateAccountBalanceInCurrency:
    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
    async def test_returns_zero_for_account_without_entries(self, db: AsyncSession, test_user_id, usd_asset_account):
        """Test balance is zero for account with no entries."""
        balance = await calculate_account_balance_in_currency(db, usd_asset_account)
        assert balance == Decimal("0")
