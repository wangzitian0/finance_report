"""AC-extraction.non-pnl-categories.5: a row that the model names as a transfer never posts as profit or loss (#2411).

Before policy v2, the closed category list had no class for a transfer. The model had to file an
own-account transfer under an income or expense category, and a confidence of 85 or more posted it.
Now the model can say TRANSFER. A transfer without an accepted match waits for review. A matched
transfer stays covered by its Processing entry.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from src.config import settings
from src.extraction import ClassificationStatus, DocumentSource, StatementPostingStatus
from src.extraction.extension import transaction_classification
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_posting import auto_create_posted_entries_for_statement
from src.extraction.extension.statement_validation import approve_statement
from src.extraction.extension.transaction_classification import CategoryProposal
from src.extraction.orm.layer3 import TransactionClassification
from src.ledger import Account, AccountType, JournalEntry
from src.reporting import generate_income_statement
from tests.statement_ingestion import parse_and_load_statement_projection, posting_dependencies

TRANSFER_DESCRIPTION = "Move to savings"
GROCERY_DESCRIPTION = "Grocery market"
CSV = (
    "Date,Description,Debit Amount,Credit Amount\n"
    f"2026-06-01,{TRANSFER_DESCRIPTION},500.00,\n"
    f"2026-06-02,{GROCERY_DESCRIPTION},100.00,\n"
).encode()


async def _load_statement(db, user_id, monkeypatch):
    monkeypatch.setattr(settings, "enable_ai_classification", True)
    proposals = {
        TRANSFER_DESCRIPTION: CategoryProposal(category="TRANSFER", confidence=95),
        GROCERY_DESCRIPTION: CategoryProposal(category="GROCERIES", confidence=95),
    }

    async def model_proposals(transactions, _policy):
        return [proposals[transaction.description] for transaction in transactions]

    monkeypatch.setattr(transaction_classification, "propose_categories", model_proposals)
    bank = Account(user_id=user_id, name="DBS Cash", code="1001", type=AccountType.ASSET, currency="SGD")
    db.add(bank)
    await db.flush()
    _result, statement, transactions = await parse_and_load_statement_projection(
        ExtractionService(),
        db=db,
        source=DocumentSource.resolve(path=Path("non-pnl.csv"), content=CSV),
        institution="DBS",
        user_id=user_id,
        file_type="csv",
    )
    statement.account_id = bank.id
    statement.currency = bank.currency
    statement.period_start = date(2026, 6, 1)
    statement.period_end = date(2026, 6, 30)
    statement.opening_balance = Decimal("1000.00")
    statement.closing_balance = Decimal("400.00")
    for transaction in transactions:
        transaction.currency = bank.currency
        transaction.currency_unresolved = False
        transaction.currency_resolved_by = user_id
        transaction.currency_resolved_at = datetime.now(UTC)
    await db.flush()
    return statement, {t.id for t in transactions if t.description == TRANSFER_DESCRIPTION}


@pytest.mark.asyncio
async def test_AC_extraction_non_pnl_categories_5_unmatched_transfer_waits_for_review(
    db, test_user, monkeypatch
) -> None:
    """AC-extraction.non-pnl-categories.5: an unmatched TRANSFER row is not posted as profit or loss."""
    statement, transfer_ids = await _load_statement(db, test_user.id, monkeypatch)

    async def no_accepted_transfers(_db, _transaction_ids):
        return set()

    approved = await approve_statement(db, statement.id, test_user.id)
    outcome = await auto_create_posted_entries_for_statement(
        db,
        approved,
        test_user.id,
        dependencies=replace(posting_dependencies(), transfer_exclusions=no_accepted_transfers),
    )

    assert outcome.status is StatementPostingStatus.REVIEW_REQUIRED
    assert outcome.review_reasons == ("intent_missing",)
    assert outcome.created_count == 0
    assert list((await db.execute(select(JournalEntry.id))).scalars()) == []
    # The TRANSFER row has a draft row without an account: posting ignores it. No "Other" account exists.
    transfer_rows = list(
        (
            await db.execute(
                select(TransactionClassification).where(TransactionClassification.atomic_txn_id.in_(transfer_ids))
            )
        ).scalars()
    )
    assert [(row.status, row.account_id) for row in transfer_rows] == [(ClassificationStatus.DRAFT, None)]
    names = set((await db.execute(select(Account.name).where(Account.user_id == test_user.id))).scalars())
    assert "Expense - Other" not in names and "Income - Other" not in names


@pytest.mark.asyncio
async def test_AC_extraction_non_pnl_categories_5_matched_transfer_stays_covered(db, test_user, monkeypatch) -> None:
    """AC-extraction.non-pnl-categories.5: a matched TRANSFER row posts nothing; the ordinary row posts."""
    statement, transfer_ids = await _load_statement(db, test_user.id, monkeypatch)

    async def accepted_transfer_ids(_db, _transaction_ids):
        return transfer_ids

    approved = await approve_statement(db, statement.id, test_user.id)
    outcome = await auto_create_posted_entries_for_statement(
        db,
        approved,
        test_user.id,
        dependencies=replace(posting_dependencies(), transfer_exclusions=accepted_transfer_ids),
    )

    assert outcome.status is StatementPostingStatus.POSTED
    assert outcome.created_count == 1
    posted_source_ids = set((await db.execute(select(JournalEntry.source_id))).scalars())
    assert posted_source_ids.isdisjoint(transfer_ids)
    report = await generate_income_statement(
        db, test_user.id, start_date=date(2026, 6, 1), end_date=date(2026, 6, 30), currency="SGD"
    )
    assert {line["name"]: line["amount"] for line in report["expenses"]} == {"Expense - Groceries": Decimal("100.00")}
