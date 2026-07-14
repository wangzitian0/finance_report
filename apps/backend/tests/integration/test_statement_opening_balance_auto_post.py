"""AC-extraction.1833.1/.2: auto-approve posts the chain-validated opening balance (#1833).

Staging real-statement QA (2026-07-14) showed the happy path producing a wrong
headline: a high-confidence, balance-validated statement auto-approves and posts
its period transactions, but the opening balance the chain validation just
proved is never posted — so the account "balance" on the balance sheet is the
period net flow (negative for a draw-down month), not the closing balance.

These tests drive the same parse -> auto-approve -> post path as
``test_bank_statement_auto_account_post.py`` and assert the ledger ends at the
statement's closing balance, not its net flow.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

from sqlalchemy import select

from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_posting import (
    try_auto_approve_high_confidence_statement,
    try_auto_post_statement_opening_balance,
)
from src.extraction.orm.statement_enums import BankStatementStatus
from src.ledger import Account, JournalEntry, JournalEntryStatus, JournalLine


def _drawdown_statement_payload() -> dict:
    """A validated statement whose net flow is negative (the QA failure shape)."""
    return {
        "institution": "GXS",
        "account_last4": "7174",
        "currency": "SGD",
        "period_start": "2026-06-01",
        "period_end": "2026-06-30",
        "opening_balance": "51730.82",
        "closing_balance": "2953.14",
        "transactions": [
            {
                "date": "2026-06-05",
                "description": "Transfer out",
                "amount": "48800.00",
                "direction": "OUT",
                "currency": "SGD",
                "balance_after": "2930.82",
            },
            {
                "date": "2026-06-30",
                "description": "Interest",
                "amount": "22.32",
                "direction": "IN",
                "currency": "SGD",
                "balance_after": "2953.14",
            },
        ],
    }


def _followup_month_payload() -> dict:
    return {
        "institution": "GXS",
        "account_last4": "7174",
        "currency": "SGD",
        "period_start": "2026-07-01",
        "period_end": "2026-07-31",
        "opening_balance": "2953.14",
        "closing_balance": "3053.14",
        "transactions": [
            {
                "date": "2026-07-15",
                "description": "Deposit",
                "amount": "100.00",
                "direction": "IN",
                "currency": "SGD",
                "balance_after": "3053.14",
            },
        ],
    }


async def _parse_and_auto_post(db, test_user, payload: dict, file_hash: str):
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(return_value=payload)
    statement, _txns = await service.parse_document(
        file_path=Path(f"{file_hash}.pdf"),
        institution=payload["institution"],
        user_id=test_user.id,
        file_content=b"%PDF-1.7",
        file_hash=file_hash,
        db=db,
    )
    await db.flush()
    assert statement.status == BankStatementStatus.APPROVED
    posted = await try_auto_approve_high_confidence_statement(db, statement.id, test_user.id)
    assert posted >= 1
    return statement


async def _account_ledger_balance(db, account_id) -> Decimal:
    lines = (
        (
            await db.execute(
                select(JournalLine)
                .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
                .where(JournalLine.account_id == account_id)
                .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
            )
        )
        .scalars()
        .all()
    )
    balance = Decimal("0")
    for line in lines:
        if line.direction.value == "DEBIT":
            balance += line.amount
        else:
            balance -= line.amount
    return balance


async def _opening_equity_line_count(db, user_id) -> int:
    equity = (
        await db.execute(
            select(Account).where(
                Account.user_id == user_id,
                Account.is_system.is_(True),
                Account.code == "3199",
            )
        )
    ).scalar_one_or_none()
    if equity is None:
        return 0
    lines = (await db.execute(select(JournalLine).where(JournalLine.account_id == equity.id))).scalars().all()
    return len(lines)


async def test_AC_extraction_1833_1_auto_approve_posts_validated_opening_balance(db, test_user):
    """AC-extraction.1833.1: after auto-approve, the asset account's ledger
    balance equals the statement's closing balance (opening balance posted
    against the system Opening Balance Equity account), not the period net flow."""
    statement = await _parse_and_auto_post(db, test_user, _drawdown_statement_payload(), "ac-1833-1")

    assert statement.account_id is not None
    balance = await _account_ledger_balance(db, statement.account_id)
    assert balance == Decimal("2953.14"), (
        f"asset ledger balance is {balance} — the period net flow — instead of the "
        "statement closing balance; the validated opening balance was not posted"
    )
    assert await _opening_equity_line_count(db, test_user.id) == 1


async def test_AC_extraction_1833_2_second_import_does_not_duplicate_opening_balance(db, test_user):
    """AC-extraction.1833.2: a follow-up month import for the same account posts
    its transactions but never a second opening-balance entry (the account
    already has prior posted activity)."""
    first = await _parse_and_auto_post(db, test_user, _drawdown_statement_payload(), "ac-1833-2a")
    second = await _parse_and_auto_post(db, test_user, _followup_month_payload(), "ac-1833-2b")

    assert second.account_id == first.account_id
    assert await _opening_equity_line_count(db, test_user.id) == 1

    balance = await _account_ledger_balance(db, first.account_id)
    assert balance == Decimal("3053.14")


async def test_AC_extraction_1833_1_zero_or_absent_opening_balance_posts_no_opening_entry(db, test_user):
    """A statement with no starting position still auto-posts its transactions
    and creates no opening-balance entry (nothing to establish)."""
    payload = _drawdown_statement_payload()
    payload["opening_balance"] = "0.00"
    payload["closing_balance"] = "-48777.68"
    # keep the chain internally consistent so validation still passes
    payload["transactions"][0]["balance_after"] = "-48800.00"
    payload["transactions"][1]["balance_after"] = "-48777.68"

    statement = await _parse_and_auto_post(db, test_user, payload, "ac-1833-3")

    assert await _opening_equity_line_count(db, test_user.id) == 0
    balance = await _account_ledger_balance(db, statement.account_id)
    assert balance == Decimal("-48777.68")


async def test_AC_extraction_1833_3_zero_created_count_still_posts_opening_balance(db, test_user, monkeypatch):
    """AC-extraction.1833.3 (PR #1842 review): created_count == 0 must not block
    the opening-balance post.

    created_count reaching 0 for a HIGH-CONFIDENCE, balance-validated statement is
    realistic — e.g. every transaction in the period turns out to be an internal
    transfer excluded via the reconciliation transfer-exclusions provider, or the
    statement is re-processed after its transactions were already posted. (A
    literally-empty extracted payload, by contrast, cannot reach this path: the
    confidence-scoring formula's txn-count/balance-progression components need
    >=1 transaction, so a genuinely empty statement scores below the 85
    auto-approve threshold and never reaches this function — verified empirically
    while writing this test.) This test isolates the orchestration contract
    directly: given created_count == 0 for any reason, the opening balance must
    still be posted.
    """
    from src.extraction.extension import statement_posting as statement_posting_module

    service = ExtractionService()
    service.extract_financial_data = AsyncMock(return_value=_drawdown_statement_payload())
    statement, _txns = await service.parse_document(
        file_path=Path("ac-1833-4.pdf"),
        institution="GXS",
        user_id=test_user.id,
        file_content=b"%PDF-1.7",
        file_hash="ac-1833-4",
        db=db,
    )
    await db.flush()
    assert statement.status == BankStatementStatus.APPROVED

    # Force created_count == 0 as if every transaction were excluded (internal
    # transfer match, or already posted by a prior call) — the scenario the
    # created_count gate could not distinguish from "genuinely nothing to post".
    monkeypatch.setattr(statement_posting_module, "auto_create_posted_entries_for_statement", AsyncMock(return_value=0))

    posted = await try_auto_approve_high_confidence_statement(db, statement.id, test_user.id)
    assert posted == 0

    assert await _opening_equity_line_count(db, test_user.id) == 1
    balance = await _account_ledger_balance(db, statement.account_id)
    assert balance == Decimal("51730.82")  # opening balance posted; no transactions posted


async def test_same_period_start_second_import_does_not_duplicate_opening_balance(db, test_user):
    """Hardening beyond PR #1842's review: two statements sharing the exact same
    period_start (so post_opening_balance_entry's date-ordering guard alone would
    not catch a re-attempt) must still only post the opening balance once —
    enforced by the per-account _account_has_opening_balance_entry check."""
    first = await _parse_and_auto_post(db, test_user, _drawdown_statement_payload(), "ac-1833-5a")

    # Same account (same institution/last4/currency), same period_start as `first`.
    duplicate_period_payload = _drawdown_statement_payload()
    duplicate_period_payload["opening_balance"] = "51730.82"
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(return_value=duplicate_period_payload)
    statement, _txns = await service.parse_document(
        file_path=Path("ac-1833-5b.pdf"),
        institution="GXS",
        user_id=test_user.id,
        file_content=b"%PDF-1.7",
        file_hash="ac-1833-5b",
        account_id=first.account_id,
        db=db,
    )
    await db.flush()

    await try_auto_post_statement_opening_balance(db, statement, test_user.id)

    assert await _opening_equity_line_count(db, test_user.id) == 1
