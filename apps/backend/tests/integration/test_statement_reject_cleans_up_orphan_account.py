from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

from sqlalchemy import select
from src.extraction import BankStatementStatus, DocumentSource
from src.extraction.extension.service import ExtractionService
from src.ledger import Account, AccountType
from tests.statement_ingestion import parse_and_load_statement_projection


def _unreconciled_payload(institution: str, last4: str) -> dict:
    return {
        "institution": institution,
        "account_last4": last4,
        "currency": "SGD",
        "period_start": "2026-06-01",
        "period_end": "2026-06-30",
        "opening_balance": "1000.00",
        "closing_balance": "2000.00",
        "transactions": [
            {
                "date": "2026-06-15",
                "description": "Test",
                "amount": "100.00",
                "direction": "IN",
                "currency": "SGD",
                "balance_after": "1100.00",
            }
        ],
    }


def _balanced_payload(institution: str, last4: str, opening: str, closing: str, amount: str) -> dict:
    return {
        "institution": institution,
        "account_last4": last4,
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
            }
        ],
    }


async def _find_account(db, user_id, institution: str, last4: str) -> Account | None:
    return (
        await db.execute(
            select(Account).where(
                Account.user_id == user_id,
                Account.name == f"{institution} ••{last4}",
                Account.type == AccountType.ASSET,
            )
        )
    ).scalar_one_or_none()


def _pdf_with_text(text: str) -> bytes:
    from io import BytesIO
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    pdf = canvas.Canvas(buf)
    pdf.drawString(72, 720, text)
    pdf.showPage()
    pdf.save()
    return buf.getvalue()


async def test_rejected_parse_deletes_orphan_account_but_preserves_preexisting(db, test_user):
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(return_value=_unreconciled_payload("DBS", "9911"))
    _, stmt, _ = await parse_and_load_statement_projection(
        service,
        db=db,
        source=DocumentSource.resolve(path=Path("rej-a.pdf"), content=b"%PDF-1.7", content_hash="rej-a"),
        institution="DBS",
        user_id=test_user.id,
    )
    await db.flush()
    assert (stmt.status, stmt.account_id, await _find_account(db, test_user.id, "DBS", "9911")) == (
        BankStatementStatus.REJECTED,
        None,
        None,
    )

    service.extract_financial_data = AsyncMock(
        return_value=_balanced_payload("GXS", "7174", "500.00", "600.00", "100.00")
    )
    _, first, _ = await parse_and_load_statement_projection(
        service,
        db=db,
        source=DocumentSource.resolve(
            path=Path("rej-b1.pdf"),
            content=_pdf_with_text("Opening 500.00 Closing 600.00 Interest 100.00"),
            content_hash="rej-b1",
        ),
        institution="GXS",
        user_id=test_user.id,
    )
    await db.flush()
    assert first.status == BankStatementStatus.APPROVED and first.account_id is not None

    service.extract_financial_data = AsyncMock(return_value=_unreconciled_payload("GXS", "7174"))
    _, second, _ = await parse_and_load_statement_projection(
        service,
        db=db,
        source=DocumentSource.resolve(path=Path("rej-b2.pdf"), content=b"%PDF-1.7", content_hash="rej-b2"),
        institution="GXS",
        user_id=test_user.id,
    )
    await db.flush()
    account = await _find_account(db, test_user.id, "GXS", "7174")
    refreshed_first = await db.get(type(first), first.id)
    assert (second.status, account is not None, account.id, refreshed_first.account_id) == (
        BankStatementStatus.REJECTED,
        True,
        first.account_id,
        account.id,
    )


async def test_no_db_session_skips_account_lifecycle_entirely():
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(return_value=_unreconciled_payload("DBS", "4242"))
    result = await service.parse_document(
        DocumentSource.resolve(path=Path("rej-c.pdf"), content=b"%PDF-1.7", content_hash="rej-c"),
        institution="DBS",
        user_id=uuid4(),
        db=None,
    )
    assert result.balance_validated is False and result.review_reasons
