import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select

from src.extraction import (
    BankStatementStatus,
    DocumentSource,
    DocumentStatus,
    DocumentType,
    Stage1Status,
    TransactionDirection,
    UploadedDocument,
    register_statement_source,
)
from src.extraction.extension.service import ExtractionError, ExtractionService
from src.extraction.orm.evidence import EvidenceNode
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.statement_summary import StatementSummary
from tests.statement_ingestion import parse_and_load_statement_projection

MOCK_AI = {
    "account_last4": "1234",
    "currency": "SGD",
    "period_start": "2024-01-01",
    "period_end": "2024-01-31",
    "opening_balance": "1000.00",
    "closing_balance": "1500.00",
    "transactions": [
        {
            "date": "2024-01-15",
            "description": "Salary Deposit",
            "amount": "3000.00",
            "direction": "IN",
            "reference": "SAL001",
        },
        {
            "date": "2024-01-20",
            "description": "Rent Payment",
            "amount": "2500.00",
            "direction": "OUT",
            "reference": "RENT001",
        },
    ],
}
SAMPLE_BYTES = b"PDF-SAMPLE-CONTENT"


async def test_dual_write_creates_layer1_layer2_and_preserves_layer0(db, test_user):
    service, file_hash = ExtractionService(), hashlib.sha256(SAMPLE_BYTES).hexdigest()
    pre = StatementSummary(
        user_id=test_user.id,
        file_hash=file_hash,
        institution="DBS",
        currency="SGD",
        status=BankStatementStatus.UPLOADED,
        stage1_status=None,
    )
    db.add(pre)
    await db.flush()
    with patch.object(service, "extract_financial_data", return_value=MOCK_AI):
        ext_res, statement, transactions = await parse_and_load_statement_projection(
            service,
            db=db,
            source=DocumentSource.resolve(path=Path("test_statement.pdf"), content=SAMPLE_BYTES),
            institution="DBS",
            user_id=test_user.id,
        )
    await db.commit()
    uploaded_doc = (
        await db.execute(select(UploadedDocument).where(UploadedDocument.user_id == test_user.id))
    ).scalar_one()
    persisted = (await db.execute(select(StatementSummary).where(StatementSummary.file_hash == file_hash))).scalar_one()
    atomic_txns = (
        (
            await db.execute(
                select(AtomicTransaction)
                .where(AtomicTransaction.user_id == test_user.id)
                .order_by(AtomicTransaction.txn_date)
            )
        )
        .scalars()
        .all()
    )
    assert (
        ext_res.institution,
        ext_res.balances[0].currency,
        ext_res.balances[0].opening,
        ext_res.balances[0].closing,
        len(ext_res.transactions),
    ) == ("DBS", "SGD", Decimal("1000.00"), Decimal("1500.00"), 2)
    assert (
        statement is not None,
        len(transactions),
        uploaded_doc.file_hash,
        uploaded_doc.original_filename,
        uploaded_doc.document_type,
        uploaded_doc.status,
        uploaded_doc.extraction_metadata,
    ) == (True, 2, file_hash, "test_statement.pdf", DocumentType.BANK_STATEMENT, DocumentStatus.COMPLETED, None)
    assert (persisted.status, persisted.stage1_status) == (BankStatementStatus.PARSED, Stage1Status.PENDING_REVIEW)
    assert [(t.txn_date, t.description, t.amount, t.direction, t.currency, t.reference) for t in atomic_txns] == [
        (date(2024, 1, 15), "Salary Deposit", Decimal("3000.00"), TransactionDirection.IN, "SGD", "SAL001"),
        (date(2024, 1, 20), "Rent Payment", Decimal("2500.00"), TransactionDirection.OUT, "SGD", "RENT001"),
    ]

    with patch.object(service, "extract_financial_data", return_value=MOCK_AI):
        await service.parse_document(
            DocumentSource.resolve(path=Path("test_statement_v2.pdf"), content=b"DIFFERENT_FILE"),
            institution="DBS",
            user_id=test_user.id,
            db=db,
        )
    await db.commit()
    after = (
        (await db.execute(select(AtomicTransaction).where(AtomicTransaction.user_id == test_user.id))).scalars().all()
    )
    assert len(after) == 2 and all(isinstance(t.source_documents, list) and len(t.source_documents) == 2 for t in after)


async def test_dual_write_persists_brokerage_extraction_metadata(db, test_user):
    service, file_hash = ExtractionService(), hashlib.sha256(SAMPLE_BYTES).hexdigest()
    pre = StatementSummary(
        user_id=test_user.id, file_hash=file_hash, institution="Moomoo", status=BankStatementStatus.PARSING
    )
    db.add(pre)
    await db.flush()
    src_doc = await register_statement_source(
        db, statement=pre, storage_key="statements/moomoo-preparse.pdf", original_filename="moomoo-statement.pdf"
    )
    assert (src_doc.document_type, src_doc.status) == (DocumentType.BANK_STATEMENT, DocumentStatus.UPLOADED)
    brokerage = {
        "institution": "Moomoo",
        "currency": "SGD",
        "period_start": "2026-05-01",
        "period_end": "2026-05-31",
        "positions": [
            {"symbol": "Fullerton SGD Money Market Fund", "quantity": "1", "market_value": "1250.50", "currency": "SGD"}
        ],
        "transactions": [],
    }
    with patch.object(service, "extract_financial_data", return_value=brokerage):
        res, stmt, txns = await parse_and_load_statement_projection(
            service,
            db=db,
            source=DocumentSource.resolve(path=Path("moomoo-statement.pdf"), content=SAMPLE_BYTES),
            institution="Moomoo",
            user_id=test_user.id,
        )
    await db.commit()
    doc = (await db.execute(select(UploadedDocument).where(UploadedDocument.user_id == test_user.id))).scalar_one()
    node = (
        await db.execute(
            select(EvidenceNode).where(
                EvidenceNode.entity_type == "uploaded_document", EvidenceNode.entity_id == src_doc.id
            )
        )
    ).scalar_one()
    expected_meta = {"statement_extraction_result": res.to_payload()}
    assert (
        txns,
        bool(res.positions),
        stmt.extraction_metadata,
        doc.id,
        doc.document_type,
        doc.status,
        doc.extraction_metadata,
        node.properties["document_type"],
    ) == (
        [],
        True,
        expected_meta,
        src_doc.id,
        DocumentType.BROKERAGE_STATEMENT,
        DocumentStatus.COMPLETED,
        None,
        DocumentType.BROKERAGE_STATEMENT.value,
    )


async def test_dual_write_error_and_missing_db(db, test_user):
    service = ExtractionService()
    with (
        patch.object(service, "extract_financial_data", return_value=MOCK_AI),
        patch("src.extraction.extension.deduplication.resolve_source_identity", side_effect=Exception("DB error")),
        pytest.raises(ExtractionError) as exc_info,
    ):
        await service.parse_document(
            DocumentSource.resolve(path=Path("test_statement.pdf"), content=SAMPLE_BYTES),
            institution="DBS",
            user_id=test_user.id,
            db=db,
        )
    assert "Failed to parse document" in str(exc_info.value) and "Failed to write to Layer 2" in str(
        exc_info.value.__cause__
    )

    with patch.object(service, "extract_financial_data", return_value=MOCK_AI):
        res = await service.parse_document(
            DocumentSource.resolve(path=Path("test_statement.pdf"), content=SAMPLE_BYTES),
            institution="DBS",
            user_id=test_user.id,
            db=None,
        )
    assert res is not None and len(res.transactions) == 2


async def test_AC13_22_2_page_boundary_duplicate_deposit_survives(db, test_user):
    service = ExtractionService()
    payload = {
        "account_last4": "0001",
        "currency": "SGD",
        "period_start": "2024-04-01",
        "period_end": "2024-04-30",
        "opening_balance": "1000.00",
        "closing_balance": "1400.00",
        "transactions": [
            {
                "date": "2024-04-12",
                "description": "Incoming Transfer",
                "amount": "250.00",
                "direction": "IN",
                "balance_after": "1250.00",
            },
            {
                "date": "2024-04-12",
                "description": "Incoming Transfer",
                "amount": "250.00",
                "direction": "IN",
                "balance_after": "1250.00",
            },
            {
                "date": "2024-04-13",
                "description": "Card Spend",
                "amount": "100.00",
                "direction": "OUT",
                "balance_after": "1400.00",
            },
        ],
    }
    with patch.object(service, "extract_financial_data", return_value=payload):
        res, stmt, txns = await parse_and_load_statement_projection(
            service,
            db=db,
            source=DocumentSource.resolve(path=Path("synthetic_statement.pdf"), content=b"SYNTHETIC-PAGE-BOUNDARY"),
            institution="SynthBank",
            user_id=test_user.id,
        )
    await db.commit()
    atomic_txns = (
        (await db.execute(select(AtomicTransaction).where(AtomicTransaction.user_id == test_user.id))).scalars().all()
    )
    deposits = [t for t in atomic_txns if t.direction == TransactionDirection.IN]
    net = sum((t.amount if t.direction == TransactionDirection.IN else -t.amount for t in atomic_txns), Decimal("0.00"))
    assert (
        len(res.transactions),
        len(txns),
        len(deposits),
        all(d.amount == Decimal("250.00") for d in deposits),
        len(atomic_txns),
        stmt.opening_balance + net == stmt.closing_balance,
        stmt.balance_validated,
    ) == (3, 3, 2, True, 3, True, True)
