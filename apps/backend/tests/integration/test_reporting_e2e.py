"""Reporting backend journey integration tests."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from common.testing.ac_proof import ac_proof
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import create_journal_entry, post_journal_entry
from src.models.account import Account, AccountType
from src.pricing.orm.market_data import FxRate
from src.reporting import generate_balance_sheet, generate_cash_flow, generate_income_statement


async def _account(
    db: AsyncSession,
    user_id: UUID,
    *,
    name: str,
    code: str,
    account_type: AccountType,
    currency: str = "SGD",
) -> Account:
    account = Account(
        user_id=user_id,
        name=name,
        code=code,
        type=account_type,
        currency=currency,
    )
    db.add(account)
    await db.flush()
    await db.refresh(account)
    return account


async def _posted_entry(
    db: AsyncSession,
    user_id: UUID,
    *,
    entry_date: date,
    memo: str,
    lines: list[dict[str, object]],
) -> None:
    entry = await create_journal_entry(
        db=db,
        user_id=user_id,
        entry_date=entry_date,
        memo=memo,
        lines_data=lines,
    )
    await post_journal_entry(db, entry.id, user_id)


@ac_proof(
    "structured-source-reporting-pr",
    ac_ids=["AC-reporting.integration.1", "AC-testing.trust-mirrors.4"],
    scope="behavioral",
    ci_tier="pr_ci",
    trust_mode="deterministic_pr",
    source_classes=["bank_statement", "csv_export", "manual_record"],
    issue="#696",
)
async def test_AC5_15_1_multicurrency_reporting_cycle_reconciles_bs_is_cf(
    db: AsyncSession,
    test_user,
) -> None:
    """AC-reporting.integration.1 AC-testing.trust-mirrors.4: AC5.15.1 AC8.14.4: Structured/manual facts deterministically generate BS, IS, and CF reports."""
    user_id = test_user.id
    period_start = date(2026, 1, 1)
    period_end = date(2026, 1, 31)

    cash = await _account(db, user_id, name="Cash SGD", code="1001", account_type=AccountType.ASSET)
    receivable_usd = await _account(
        db,
        user_id,
        name="Broker Cash USD",
        code="1010",
        account_type=AccountType.ASSET,
        currency="USD",
    )
    salary = await _account(db, user_id, name="Salary", code="4001", account_type=AccountType.INCOME)
    expense = await _account(db, user_id, name="Groceries", code="5001", account_type=AccountType.EXPENSE)
    equity = await _account(db, user_id, name="Opening Equity", code="3001", account_type=AccountType.EQUITY)

    db.add_all(
        [
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.350000"),
                rate_date=date(2026, 1, 10),
                source="test",
            ),
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.350000"),
                rate_date=period_end,
                source="test",
            ),
        ]
    )

    await _posted_entry(
        db,
        user_id,
        entry_date=period_start,
        memo="Opening capital",
        lines=[
            {"account_id": cash.id, "direction": "DEBIT", "amount": Decimal("5000.00"), "currency": "SGD"},
            {"account_id": equity.id, "direction": "CREDIT", "amount": Decimal("5000.00"), "currency": "SGD"},
        ],
    )
    await _posted_entry(
        db,
        user_id,
        entry_date=date(2026, 1, 5),
        memo="Salary deposit",
        lines=[
            {"account_id": cash.id, "direction": "DEBIT", "amount": Decimal("3000.00"), "currency": "SGD"},
            {"account_id": salary.id, "direction": "CREDIT", "amount": Decimal("3000.00"), "currency": "SGD"},
        ],
    )
    await _posted_entry(
        db,
        user_id,
        entry_date=date(2026, 1, 8),
        memo="Groceries",
        lines=[
            {"account_id": expense.id, "direction": "DEBIT", "amount": Decimal("200.00"), "currency": "SGD"},
            {"account_id": cash.id, "direction": "CREDIT", "amount": Decimal("200.00"), "currency": "SGD"},
        ],
    )
    await _posted_entry(
        db,
        user_id,
        entry_date=date(2026, 1, 10),
        memo="USD dividend",
        lines=[
            {
                "account_id": receivable_usd.id,
                "direction": "DEBIT",
                "amount": Decimal("100.00"),
                "currency": "USD",
                "fx_rate": Decimal("1.350000"),
            },
            {"account_id": salary.id, "direction": "CREDIT", "amount": Decimal("135.00"), "currency": "SGD"},
        ],
    )
    await db.commit()

    balance_sheet = await generate_balance_sheet(db, user_id, as_of_date=period_end, currency="SGD")
    income_statement = await generate_income_statement(
        db,
        user_id,
        start_date=period_start,
        end_date=period_end,
        currency="SGD",
    )
    cash_flow = await generate_cash_flow(
        db,
        user_id,
        start_date=period_start,
        end_date=period_end,
        currency="SGD",
    )

    assert balance_sheet["is_balanced"] is True
    assert balance_sheet["equation_delta"] == Decimal("0.00")
    assert balance_sheet["total_assets"] == Decimal("7935.00")
    assert balance_sheet["total_equity"] == Decimal("5000.00")

    assert income_statement["total_income"] == Decimal("3135.00")
    assert income_statement["total_expenses"] == Decimal("200.00")
    assert income_statement["net_income"] == Decimal("2935.00")

    assert cash_flow["summary"]["beginning_cash"] == Decimal("0.00")
    assert cash_flow["summary"]["ending_cash"] == Decimal("7935.00")
    assert cash_flow["summary"]["net_cash_flow"] == Decimal("7935.00")
