from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

from sqlalchemy import select
from src.extraction import BankStatementStatus, ClassificationStatus, DocumentSource, RuleType
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_posting import try_auto_approve_high_confidence_statement
from src.extraction.orm.layer3 import ClassificationRule, TransactionClassification
from src.ledger import Account, AccountType, JournalEntry, JournalEntryStatus
from tests.statement_ingestion import parse_and_load_statement_projection, posting_dependencies


def _pdf_with_text(text: str) -> bytes:
    from io import BytesIO
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    pdf = canvas.Canvas(buf)
    pdf.drawString(72, 720, text)
    pdf.showPage()
    pdf.save()
    return buf.getvalue()


async def test_bank_statement_auto_creates_account_and_posts_with_reviewed_disposition(db, test_user):
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(
        return_value={
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
                }
            ],
        }
    )
    _, stmt, txns = await parse_and_load_statement_projection(
        service,
        db=db,
        source=DocumentSource.resolve(
            path=Path("mari-2605.pdf"), content=_pdf_with_text("Opening 1000.00 Closing 1090.00 Interest 90.00")
        ),
        institution="MariBank",
        user_id=test_user.id,
    )
    await db.flush()
    account = await db.get(Account, stmt.account_id)
    assert account is not None and (account.type, account.is_active, account.currency, stmt.status) == (
        AccountType.ASSET,
        True,
        "SGD",
        BankStatementStatus.APPROVED,
    )

    txn = txns[0]
    income = Account(
        user_id=test_user.id, name="Income - Interest", code="4102", type=AccountType.INCOME, currency=txn.currency
    )
    db.add(income)
    await db.flush()
    rule = ClassificationRule(
        user_id=test_user.id,
        version_number=1,
        effective_date=txn.txn_date,
        rule_name="Reviewed interest disposition",
        rule_type=RuleType.KEYWORD_MATCH,
        rule_config={"keywords": ["interest"]},
        default_account_id=income.id,
        created_by=test_user.id,
    )
    db.add(rule)
    await db.flush()
    db.add(
        TransactionClassification(
            atomic_txn_id=txn.id,
            rule_version_id=rule.id,
            account_id=income.id,
            tags={"category": "INTEREST"},
            confidence_score=100,
            status=ClassificationStatus.APPLIED,
        )
    )
    await db.flush()

    posted = await try_auto_approve_high_confidence_statement(
        db, stmt.id, test_user.id, dependencies=posting_dependencies()
    )
    entries = (
        (
            await db.execute(
                select(JournalEntry).where(
                    JournalEntry.user_id == test_user.id, JournalEntry.status == JournalEntryStatus.POSTED
                )
            )
        )
        .scalars()
        .all()
    )
    assert posted >= 1 and len(entries) >= 1
