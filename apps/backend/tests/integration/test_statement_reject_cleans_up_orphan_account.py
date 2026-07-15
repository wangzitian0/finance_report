"""AC-extraction.1832.4: a rejected parse must not leave a zombie bank account (#1832).

Staging real-statement QA (2026-07-14): a statement whose running-balance
chain fails the LLM-LED invariant gate is quarantined to REJECTED — but the
physical bank account auto-created moments earlier (#1444) for that same
parse was left behind: a balance-0.00, provenance-less account cluttering the
chart of accounts and the balance sheet, with nothing pointing at it.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

from sqlalchemy import select

from src.extraction import DocumentSource
from src.extraction.extension.service import ExtractionService
from src.extraction.orm.statement_enums import BankStatementStatus
from src.ledger import Account, AccountType


def _unreconciled_payload(institution: str, account_last4: str) -> dict:
    """A statement whose balance chain does not reconcile (guaranteed REJECTED)."""
    return {
        "institution": institution,
        "account_last4": account_last4,
        "currency": "SGD",
        "period_start": "2026-06-01",
        "period_end": "2026-06-30",
        "opening_balance": "1000.00",
        "closing_balance": "2000.00",  # gap the +100 transaction below cannot close
        "transactions": [
            {
                "date": "2026-06-15",
                "description": "Test",
                "amount": "100.00",
                "direction": "IN",
                "currency": "SGD",
                "balance_after": "1100.00",
            },
        ],
    }


def _balanced_payload(institution: str, account_last4: str, opening: str, closing: str, amount: str) -> dict:
    return {
        "institution": institution,
        "account_last4": account_last4,
        "currency": "SGD",
        "period_start": "2026-06-01",
        "period_end": "2026-06-30",
        "opening_balance": opening,
        "closing_balance": closing,
        "transactions": [
            {
                "date": "2026-06-15",
                "description": "Interest",
                "amount": amount,
                "direction": "IN",
                "currency": "SGD",
                "balance_after": closing,
            },
        ],
    }


async def _account_exists(db, user_id, institution: str, account_last4: str) -> Account | None:
    name = f"{institution} ••{account_last4}"
    return (
        await db.execute(
            select(Account)
            .where(Account.user_id == user_id)
            .where(Account.name == name)
            .where(Account.type == AccountType.ASSET)
        )
    ).scalar_one_or_none()


async def test_AC_extraction_1832_4_rejected_parse_deletes_the_account_it_just_created(db, test_user):
    """A fresh institution/last4 whose parse is quarantined leaves no account behind."""
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(return_value=_unreconciled_payload("DBS", "9911"))

    statement, _txns = await service.parse_document(
        DocumentSource.resolve(
            path=Path("ac-1832-4a.pdf"),
            content=b"%PDF-1.7",
            content_hash="ac-1832-4a",
        ),
        institution="DBS",
        user_id=test_user.id,
        db=db,
    )
    await db.flush()

    assert statement.status == BankStatementStatus.REJECTED
    assert statement.account_id is None
    assert await _account_exists(db, test_user.id, "DBS", "9911") is None


async def test_AC_extraction_1832_4_rejected_parse_never_deletes_a_preexisting_account(db, test_user):
    """A later rejected statement for an account already used by an earlier
    approved statement must not delete that account out from under it."""
    service = ExtractionService()

    service.extract_financial_data = AsyncMock(
        return_value=_balanced_payload("GXS", "7174", "500.00", "600.00", "100.00")
    )
    first, _txns = await service.parse_document(
        DocumentSource.resolve(
            path=Path("ac-1832-4b-first.pdf"),
            content=b"%PDF-1.7",
            content_hash="ac-1832-4b-first",
        ),
        institution="GXS",
        user_id=test_user.id,
        db=db,
    )
    await db.flush()
    assert first.status == BankStatementStatus.APPROVED
    assert first.account_id is not None

    service.extract_financial_data = AsyncMock(return_value=_unreconciled_payload("GXS", "7174"))
    second, _txns = await service.parse_document(
        DocumentSource.resolve(
            path=Path("ac-1832-4b-second.pdf"),
            content=b"%PDF-1.7",
            content_hash="ac-1832-4b-second",
        ),
        institution="GXS",
        user_id=test_user.id,
        db=db,
    )
    await db.flush()

    assert second.status == BankStatementStatus.REJECTED
    # The account is reused (get-or-create), so this parse never created a new
    # one — nothing should be deleted, and the first statement's account link
    # must survive untouched.
    account = await _account_exists(db, test_user.id, "GXS", "7174")
    assert account is not None
    assert account.id == first.account_id
    refreshed_first = await db.get(type(first), first.id)
    assert refreshed_first.account_id == account.id


async def test_AC_extraction_1832_4_no_db_session_skips_account_lifecycle_entirely(tmp_path):
    """Without a db session (e.g. dry-run callers), no account is created or
    referenced, so the quarantine cleanup path is simply a no-op."""
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(return_value=_unreconciled_payload("DBS", "4242"))

    statement, _txns = await service.parse_document(
        DocumentSource.resolve(
            path=Path("ac-1832-4c.pdf"),
            content=b"%PDF-1.7",
            content_hash="ac-1832-4c",
        ),
        institution="DBS",
        user_id=uuid4(),
        db=None,
    )

    assert statement.status == BankStatementStatus.REJECTED
    assert statement.account_id is None
