from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.integration
from src.config import settings
from src.extraction import ClassificationStatus, DocumentSource, StatementPostingStatus
from src.extraction.extension import transaction_classification
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_posting import auto_create_posted_entries_for_statement
from src.extraction.extension.statement_validation import approve_statement_with_transactions
from src.extraction.extension.transaction_classification import CategoryProposal
from src.extraction.orm.layer3 import TransactionClassification
from src.ledger import Account, AccountType, JournalEntry
from src.reporting import generate_income_statement
from tests.statement_ingestion import classify_rows, parse_and_load_statement_projection, posting_dependencies

TRANSFER_DESCRIPTION, GROCERY_DESCRIPTION = "Own account transfer", "Grocery market"
CSV = f"Date,Description,Debit Amount,Credit Amount\n2026-06-01,{TRANSFER_DESCRIPTION},500.00,\n2026-06-02,{GROCERY_DESCRIPTION},100.00,\n".encode()


async def test_applied_model_category_does_not_repost_a_matched_leg(db, test_user, monkeypatch) -> None:
    monkeypatch.setattr(settings, "enable_ai_classification", True)
    proposals = {TRANSFER_DESCRIPTION: CategoryProposal(category="DINING", confidence=95), GROCERY_DESCRIPTION: CategoryProposal(category="GROCERIES", confidence=95)}

    async def model_proposals(txns, _policy):
        return [proposals[t.description] for t in txns]

    monkeypatch.setattr(transaction_classification, "propose_categories", model_proposals)
    bank = Account(user_id=test_user.id, name="DBS Cash", code="1001", type=AccountType.ASSET, currency="SGD")
    db.add(bank)
    await db.flush()
    _, stmt, txns = await parse_and_load_statement_projection(
        ExtractionService(), db=db, source=DocumentSource.resolve(path=Path("transfer-conflict.csv"), content=CSV), institution="DBS", user_id=test_user.id, file_type="csv"
    )
    stmt.account_id, stmt.currency, stmt.period_start, stmt.period_end, stmt.opening_balance, stmt.closing_balance = bank.id, bank.currency, date(2026, 6, 1), date(2026, 6, 30), Decimal("1000.00"), Decimal("400.00")
    for t in txns:
        t.currency, t.currency_unresolved, t.currency_resolved_by, t.currency_resolved_at = bank.currency, False, test_user.id, datetime.now(UTC)
    await db.flush()
    transfer_ids = {t.id for t in txns if t.description == TRANSFER_DESCRIPTION}
    assert len(transfer_ids) == 1

    async def accepted_transfer_ids(_db, _ids):
        return transfer_ids

    await classify_rows(db, test_user.id, txns)
    approved, approved_txns = await approve_statement_with_transactions(db, stmt.id, test_user.id)
    outcome = await auto_create_posted_entries_for_statement(db, approved, test_user.id, dependencies=replace(posting_dependencies(), transfer_exclusions=accepted_transfer_ids), transactions=approved_txns)
    tc = (await db.execute(select(TransactionClassification).where(TransactionClassification.atomic_txn_id.in_(transfer_ids)))).scalar_one()
    assert (tc.status, (tc.tags or {}).get("category"), outcome.status, outcome.created_count) == (ClassificationStatus.APPLIED, "DINING", StatementPostingStatus.POSTED, 1)
    assert set((await db.execute(select(JournalEntry.source_id))).scalars()).isdisjoint(transfer_ids)
    report = await generate_income_statement(db, test_user.id, start_date=date(2026, 6, 1), end_date=date(2026, 6, 30), currency="SGD")
    assert ({line["name"]: line["amount"] for line in report["expenses"]}, report["total_expenses"]) == ({"Expense - Groceries": Decimal("100.00")}, Decimal("100.00"))
