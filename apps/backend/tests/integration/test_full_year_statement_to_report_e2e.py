from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration
from src.config import settings
from src.extraction import DocumentSource
from src.extraction.extension import transaction_classification
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_posting import auto_create_posted_entries_for_statement
from src.extraction.extension.statement_validation import approve_statement_with_transactions
from src.extraction.extension.transaction_classification import CategoryProposal, TransactionCategory
from src.ledger import Account, AccountType
from src.reporting import generate_balance_sheet, generate_cash_flow, generate_income_statement
from tests.statement_ingestion import classify_rows, parse_and_load_statement_projection, posting_dependencies

MONTHS = tuple(f"2026-{m:02d}" for m in range(1, 13))
SALARY, RENT = Decimal("5000.00"), Decimal("1500.00")


async def _ingest_month(
    db: AsyncSession, user_id, bank: Account, ym: str, *, opening: Decimal, closing: Decimal
) -> int:
    csv_bytes = (
        f"Date,Description,Debit Amount,Credit Amount\n{ym}-05,Salary,,{SALARY}\n{ym}-20,Rent,{RENT},\n".encode()
    )
    _, stmt, txns = await parse_and_load_statement_projection(
        ExtractionService(),
        db=db,
        source=DocumentSource.resolve(path=Path(f"{ym}.csv"), content=csv_bytes),
        institution="DBS",
        user_id=user_id,
        file_type="csv",
    )
    stmt.account_id, stmt.currency, stmt.period_start, stmt.period_end, stmt.opening_balance, stmt.closing_balance = (
        bank.id,
        bank.currency,
        min(t.txn_date for t in txns),
        max(t.txn_date for t in txns),
        opening,
        closing,
    )
    for t in txns:
        t.currency, t.currency_unresolved, t.currency_resolved_by, t.currency_resolved_at = (
            bank.currency,
            False,
            user_id,
            datetime.now(UTC),
        )
    await db.flush()
    await classify_rows(db, user_id, txns)
    approved, approved_txns = await approve_statement_with_transactions(db, stmt.id, user_id)
    outcome = await auto_create_posted_entries_for_statement(
        db, approved, user_id, dependencies=posting_dependencies(), transactions=approved_txns
    )
    assert outcome.review_reasons == ()
    return outcome.created_count


async def test_full_year_statement_to_report_ties_out(db: AsyncSession, test_user, monkeypatch) -> None:
    user_id = test_user.id
    monkeypatch.setattr(settings, "enable_ai_classification", True)
    cats = {"Salary": TransactionCategory.SALARY, "Rent": TransactionCategory.HOUSING}

    async def proposer(txns, _p):
        return [CategoryProposal(category=cats[t.description].value, confidence=99, reason="fixture") for t in txns]

    monkeypatch.setattr(transaction_classification, "propose_categories", proposer)
    bank = Account(user_id=user_id, name="DBS Cash", code="1001", type=AccountType.ASSET, currency="SGD")
    db.add(bank)
    await db.flush()
    total_created, running, net_per_month = 0, Decimal("0.00"), SALARY - RENT
    for ym in MONTHS:
        total_created += await _ingest_month(db, user_id, bank, ym, opening=running, closing=running + net_per_month)
        running += net_per_month
    await db.commit()

    p_start, p_end = date(2026, 1, 1), date(2026, 12, 31)
    bs = await generate_balance_sheet(db, user_id, as_of_date=p_end, currency="SGD")
    inc = await generate_income_statement(db, user_id, start_date=p_start, end_date=p_end, currency="SGD")
    cf = await generate_cash_flow(db, user_id, start_date=p_start, end_date=p_end, currency="SGD")
    exp_inc, exp_exp = SALARY * len(MONTHS), RENT * len(MONTHS)
    exp_net = exp_inc - exp_exp
    assert (
        total_created,
        inc["total_income"],
        inc["total_expenses"],
        inc["net_income"],
        cf["summary"]["ending_cash"],
        bs["total_assets"],
        bs["is_balanced"],
        bs["equation_delta"],
    ) == (2 * len(MONTHS), exp_inc, exp_exp, exp_net, exp_net, exp_net, True, Decimal("0.00"))
