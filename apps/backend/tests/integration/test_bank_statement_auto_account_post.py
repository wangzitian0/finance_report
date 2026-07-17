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

from src.extraction import DocumentSource
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_posting import try_auto_approve_high_confidence_statement
from src.extraction.orm.layer3 import ClassificationRule, ClassificationStatus, RuleType, TransactionClassification
from src.extraction.orm.statement_enums import BankStatementStatus
from src.ledger import Account, AccountType, JournalEntry, JournalEntryStatus
from tests.statement_ingestion import (
    parse_and_load_statement_projection,
    posting_dependencies,
)


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


async def _apply_reviewed_interest_disposition(db, user_id, transaction) -> None:
    """Create the reviewed category basis needed for an authoritative posting."""
    income = Account(
        user_id=user_id,
        name="Income - Interest",
        code="4102",
        type=AccountType.INCOME,
        currency=transaction.currency,
    )
    db.add(income)
    await db.flush()
    rule = ClassificationRule(
        user_id=user_id,
        version_number=1,
        effective_date=transaction.txn_date,
        rule_name="Reviewed interest disposition",
        rule_type=RuleType.KEYWORD_MATCH,
        rule_config={"keywords": ["interest"]},
        default_account_id=income.id,
        created_by=user_id,
    )
    db.add(rule)
    await db.flush()
    db.add(
        TransactionClassification(
            atomic_txn_id=transaction.id,
            rule_version_id=rule.id,
            account_id=income.id,
            tags={"category": "INTEREST"},
            confidence_score=100,
            status=ClassificationStatus.APPLIED,
        )
    )
    await db.flush()


async def test_AC8_15_2_bank_statement_auto_creates_account_and_posts_with_reviewed_disposition(db, test_user):
    """AC-reporting.full-year.2: auto-created custody account posts only with reviewed meaning."""
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(return_value=_balanced_bank_payload())

    # No account_id passed — the everyday-user upload path.
    _result, statement, transactions = await parse_and_load_statement_projection(
        service,
        db=db,
        source=DocumentSource.resolve(path=Path("mari-2605.pdf"), content=b"%PDF-1.7"),
        institution="MariBank",
        user_id=test_user.id,
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
    await _apply_reviewed_interest_disposition(db, test_user.id, transactions[0])

    # The reviewed income basis gives the posting engine a category and counter-account.
    posted = await try_auto_approve_high_confidence_statement(
        db, statement.id, test_user.id, dependencies=posting_dependencies()
    )
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
