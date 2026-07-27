"""Integration tests for EPIC-011 Phase 2 dual write to Layer 1/2."""

import hashlib
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select

from src.extraction import (
    DocumentSource,
    DocumentStatus,
    DocumentType,
    ExtractedTransactionRow,
    UploadedDocument,
    register_statement_source,
)
from src.extraction.extension.deduplication import DeduplicationService
from src.extraction.extension.service import ExtractionService
from src.extraction.orm.evidence import EvidenceNode
from src.extraction.orm.layer2 import AtomicTransaction, TransactionDirection
from src.extraction.orm.statement_enums import BankStatementStatus, Stage1Status
from src.extraction.orm.statement_summary import StatementSummary
from tests.statement_ingestion import parse_and_load_statement_projection


@pytest.fixture
def mock_ai_response():
    """Mock AI extraction response."""
    return {
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


@pytest.fixture
def sample_file_content():
    """Sample PDF content."""
    return b"PDF-SAMPLE-CONTENT"


class TestDualWriteLayer2:
    async def test_dual_write_enabled_by_default(self, db, test_user, mock_ai_response, sample_file_content):
        """AC-extraction.213.1: After Stage 1 cutover, parsing populates Layer 1/2 without any flag override."""
        service = ExtractionService()

        with patch.object(service, "extract_financial_data", return_value=mock_ai_response):
            extraction_result, statement, transactions = await parse_and_load_statement_projection(
                service,
                db=db,
                source=DocumentSource.resolve(path=Path("test_statement.pdf"), content=sample_file_content),
                institution="DBS",
                user_id=test_user.id,
            )

        assert extraction_result.transactions
        assert statement is not None
        assert len(transactions) == 2

        result = await db.execute(select(UploadedDocument).where(UploadedDocument.user_id == test_user.id))
        uploaded_docs = result.scalars().all()
        assert len(uploaded_docs) == 1

        result = await db.execute(select(AtomicTransaction).where(AtomicTransaction.user_id == test_user.id))
        atomic_txns = result.scalars().all()
        assert len(atomic_txns) == 2

    async def test_dual_write_creates_layer1_document(
        self, db, test_user, mock_ai_response, sample_file_content, monkeypatch
    ):
        service = ExtractionService()
        file_hash = hashlib.sha256(sample_file_content).hexdigest()

        with patch.object(service, "extract_financial_data", return_value=mock_ai_response):
            _extraction_result, statement, transactions = await parse_and_load_statement_projection(
                service,
                db=db,
                source=DocumentSource.resolve(path=Path("test_statement.pdf"), content=sample_file_content),
                institution="DBS",
                user_id=test_user.id,
            )

        await db.commit()

        result = await db.execute(select(UploadedDocument).where(UploadedDocument.user_id == test_user.id))
        uploaded_doc = result.scalar_one()

        assert uploaded_doc.file_hash == file_hash
        assert uploaded_doc.original_filename == "test_statement.pdf"
        assert uploaded_doc.document_type == DocumentType.BANK_STATEMENT
        assert uploaded_doc.extraction_metadata == {"statement_extraction_result": _extraction_result.to_payload()}

    async def test_dual_write_marks_document_completed(self, db, test_user, mock_ai_response, sample_file_content):
        """AC-extraction.1622.9: a successfully parsed-and-persisted document advances to status=completed
        instead of staying stuck at 'uploaded'."""
        service = ExtractionService()

        with patch.object(service, "extract_financial_data", return_value=mock_ai_response):
            await service.parse_document(
                DocumentSource.resolve(path=Path("test_statement.pdf"), content=sample_file_content),
                institution="DBS",
                user_id=test_user.id,
                db=db,
            )

        await db.commit()

        uploaded_doc = (
            await db.execute(select(UploadedDocument).where(UploadedDocument.user_id == test_user.id))
        ).scalar_one()
        assert uploaded_doc.status == DocumentStatus.COMPLETED

    async def test_dual_write_persists_pending_review_onto_reused_envelope(
        self, db, test_user, mock_ai_response, sample_file_content
    ):
        """AC-extraction.1622.8: in the real flow the upload pre-creates a StatementSummary envelope, so
        dual_write reconciles onto that reused row. The freshly-computed stage1_status=pending_review
        must be persisted there, not dropped (the no-db unit path hid this)."""
        service = ExtractionService()
        file_hash = hashlib.sha256(sample_file_content).hexdigest()

        # Pre-create the envelope exactly as the upload endpoint does (reused by user_id+file_hash).
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

        with patch.object(service, "extract_financial_data", return_value=mock_ai_response):
            await service.parse_document(
                DocumentSource.resolve(path=Path("test_statement.pdf"), content=sample_file_content),
                institution="DBS",
                user_id=test_user.id,
                db=db,
            )
        await db.commit()

        persisted = (
            await db.execute(select(StatementSummary).where(StatementSummary.file_hash == file_hash))
        ).scalar_one()
        assert persisted.status == BankStatementStatus.PARSED
        assert persisted.stage1_status == Stage1Status.PENDING_REVIEW

    async def test_dual_write_persists_brokerage_extraction_metadata(
        self, db, test_user, sample_file_content, monkeypatch
    ):
        """AC-extraction.304.7: Brokerage enrichment retains the registered source artifact."""

        service = ExtractionService()
        file_hash = hashlib.sha256(sample_file_content).hexdigest()
        precreated = StatementSummary(
            user_id=test_user.id,
            file_hash=file_hash,
            institution="Moomoo",
            status=BankStatementStatus.PARSING,
        )
        db.add(precreated)
        await db.flush()
        source_document = await register_statement_source(
            db,
            statement=precreated,
            storage_key="statements/moomoo-preparse.pdf",
            original_filename="moomoo-statement.pdf",
        )
        assert source_document.document_type is DocumentType.BANK_STATEMENT
        assert source_document.status is DocumentStatus.UPLOADED

        brokerage_response = {
            "institution": "Moomoo",
            "currency": "SGD",
            "period_start": "2026-05-01",
            "period_end": "2026-05-31",
            "positions": [
                {
                    "symbol": "Fullerton SGD Money Market Fund",
                    "quantity": "1",
                    "market_value": "1250.50",
                    "currency": "SGD",
                }
            ],
            "transactions": [],
        }

        with patch.object(service, "extract_financial_data", return_value=brokerage_response):
            extraction_result, statement, transactions = await parse_and_load_statement_projection(
                service,
                db=db,
                source=DocumentSource.resolve(path=Path("moomoo-statement.pdf"), content=sample_file_content),
                institution="Moomoo",
                user_id=test_user.id,
            )

        await db.commit()

        result = await db.execute(select(UploadedDocument).where(UploadedDocument.user_id == test_user.id))
        uploaded_doc = result.scalar_one()

        assert transactions == []
        assert extraction_result.positions
        assert statement.extraction_metadata == {"statement_extraction_result": extraction_result.to_payload()}
        assert uploaded_doc.id == source_document.id
        assert uploaded_doc.document_type == DocumentType.BROKERAGE_STATEMENT
        assert uploaded_doc.status is DocumentStatus.COMPLETED
        assert uploaded_doc.extraction_metadata == {"statement_extraction_result": extraction_result.to_payload()}
        source_node = (
            await db.execute(
                select(EvidenceNode)
                .where(EvidenceNode.entity_type == "uploaded_document")
                .where(EvidenceNode.entity_id == source_document.id)
            )
        ).scalar_one()
        assert source_node.properties["document_type"] == DocumentType.BROKERAGE_STATEMENT.value

    async def test_dual_write_creates_atomic_transactions(
        self, db, test_user, mock_ai_response, sample_file_content, monkeypatch
    ):
        service = ExtractionService()

        with patch.object(service, "extract_financial_data", return_value=mock_ai_response):
            _extraction_result, statement, transactions = await parse_and_load_statement_projection(
                service,
                db=db,
                source=DocumentSource.resolve(path=Path("test_statement.pdf"), content=sample_file_content),
                institution="DBS",
                user_id=test_user.id,
            )

        await db.commit()

        result = await db.execute(
            select(AtomicTransaction)
            .where(AtomicTransaction.user_id == test_user.id)
            .order_by(AtomicTransaction.txn_date)
        )
        atomic_txns = result.scalars().all()

        assert len(atomic_txns) == 2

        txn1 = atomic_txns[0]
        assert txn1.txn_date == date(2024, 1, 15)
        assert txn1.description == "Salary Deposit"
        assert txn1.amount == Decimal("3000.00")
        assert txn1.direction == TransactionDirection.IN
        assert txn1.currency == "SGD"
        assert txn1.reference == "SAL001"

        txn2 = atomic_txns[1]
        assert txn2.txn_date == date(2024, 1, 20)
        assert txn2.description == "Rent Payment"
        assert txn2.amount == Decimal("2500.00")
        assert txn2.direction == TransactionDirection.OUT
        assert txn2.reference == "RENT001"

    async def test_dual_write_deduplication_on_reupload(
        self, db, test_user, mock_ai_response, sample_file_content, monkeypatch
    ):
        service = ExtractionService()

        with patch.object(service, "extract_financial_data", return_value=mock_ai_response):
            await service.parse_document(
                DocumentSource.resolve(path=Path("test_statement.pdf"), content=sample_file_content),
                institution="DBS",
                user_id=test_user.id,
                db=db,
            )
            await db.commit()

        result = await db.execute(select(AtomicTransaction).where(AtomicTransaction.user_id == test_user.id))
        atomic_txns_before = result.scalars().all()
        assert len(atomic_txns_before) == 2

        with patch.object(service, "extract_financial_data", return_value=mock_ai_response):
            await service.parse_document(
                DocumentSource.resolve(path=Path("test_statement_v2.pdf"), content=b"DIFFERENT_FILE"),
                institution="DBS",
                user_id=test_user.id,
                db=db,
            )
            await db.commit()

        result = await db.execute(select(AtomicTransaction).where(AtomicTransaction.user_id == test_user.id))
        atomic_txns_after = result.scalars().all()
        assert len(atomic_txns_after) == 2

        for txn in atomic_txns_after:
            assert isinstance(txn.source_documents, list)
            assert len(txn.source_documents) == 2

    async def test_dual_write_preserves_layer0_behavior(
        self, db, test_user, mock_ai_response, sample_file_content, monkeypatch
    ):
        service = ExtractionService()

        with patch.object(service, "extract_financial_data", return_value=mock_ai_response):
            extraction_result = await service.parse_document(
                DocumentSource.resolve(path=Path("test_statement.pdf"), content=sample_file_content),
                institution="DBS",
                user_id=test_user.id,
                db=db,
            )

        assert extraction_result.institution == "DBS"
        assert extraction_result.balances[0].currency == "SGD"
        assert extraction_result.balances[0].opening == Decimal("1000.00")
        assert extraction_result.balances[0].closing == Decimal("1500.00")
        assert len(extraction_result.transactions) == 2

    async def test_dual_write_failure_raises_error(
        self, db, test_user, mock_ai_response, sample_file_content, monkeypatch
    ):
        """Test that dual-write failures (non-IntegrityError) raise RuntimeError."""

        service = ExtractionService()

        from src.extraction.extension.service import ExtractionError

        with patch.object(service, "extract_financial_data", return_value=mock_ai_response):
            with patch(
                "src.extraction.extension.deduplication.resolve_source_identity",
                side_effect=Exception("DB error"),
            ):
                with pytest.raises(ExtractionError) as exc_info:
                    await service.parse_document(
                        DocumentSource.resolve(path=Path("test_statement.pdf"), content=sample_file_content),
                        institution="DBS",
                        user_id=test_user.id,
                        db=db,
                    )

        assert "Failed to parse document" in str(exc_info.value)
        assert "Failed to write to Layer 2" in str(exc_info.value.__cause__)

    async def test_dual_write_handles_missing_db_session(
        self, test_user, mock_ai_response, sample_file_content, monkeypatch
    ):
        service = ExtractionService()

        with patch.object(service, "extract_financial_data", return_value=mock_ai_response):
            extraction_result = await service.parse_document(
                DocumentSource.resolve(path=Path("test_statement.pdf"), content=sample_file_content),
                institution="DBS",
                user_id=test_user.id,
                db=None,
            )

        assert extraction_result is not None
        assert len(extraction_result.transactions) == 2

    async def test_dual_write_integrity_error_silent(self, db, test_user, sample_file_content, monkeypatch):
        """Test that IntegrityError (duplicate upload) is silently handled."""
        from sqlalchemy.exc import IntegrityError

        from src.extraction.extension.deduplication import dual_write_layer2
        from tests.factories import StatementSummaryFactory

        file_hash = hashlib.sha256(sample_file_content).hexdigest()

        statement = StatementSummaryFactory.build(
            user_id=test_user.id,
            file_hash=file_hash,
            institution="DBS",
            account_last4="1234",
            currency="SGD",
            period_start=date(2024, 1, 1),
            period_end=date(2024, 1, 31),
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("1500.00"),
        )
        txn_date = date(2024, 1, 15)
        amount = Decimal("3000.00")
        direction = TransactionDirection.IN
        description = "Salary Deposit"
        reference = "SAL001"
        txn = ExtractedTransactionRow(
            user_id=test_user.id,
            txn_date=txn_date,
            description=description,
            amount=amount,
            direction=direction.value,
            reference=reference,
            currency="SGD",
            currency_unresolved=False,
            balance_after=None,
            occurrence_index=0,
            dedup_hash=DeduplicationService.calculate_transaction_hash(
                test_user.id,
                txn_date,
                amount,
                direction,
                description,
                reference,
            ),
        )
        transactions = [txn]

        # Mock create_uploaded_document to raise IntegrityError
        with patch(
            "src.extraction.extension.deduplication.DeduplicationService.create_uploaded_document",
            side_effect=IntegrityError("INSERT", [], Exception("duplicate")),
        ):
            # Should not raise - IntegrityError is silently handled
            result = await dual_write_layer2(
                db=db,
                user_id=test_user.id,
                statement=statement,
                transactions=transactions,
                file_path=Path("test_statement.pdf"),
                original_filename="test_statement.pdf",
            )

        # Function should return None on IntegrityError
        assert result is None

    async def test_AC13_22_2_page_boundary_duplicate_deposit_survives(self, db, test_user):
        """AC-extraction.122.2: a statement with two distinct same-date/same-amount deposits separated by a
        carried-forward / brought-forward balance repeat across a page boundary persists BOTH
        deposits, and the running-balance chain reconciles (#1254).

        Synthetic, anonymized payload — no real bank names, amounts, or filenames. The two deposits
        are both extracted with the SAME ``balance_after`` because the OCR/LLM reads the repeated
        carried-forward / brought-forward running balance against each row. Before the fix the two
        rows hashed identically (balance_after was the sole disambiguator) and the second collapsed,
        dropping exactly one deposit and breaking the balance chain. The fix keeps both via the
        per-document occurrence ordinal."""
        service = ExtractionService()
        file_content = b"SYNTHETIC-PAGE-BOUNDARY-STATEMENT"

        # opening 1000 -> +250 -> +250 -> -100 -> closing 1400. The two +250 deposits are genuinely
        # distinct but both carry the SAME extracted balance_after (1250) because the OCR/LLM reads
        # the repeated carried-forward / brought-forward running balance printed across the page
        # boundary against each row. This is exactly the collapse condition: identical
        # (date, amount, direction, description, balance_after) for two real rows.
        page_boundary_response = {
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

        with patch.object(service, "extract_financial_data", return_value=page_boundary_response):
            extraction_result, statement, transactions = await parse_and_load_statement_projection(
                service,
                db=db,
                source=DocumentSource.resolve(path=Path("synthetic_statement.pdf"), content=file_content),
                institution="SynthBank",
                user_id=test_user.id,
            )

        await db.commit()

        # Both same-amount deposits survived extraction (the parser appends every row).
        assert len(extraction_result.transactions) == 3
        assert len(transactions) == 3

        # Both deposits persisted to Layer 2 — the dedup layer must NOT collapse them.
        atomic_txns = (
            (await db.execute(select(AtomicTransaction).where(AtomicTransaction.user_id == test_user.id)))
            .scalars()
            .all()
        )
        deposits = [t for t in atomic_txns if t.direction == TransactionDirection.IN]
        assert len(deposits) == 2, "both distinct same-amount deposits must persist (no dedup collapse)"
        assert all(d.amount == Decimal("250.00") for d in deposits)
        assert len(atomic_txns) == 3

        # The deterministic running-balance chain reconciles: opening + ΣIN − ΣOUT == closing.
        net = sum(
            (t.amount if t.direction == TransactionDirection.IN else -t.amount for t in atomic_txns),
            Decimal("0.00"),
        )
        assert statement.opening_balance + net == statement.closing_balance
        assert statement.balance_validated is True
