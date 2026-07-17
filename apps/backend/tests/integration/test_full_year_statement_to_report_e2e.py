"""Full-year statement-to-report end-to-end acceptance (Usable milestone G2∩G3, #950).

Proves the *assembled* pipeline — CSV statement parse -> Stage-1 approval ->
auto-posted ledger entries -> period reports — ties out across MULTIPLE months,
not just a single manual-entry period (the gap left by
``test_reporting_e2e.py``, which posts manual entries for one month).

Deterministic by construction: CSV parsing is rule-based and the recorded
descriptions receive a fixed high-confidence category proposal. The production
classification and disposition path still performs category -> account ->
journal-entry resolution; there is no Uncategorized fallback in this proof.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.extraction import DocumentSource
from src.extraction.extension import transaction_classification
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_posting import auto_create_posted_entries_for_statement
from src.extraction.extension.statement_validation import approve_statement
from src.extraction.extension.transaction_classification import CategoryProposal, TransactionCategory
from src.ledger import Account, AccountType
from src.reporting import generate_balance_sheet, generate_cash_flow, generate_income_statement
from tests.statement_ingestion import parse_and_load_statement_projection, posting_dependencies

# A full year of distinct, non-overlapping monthly statement periods (the
# period-overlap posting guard requires distinct ranges per account).
MONTHS = (
    "2026-01",
    "2026-02",
    "2026-03",
    "2026-04",
    "2026-05",
    "2026-06",
    "2026-07",
    "2026-08",
    "2026-09",
    "2026-10",
    "2026-11",
    "2026-12",
)
SALARY = Decimal("5000.00")
RENT = Decimal("1500.00")


def _month_csv(year_month: str) -> bytes:
    """One inflow (salary -> Credit) and one outflow (rent -> Debit) for the month.

    Uses the DBS column layout the rule-based CSV parser recognises (separate
    Debit/Credit columns), so no AI CSV-mapping fallback is triggered.
    """
    return (
        f"Date,Description,Debit Amount,Credit Amount\n{year_month}-05,Salary,,{SALARY}\n{year_month}-20,Rent,{RENT},\n"
    ).encode()


async def _ingest_month(
    db: AsyncSession,
    user_id: UUID,
    bank: Account,
    csv_bytes: bytes,
    filename: str,
    *,
    opening: Decimal,
    closing: Decimal,
) -> int:
    """Parse a CSV statement, map it to the bank account, approve, and auto-post.

    Opening/closing balances are set to a realistic running chain so the
    statement balance-chain guard (opening + movements == closing, and opening ==
    prior statement's closing) passes.
    """
    service = ExtractionService()
    _result, statement, transactions = await parse_and_load_statement_projection(
        service,
        db=db,
        source=DocumentSource.resolve(path=Path(filename), content=csv_bytes),
        institution="DBS",
        user_id=user_id,
        file_type="csv",
    )
    # A transaction-only CSV cannot prove its account currency or boundary
    # balances. This test exercises the reviewed-record continuation: the user
    # confirms those source facts before approval; extraction itself retains the
    # missing-fact warning in its immutable result.
    statement.account_id = bank.id
    statement.currency = bank.currency
    statement.period_start = min(transaction.txn_date for transaction in transactions)
    statement.period_end = max(transaction.txn_date for transaction in transactions)
    statement.opening_balance = opening
    statement.closing_balance = closing
    for transaction in transactions:
        transaction.currency = bank.currency
        transaction.currency_unresolved = False
        transaction.currency_resolved_by = user_id
        transaction.currency_resolved_at = datetime.now(UTC)
    await db.flush()
    approved = await approve_statement(db, statement.id, user_id)
    return await auto_create_posted_entries_for_statement(db, approved, user_id, dependencies=posting_dependencies())


async def test_AC8_15_1_full_year_statement_to_report_ties_out(
    db: AsyncSession,
    test_user,
    monkeypatch,
) -> None:
    """AC-reporting.full-year.1: EPIC-003 EPIC-008 EPIC-019 / AC8.15.1: A multi-month run of real CSV
    statements parses, approves under the balance-chain guard, auto-posts to the
    ledger, and the assembled period reports tie out end-to-end (income,
    expenses, net income, ending cash, total assets, and the accounting
    equation)."""
    user_id = test_user.id
    monkeypatch.setattr(settings, "enable_ai_classification", True)

    async def deterministic_proposer(transactions, _policy):
        categories = {
            "Salary": TransactionCategory.SALARY,
            "Rent": TransactionCategory.HOUSING,
        }
        return [
            CategoryProposal(category=categories[transaction.description].value, confidence=99, reason="fixture")
            for transaction in transactions
        ]

    monkeypatch.setattr(transaction_classification, "propose_categories", deterministic_proposer)

    bank = Account(
        user_id=user_id,
        name="DBS Cash",
        code="1001",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(bank)
    await db.flush()

    total_created = 0
    running = Decimal("0.00")
    net_per_month = SALARY - RENT
    for year_month in MONTHS:
        opening = running
        closing = running + net_per_month
        total_created += await _ingest_month(
            db,
            user_id,
            bank,
            _month_csv(year_month),
            f"{year_month}.csv",
            opening=opening,
            closing=closing,
        )
        running = closing
    await db.commit()

    # 2 transactions per month, all posted to the ledger.
    assert total_created == 2 * len(MONTHS)

    period_start = date(2026, 1, 1)
    period_end = date(2026, 12, 31)
    balance_sheet = await generate_balance_sheet(db, user_id, as_of_date=period_end, currency="SGD")
    income_statement = await generate_income_statement(
        db, user_id, start_date=period_start, end_date=period_end, currency="SGD"
    )
    cash_flow = await generate_cash_flow(db, user_id, start_date=period_start, end_date=period_end, currency="SGD")

    expected_income = SALARY * len(MONTHS)  # 60000.00 (12 x 5000)
    expected_expenses = RENT * len(MONTHS)  # 18000.00 (12 x 1500)
    expected_net = expected_income - expected_expenses  # 42000.00

    assert income_statement["total_income"] == expected_income
    assert income_statement["total_expenses"] == expected_expenses
    assert income_statement["net_income"] == expected_net

    assert cash_flow["summary"]["ending_cash"] == expected_net
    assert balance_sheet["total_assets"] == expected_net
    assert balance_sheet["is_balanced"] is True
    assert balance_sheet["equation_delta"] == Decimal("0.00")
