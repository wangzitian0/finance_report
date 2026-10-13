"""AC-extraction.disposition-transfer-fact.4: AI classification cannot post a matched transfer leg again (#2410).

On staging, the model gave a transfer leg an income or expense category with a confidence of 85 or more.
Reconciliation had already accepted the leg as a transfer and had posted its Processing entry.
Statement posting then posted a second entry from the category, and the same money counted twice.
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

TRANSFER_DESCRIPTION = "Own account transfer"
GROCERY_DESCRIPTION = "Grocery market"
CSV = (
    "Date,Description,Debit Amount,Credit Amount\n"
    f"2026-06-01,{TRANSFER_DESCRIPTION},500.00,\n"
    f"2026-06-02,{GROCERY_DESCRIPTION},100.00,\n"
).encode()


@pytest.mark.asyncio
async def test_AC_extraction_disposition_transfer_fact_4_applied_model_category_does_not_repost_a_matched_leg(
    db, test_user, monkeypatch
) -> None:
    """AC-extraction.disposition-transfer-fact.4: the model's expense category yields to an accepted transfer match."""
    monkeypatch.setattr(settings, "enable_ai_classification", True)
    proposals = {
        TRANSFER_DESCRIPTION: CategoryProposal(category="OTHER_EXPENSE", confidence=95),
        GROCERY_DESCRIPTION: CategoryProposal(category="GROCERIES", confidence=95),
    }

    async def model_proposals(transactions, _policy):
        return [proposals[transaction.description] for transaction in transactions]

    monkeypatch.setattr(transaction_classification, "propose_categories", model_proposals)

    bank = Account(user_id=test_user.id, name="DBS Cash", code="1001", type=AccountType.ASSET, currency="SGD")
    db.add(bank)
    await db.flush()
    _result, statement, transactions = await parse_and_load_statement_projection(
        ExtractionService(),
        db=db,
        source=DocumentSource.resolve(path=Path("transfer-conflict.csv"), content=CSV),
        institution="DBS",
        user_id=test_user.id,
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
        transaction.currency_resolved_by = test_user.id
        transaction.currency_resolved_at = datetime.now(UTC)
    await db.flush()
    transfer_ids = {transaction.id for transaction in transactions if transaction.description == TRANSFER_DESCRIPTION}
    assert len(transfer_ids) == 1

    async def accepted_transfer_ids(_db, _transaction_ids):
        return transfer_ids

    approved = await approve_statement(db, statement.id, test_user.id)
    outcome = await auto_create_posted_entries_for_statement(
        db,
        approved,
        test_user.id,
        dependencies=replace(posting_dependencies(), transfer_exclusions=accepted_transfer_ids),
    )

    # The model did classify the transfer leg and the classification is applied. A guard that
    # never saw a competing category would prove nothing.
    transfer_classification = (
        await db.execute(
            select(TransactionClassification).where(TransactionClassification.atomic_txn_id.in_(transfer_ids))
        )
    ).scalar_one()
    assert transfer_classification.status is ClassificationStatus.APPLIED
    assert (transfer_classification.tags or {}).get("category") == "OTHER_EXPENSE"

    assert outcome.status is StatementPostingStatus.POSTED
    assert outcome.created_count == 1, "only the grocery row posts; the transfer leg has its own Processing entry"
    posted_source_ids = set((await db.execute(select(JournalEntry.source_id))).scalars())
    assert posted_source_ids.isdisjoint(transfer_ids)

    report = await generate_income_statement(
        db, test_user.id, start_date=date(2026, 6, 1), end_date=date(2026, 6, 30), currency="SGD"
    )
    assert {line["name"]: line["amount"] for line in report["expenses"]} == {"Expense - Groceries": Decimal("100.00")}
    assert report["total_expenses"] == Decimal("100.00")
