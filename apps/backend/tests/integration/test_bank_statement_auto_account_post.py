"""AC8.15.2: a bank statement auto-creates+links its physical account (#1444).

The everyday-user flow uploads a bank statement without picking an account. A
high-confidence, balance-validated statement must therefore auto-create and link
its physical asset account (by institution + account_last4 + currency) so it can
reach APPROVED and auto-post to the ledger — instead of being stranded in review
with empty reports. Category (counter-account) classification stays a separate,
user-adjustable layer and is not exercised here.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from sqlalchemy import select

from src.models.account import Account, AccountType
from src.models.journal import JournalEntry, JournalEntryStatus
from src.models.statement_enums import BankStatementStatus
from src.services.extraction import ExtractionService
from src.services.statement_posting import try_auto_approve_high_confidence_statement


def _balanced_bank_payload() -> dict:
    # CR on #1467: a non-normalized extraction currency ("sgd") must still produce a
    # canonical account currency so the posting-account currency check matches and
    # auto-post is not silently blocked.
    return {
        "institution": "MariBank",
        "account_last4": "8497",
        "currency": "sgd",
        "period_start": "2026-05-01",
        "period_end": "2026-05-31",
        "opening_balance": "1000.00",
        "closing_balance": "1090.00",
        "transactions": [
            {
                "date": "2026-05-10",
                "description": "Interest",
                "amount": "90.00",
                "direction": "IN",
                "currency": "sgd",
                "balance_after": "1090.00",
            },
        ],
    }


async def test_AC8_15_2_bank_statement_auto_creates_account_and_posts_without_manual_mapping(db, test_user):
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(return_value=_balanced_bank_payload())

    # No account_id passed — the everyday-user upload path.
    statement, _txns = await service.parse_document(
        file_path=Path("mari-2605.pdf"),
        institution="MariBank",
        user_id=test_user.id,
        file_content=b"%PDF-1.7",
        file_hash="ac-8-15-2-auto-account",
        db=db,
    )
    await db.flush()

    # Physical account auto-created + linked; the high-confidence statement reaches APPROVED.
    assert statement.account_id is not None
    account = await db.get(Account, statement.account_id)
    assert account is not None
    assert account.type == AccountType.ASSET
    assert account.is_active is True
    assert account.currency == "SGD"  # normalized from the lowercase extraction currency
    assert statement.status == BankStatementStatus.APPROVED

    # And it auto-posts to the ledger (so reports would reflect it).
    posted = await try_auto_approve_high_confidence_statement(db, statement.id, test_user.id)
    assert posted >= 1

    posted_entries = (
        (
            await db.execute(
                select(JournalEntry).where(
                    JournalEntry.user_id == test_user.id,
                    JournalEntry.status == JournalEntryStatus.POSTED,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(posted_entries) >= 1
