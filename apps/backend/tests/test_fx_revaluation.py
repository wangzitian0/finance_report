"""Tests for FX Revaluation Service infrastructure."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
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
from src.services.fx_revaluation import (
    AccountRevaluation,
    calculate_unrealized_fx_gains,
    create_revaluation_entry,
    get_foreign_currency_accounts,
    get_or_create_fx_gain_loss_account,
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

        total_debit = sum(l.amount for l in entry.lines if l.direction == Direction.DEBIT)
        total_credit = sum(l.amount for l in entry.lines if l.direction == Direction.CREDIT)
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
