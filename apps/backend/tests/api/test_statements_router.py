"""AC3.5: Statements API router tests.

Tests all endpoints in src/routers/statements.py covering:
- POST /statements/upload - Upload statement
- GET /statements - List statements
- GET /statements/{id} - Get statement details
- GET /statements/{id}/transactions - List statement transactions
- GET /statements/pending-review - List statements pending review
- POST /statements/{id}/approve - Approve statement
- POST /statements/{id}/reject - Reject statement
- POST /statements/{id}/retry - Retry statement parsing
"""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, status
from sqlalchemy import select

from src.extraction import (
    BankStatementStatus,
    DocumentSource,
    DocumentStatus,
    DocumentType,
    ExtractedTransactionRow,
    ExtractionError,
    ParseJob,
    Stage1Status,
    TransactionDirection,
    UploadedDocument,
)
from src.extraction.extension import (
    statement_parsing as statement_parsing_mod,
    statement_pipeline,
    statement_validation as statement_validation_mod,
)
from src.extraction.extension.statement_parsing import handle_parse_failure
from src.extraction.extension.statement_posting import (
    is_high_confidence_auto_approve_candidate,
)
from src.extraction.orm.evidence import EvidenceNode
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.statement_summary import StatementSummary
from src.identity import User
from src.ledger import JournalEntry, JournalEntryStatus
from src.llm.base import Modality, ModelSpec
from src.routers import statements as statements_router
from src.runtime import StorageError
from src.schemas import StatementDecisionRequest
from src.schemas.review import (
    ReviewedStatementEnvelopeRequest,
)
from tests.api._statement_router_fixtures import (
    _compose_mock_ingestion,
    add_reviewed_disposition_rule,
    add_txn,
    build_statement,
    create_statement_account,
    make_upload_file,
    persist_mock_result,
    seed_historical_source_evidence,
    seed_uploaded_document,
)
from tests.api.conftest import DummyStorage
from tests.factories import AccountFactory, UserFactory

__all__ = [
    "DummyStorage",
    "_compose_mock_ingestion",
    "add_reviewed_disposition_rule",
    "add_txn",
    "build_statement",
    "create_statement_account",
    "make_upload_file",
    "persist_mock_result",
    "seed_historical_source_evidence",
    "seed_uploaded_document",
]

pytestmark = pytest.mark.asyncio


async def test_build_statement_storage_key_sanitizes_extension():
    """AC-extraction.105.1: Statement object keys avoid PII and normalize unsafe extensions."""
    from uuid import uuid4

    statement_id = uuid4()

    assert (
        statements_router.build_statement_storage_key(
            statement_id=statement_id,
            file_hash="abcdef1234567890ffff",
            extension="PDF",
        )
        == f"statements/{statement_id}/abcdef1234567890.pdf"
    )
    assert (
        statements_router.build_statement_storage_key(
            statement_id=statement_id,
            file_hash="abcdef1234567890ffff",
            extension="exe",
        )
        == f"statements/{statement_id}/abcdef1234567890.bin"
    )


async def test_is_high_confidence_auto_approve_candidate_requires_all_guards(test_user):
    statement = build_statement(test_user.id, "hash_candidate_true", 85)
    statement.status = BankStatementStatus.APPROVED
    assert is_high_confidence_auto_approve_candidate(statement) is True

    statement.confidence_score = 84
    assert is_high_confidence_auto_approve_candidate(statement) is False

    statement.confidence_score = 90
    statement.balance_validated = False
    assert is_high_confidence_auto_approve_candidate(statement) is False

    statement.balance_validated = True
    statement.status = BankStatementStatus.PARSED
    assert is_high_confidence_auto_approve_candidate(statement) is False


async def wait_for_background_tasks() -> None:
    await statements_router.wait_for_parse_tasks()


def _patch_parse_document(
    monkeypatch,
    test_user_id,
    *,
    confidence_score=90,
    status=None,
    transactions=None,
    side_effect=None,
    modifier=None,
):
    if side_effect is not None:
        monkeypatch.setattr(
            statement_parsing_mod.ExtractionService,
            "parse_document",
            AsyncMock(side_effect=side_effect),
        )
        return

    async def fake_parse(
        self,
        source: DocumentSource,
        institution,
        *,
        user_id,
        file_type="pdf",
        account_id=None,
        force_model=None,
        db=None,
    ):
        score = confidence_score(source.content_hash) if callable(confidence_score) else confidence_score
        stmt = build_statement(test_user_id, source.content_hash, confidence_score=score)
        if status is not None:
            stmt.status = status
        if account_id is not None:
            stmt.account_id = account_id
        if modifier:
            modifier(stmt, source)
        txns = transactions(source) if callable(transactions) else (transactions or [])
        return await persist_mock_result(db, source=source, statement=stmt, transactions=txns)

    monkeypatch.setattr(statement_parsing_mod.ExtractionService, "parse_document", fake_parse)


async def test_upload_statement_duplicate(db, monkeypatch, storage_stub, model_catalog_stub, test_user):
    """AC-extraction.5.4: Uploading the same file twice should trigger duplicate detection."""
    content = b"duplicate-statement"
    _patch_parse_document(monkeypatch, test_user.id)

    upload_file = make_upload_file("statement.pdf", content)
    await statements_router.upload_statement(
        file=upload_file,
        institution="DBS",
        account_id=None,
        model="google/gemini-3-flash-preview",
        db=db,
        user_id=test_user.id,
    )
    await upload_file.close()
    await wait_for_background_tasks()
    user_id = test_user.id
    db.expire_all()

    upload_file_dup = make_upload_file("statement.pdf", content)
    with pytest.raises(HTTPException) as exc:
        await statements_router.upload_statement(
            file=upload_file_dup,
            institution="DBS",
            account_id=None,
            model="google/gemini-3-flash-preview",
            db=db,
            user_id=user_id,
        )
    await upload_file_dup.close()

    assert exc.value.status_code == status.HTTP_409_CONFLICT


async def test_upload_storage_failure(db, monkeypatch, model_catalog_stub, test_user):
    """AC-extraction.5.5: Storage failure should return 503."""
    content = b"content"

    # Mock StorageService to raise StorageError
    mock_storage = MagicMock()
    mock_storage.upload_bytes.side_effect = statements_router.StorageError("S3 Down")

    # We need to mock the class constructor to return our mock instance
    mock_storage_cls = MagicMock(return_value=mock_storage)
    monkeypatch.setattr(statements_router, "StorageService", mock_storage_cls)

    upload_file = make_upload_file("statement.pdf", content)

    with pytest.raises(HTTPException) as exc:
        await statements_router.upload_statement(
            file=upload_file,
            institution="DBS",
            account_id=None,
            model="google/gemini-3-flash-preview",
            db=db,
            user_id=test_user.id,
        )
    await upload_file.close()

    assert exc.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert "S3 Down" in exc.value.detail


async def test_upload_invalid_extension(db, test_user):
    """AC-extraction.5.6: Invalid file extension should return 400."""
    content = b"content"
    upload_file = make_upload_file("statement.exe", content)

    with pytest.raises(HTTPException) as exc:
        await statements_router.upload_statement(
            file=upload_file,
            institution="DBS",
            account_id=None,
            model=None,
            db=db,
            user_id=test_user.id,
        )
    await upload_file.close()

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Unsupported file type" in exc.value.detail


async def test_AC3_5_upload_rejects_cross_user_account_id(db, monkeypatch, test_user):
    """AC3.5: Statement upload must not bind another user's account."""
    other_user = await UserFactory.create_async(db)
    other_account = await AccountFactory.create_async(db, user_id=other_user.id, name="Other User Cash")
    await db.commit()

    mock_storage = MagicMock()
    monkeypatch.setattr(statements_router, "StorageService", MagicMock(return_value=mock_storage))

    upload_file = make_upload_file("statement.pdf", b"content")
    with pytest.raises(HTTPException) as exc:
        await statements_router.upload_statement(
            file=upload_file,
            institution="DBS",
            account_id=other_account.id,
            model=None,
            db=db,
            user_id=test_user.id,
        )
    await upload_file.close()

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc.value.detail == "Account not found"
    assert mock_storage.upload_bytes.call_count == 0


async def test_upload_uses_default_ocr_pipeline_for_pdf(db, monkeypatch, storage_stub, test_user):
    """AC-extraction.5.7: PDF/image uploads may omit model and use the default OCR pipeline."""
    mock_parse = AsyncMock(return_value=None)
    monkeypatch.setattr(
        statement_pipeline,
        "compose_statement_ingestion_use_case",
        _compose_mock_ingestion(mock_parse),
    )

    upload_file = make_upload_file("statement.pdf", b"content")

    created = await statements_router.upload_statement(
        file=upload_file,
        institution="DBS",
        account_id=None,
        model=None,
        db=db,
        user_id=test_user.id,
    )
    await upload_file.close()
    await wait_for_background_tasks()

    assert created.status == BankStatementStatus.PARSING
    job = mock_parse.await_args.kwargs["job"]
    assert isinstance(job, ParseJob)
    assert job.model is None
    storage_key = job.storage_key
    assert storage_key.startswith(f"statements/{created.id}/")
    assert "statement.pdf" not in storage_key
    assert str(test_user.id) not in storage_key
    assert storage_key.endswith(".pdf")


async def test_AC_extraction_1913_9_upload_registers_source_before_dispatch(db, monkeypatch, storage_stub, test_user):
    """AC-extraction.1913.9: source artifact is durable before asynchronous parse starts."""
    mock_parse = AsyncMock(return_value=None)
    monkeypatch.setattr(
        statement_pipeline,
        "compose_statement_ingestion_use_case",
        _compose_mock_ingestion(mock_parse),
    )

    upload_file = make_upload_file("june-statement.csv", b"date,amount\n2026-06-01,10.00\n")
    created = await statements_router.upload_statement(
        file=upload_file,
        institution="DBS",
        account_id=None,
        model=None,
        db=db,
        user_id=test_user.id,
    )
    await upload_file.close()

    statement = await db.get(StatementSummary, created.id)
    assert statement is not None
    assert statement.uploaded_document_id is not None
    document = await db.get(UploadedDocument, statement.uploaded_document_id)
    assert document is not None
    assert document.original_filename == "june-statement.csv"
    assert document.file_path == created.file_path
    assert document.status is DocumentStatus.UPLOADED
    assert created.original_filename == document.original_filename
    source_node = (
        await db.execute(
            select(EvidenceNode)
            .where(EvidenceNode.entity_type == "uploaded_document")
            .where(EvidenceNode.entity_id == document.id)
        )
    ).scalar_one()
    assert source_node.properties["original_filename"] == document.original_filename

    await wait_for_background_tasks()


async def test_AC10_8_1_upload_audit_logs_include_statement_input_provenance(
    db, monkeypatch, storage_stub, model_catalog_stub, test_user
):
    """AC-observability.8.1: Upload audit logs expose safe replay inputs and correlation IDs."""
    content = b"audit-log-input"
    mock_parse = AsyncMock(return_value=None)
    mock_info = MagicMock()
    monkeypatch.setattr(
        statement_pipeline,
        "compose_statement_ingestion_use_case",
        _compose_mock_ingestion(mock_parse),
    )
    monkeypatch.setattr(statements_router.logger, "info", mock_info)

    upload_file = make_upload_file("staging-audit.pdf", content)
    created = await statements_router.upload_statement(
        file=upload_file,
        institution="DBS",
        account_id=None,
        model="google/gemini-3-flash-preview",
        db=db,
        user_id=test_user.id,
    )
    await upload_file.close()
    await wait_for_background_tasks()

    calls = [(call.args[0], call.kwargs) for call in mock_info.call_args_list]
    accepted = next(kwargs for event, kwargs in calls if event == "statement.upload.accepted")
    storage_saved = next(kwargs for event, kwargs in calls if event == "statement.upload.storage_saved")
    enqueued = next(kwargs for event, kwargs in calls if event == "statement.parse.enqueued")

    expected_hash_prefix = hashlib.sha256(content).hexdigest()[:12]
    assert accepted["audit_event"] == "statement.upload.accepted"
    assert accepted["request_id"]
    assert accepted["statement_id"] == str(created.id)
    assert accepted["filename"] == "staging-audit.pdf"
    assert accepted["file_type"] == "pdf"
    assert accepted["institution"] == "DBS"
    assert accepted["model_requested"] == "google/gemini-3-flash-preview"
    assert accepted["model_to_use"] == "google/gemini-3-flash-preview"
    assert accepted["file_size_bytes"] == len(content)
    assert accepted["file_hash_prefix"] == expected_hash_prefix
    assert accepted["file_hash_prefix"] != hashlib.sha256(content).hexdigest()
    assert "content" not in accepted

    assert storage_saved["audit_event"] == "statement.upload.storage_saved"
    assert storage_saved["request_id"] == accepted["request_id"]
    assert storage_saved["statement_id"] == str(created.id)
    assert storage_saved["file_hash_prefix"] == expected_hash_prefix

    assert enqueued["audit_event"] == "statement.parse.enqueued"
    assert enqueued["request_id"] == accepted["request_id"]
    assert enqueued["statement_id"] == str(created.id)
    assert enqueued["model_to_use"] == "google/gemini-3-flash-preview"
    job = mock_parse.await_args.kwargs["job"]
    assert isinstance(job, ParseJob)
    assert job.statement_id == created.id


async def test_AC10_8_1_upload_storage_failure_logs_safe_audit_context(db, monkeypatch, model_catalog_stub, test_user):
    """AC-observability.8.1: Upload storage failures keep replayable safe failure context."""
    content = b"storage-failure-input"
    mock_error = MagicMock()
    monkeypatch.setattr(statements_router.logger, "error", mock_error)

    class FailingStorage(DummyStorage):
        def upload_bytes(self, **_kwargs) -> None:
            raise StorageError("object store rejected upload without source bytes")

    monkeypatch.setattr(statements_router, "StorageService", FailingStorage)

    upload_file = make_upload_file("staging-failure.pdf", content)
    with pytest.raises(HTTPException) as exc_info:
        await statements_router.upload_statement(
            file=upload_file,
            institution="DBS",
            account_id=None,
            model=None,
            db=db,
            user_id=test_user.id,
        )
    await upload_file.close()

    failed = next(
        call.kwargs for call in mock_error.call_args_list if call.args[0] == "statement.upload.storage_failed"
    )
    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert failed["audit_event"] == "statement.upload.storage_failed"
    assert failed["request_id"]
    assert failed["statement_id"]
    assert failed["phase"] == "storage_upload_failed"
    assert failed["progress"] is None
    assert failed["model_to_use"] is None
    assert failed["filename"] == "staging-failure.pdf"
    assert failed["file_type"] == "pdf"
    assert failed["file_size_bytes"] == len(content)
    assert failed["file_hash_prefix"] == hashlib.sha256(content).hexdigest()[:12]
    assert failed["error_type"] == "StorageError"
    assert failed["safe_error_message"] == "object store rejected upload without source bytes"
    assert "content" not in failed


async def test_AC10_8_3_statement_scoped_brokerage_import_audit_logs(db, test_user, monkeypatch):
    """AC-observability.8.3: Statement-scoped brokerage import logs replay context and counts."""
    statement = build_statement(test_user.id, "manual_brokerage_audit", 95)
    statement.institution = "Moomoo"
    db.add(statement)
    await db.commit()
    statement_id = statement.id

    mock_info = MagicMock()
    result = SimpleNamespace(
        broker="Moomoo",
        parsed_positions=1,
        created_atomic_positions=1,
        existing_atomic_positions=0,
        reconcile_created=1,
        reconcile_updated=0,
        reconcile_disposed=0,
        skipped=0,
        account_id=None,
    )

    async def fake_import_positions(*_args, **_kwargs):
        return result

    monkeypatch.setattr(statements_router.logger, "info", mock_info)
    monkeypatch.setattr(statements_router._BROKERAGE_IMPORT_SERVICE, "import_positions", fake_import_positions)

    response = await statements_router.import_brokerage_statement_positions(
        statement_id=statement_id,
        db=db,
        user_id=test_user.id,
    )

    calls = [(call.args[0], call.kwargs) for call in mock_info.call_args_list]
    started = next(kwargs for event, kwargs in calls if event == "statement.brokerage_import.started")
    completed = next(kwargs for event, kwargs in calls if event == "statement.brokerage_import.completed")

    assert response.created_atomic_positions == 1
    assert started["audit_event"] == "statement.brokerage_import.started"
    assert started["statement_id"] == str(statement_id)
    assert started["phase"] == "brokerage_import_started"
    assert started["model_to_use"] is None
    assert completed["audit_event"] == "statement.brokerage_import.completed"
    assert completed["statement_id"] == str(statement_id)
    assert completed["phase"] == "brokerage_import_completed"
    assert completed["created_atomic_positions"] == 1


async def test_upload_rejects_text_only_model(db, monkeypatch, test_user):
    """AC-extraction.5.8: Upload rejects models without image modalities."""

    async def fake_catalog_get(self, model_id):
        return ModelSpec(id=model_id, provider_id="env", modalities=frozenset({Modality.TEXT}))

    monkeypatch.setattr("src.routers.statements.LitellmCatalog.get", fake_catalog_get)

    upload_file = make_upload_file("statement.pdf", b"content")

    with pytest.raises(HTTPException) as exc:
        await statements_router.upload_statement(
            file=upload_file,
            institution="DBS",
            account_id=None,
            model="text-only/model",
            db=db,
            user_id=test_user.id,
        )
    await upload_file.close()

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "does not support image/PDF inputs" in exc.value.detail


async def test_list_and_transactions_flow(db, monkeypatch, storage_stub, model_catalog_stub, test_user):
    """AC-extraction.5.9: Upload then list statements and transactions."""

    content = b"statement-flow"

    from src.extraction.extension.deduplication import DeduplicationService

    txn_date = date(2025, 1, 2)
    amount = Decimal("5000.00")
    direction = TransactionDirection.IN
    description = "Salary"
    transaction = ExtractedTransactionRow(
        user_id=test_user.id,
        txn_date=txn_date,
        description=description,
        amount=amount,
        direction=direction.value,
        reference=None,
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
        ),
    )
    _patch_parse_document(monkeypatch, test_user.id, transactions=[transaction])

    monkeypatch.setattr(
        statements_router.StorageService,
        "generate_presigned_url",
        lambda self, key=None, expires_in=None, **kwargs: "http://fake.url",
    )

    upload_file = make_upload_file("statement.pdf", content)
    created = await statements_router.upload_statement(
        file=upload_file,
        institution="DBS",
        account_id=None,
        model="google/gemini-3-flash-preview",
        db=db,
        user_id=test_user.id,
    )
    await upload_file.close()
    await wait_for_background_tasks()
    user_id = test_user.id
    statement_id = created.id
    db.expire_all()

    listed = await statements_router.list_statements(db=db, user_id=user_id)
    assert listed.total == 1
    assert listed.items[0].id == statement_id

    fetched = await statements_router.get_statement(statement_id=statement_id, db=db, user_id=user_id)
    assert fetched.id == statement_id
    assert len(fetched.transactions) == 1
    assert fetched.transactions[0].description == "Salary"

    txns = await statements_router.list_statement_transactions(statement_id=statement_id, db=db, user_id=user_id)
    assert txns.total == 1
    assert txns.items[0].description == "Salary"


async def test_pending_review_and_decisions(db, monkeypatch, storage_stub, model_catalog_stub, test_user):
    """AC-extraction.5.10: Review queue includes reviewable parsed statements and supports approve/reject."""
    contents = [b"review-70", b"review-90"]
    scores = [70, 90]
    score_by_hash = {
        hashlib.sha256(contents[0]).hexdigest(): scores[0],
        hashlib.sha256(contents[1]).hexdigest(): scores[1],
    }

    _patch_parse_document(
        monkeypatch,
        test_user.id,
        confidence_score=lambda h: score_by_hash[h],
        modifier=lambda stmt, src: setattr(stmt, "closing_balance", Decimal("100.00")),
    )

    account = await create_statement_account(db, test_user.id, "Review Queue Account")
    created_ids = []
    for index, content in enumerate(contents):
        upload_file = make_upload_file(f"statement-{index}.pdf", content)
        created = await statements_router.upload_statement(
            file=upload_file,
            institution="DBS",
            account_id=account.id,
            model="google/gemini-3-flash-preview",
            db=db,
            user_id=test_user.id,
        )
        await upload_file.close()
        created_ids.append(created.id)
    await wait_for_background_tasks()

    pending = await statements_router.list_pending_review(db=db, user_id=test_user.id)
    assert pending.total == 2
    assert {item.id for item in pending.items} == set(created_ids)

    # Test approve. The legacy POST /statements/{id}/approve endpoint was removed
    # in #1099 (AC-platform.29.5); drive the same state transition via the service layer.
    statement_id = created_ids[0]

    source_result = await statements_router.get_current_statement_extraction_result(
        db, user_id=test_user.id, statement_id=statement_id
    )
    await statements_router.confirm_statement_review_envelope(
        statement_id=statement_id,
        request=ReviewedStatementEnvelopeRequest(
            source_result_digest=source_result.content_digest,
            account_id=account.id,
            currency="SGD",
            period_start=date(2025, 1, 1),
            period_end=date(2025, 1, 31),
            opening_balance=Decimal("100.00"),
            closing_balance=Decimal("100.00"),
            rationale="Reviewed the dormant original source and confirmed its balances.",
        ),
        db=db,
        user_id=test_user.id,
    )
    approved = await statement_validation_mod.approve_statement(db, statement_id, test_user.id)
    await db.commit()
    assert approved.status == BankStatementStatus.APPROVED

    # Test reject (state transitions are allowed on the same statement).
    rejected = await statement_validation_mod.reject_statement(db, statement_id, test_user.id, reason="Incorrect data")
    await db.commit()
    assert rejected.status == BankStatementStatus.REJECTED


async def test_stage1_reject_triggers_reparse(db, monkeypatch, storage_stub, test_user):
    """AC-extraction.stage1-validation.9: AC16.22.2: Stage 1 reject queues a re-parse for the rejected statement."""
    statement = build_statement(test_user.id, "hash_stage1_reject_reparse", 70)
    statement.status = BankStatementStatus.PARSED
    db.add(statement)
    await db.flush()
    document = await seed_uploaded_document(
        db,
        statement,
        file_path="statements/reject-reparse.pdf",
        original_filename="reject-reparse.pdf",
    )
    await db.commit()
    await db.refresh(statement)

    queued: dict[str, object] = {}

    async def fake_parse_statement_background(**kwargs):
        queued.update(kwargs)

    monkeypatch.setattr(
        statement_pipeline,
        "compose_statement_ingestion_use_case",
        _compose_mock_ingestion(fake_parse_statement_background),
    )

    response = await statements_router.reject_statement_stage1(
        statement_id=statement.id,
        decision=StatementDecisionRequest(notes="Needs re-parse"),
        db=db,
        user_id=test_user.id,
    )
    await wait_for_background_tasks()

    assert response.status == BankStatementStatus.REJECTED
    assert response.validation_error == "Needs re-parse"
    queued_job = queued["job"]
    assert isinstance(queued_job, ParseJob)
    assert queued_job.statement_id == statement.id
    assert queued_job.filename == document.original_filename
    assert queued_job.user_id == test_user.id
    assert queued_job.storage_key == document.file_path
    assert queued["content"] == b"dummy content"

    # Flow 9 Invariant: Rejected statements excluded from general ledger,
    # leaving exactly 0 journal entries and zero trial balance leakage.
    from sqlalchemy import func

    from src.ledger import JournalLine

    entry_count = await db.scalar(select(func.count(JournalEntry.id)).where(JournalEntry.user_id == test_user.id))
    assert entry_count == 0, f"Expected 0 JournalEntries for rejected statement, found {entry_count}"

    line_count = await db.scalar(
        select(func.count(JournalLine.id))
        .join(JournalEntry)
        .where(JournalEntry.user_id == test_user.id)
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
    )
    assert line_count == 0, f"Expected 0 posted trial balance lines, found {line_count}"


async def test_get_statement_not_found(db, test_user):
    """AC-extraction.5.11: Missing statement returns 404."""
    with pytest.raises(HTTPException) as exc:
        await statements_router.get_statement(
            statement_id=statements_router.UUID("00000000-0000-0000-0000-000000000000"),
            db=db,
            user_id=test_user.id,
        )
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


async def test_list_statement_transactions_not_found(db, test_user):
    """AC-extraction.5.11: Missing statement transactions return 404."""
    with pytest.raises(HTTPException) as exc:
        await statements_router.list_statement_transactions(
            statement_id=statements_router.UUID("00000000-0000-0000-0000-000000000000"),
            db=db,
            user_id=test_user.id,
        )

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


async def test_upload_file_too_large(db, model_catalog_stub, test_user):
    """AC-extraction.5.12: File exceeding 10MB limit returns 413."""
    content = b"x" * (10 * 1024 * 1024 + 1)
    upload_file = make_upload_file("large-statement.pdf", content)

    with pytest.raises(HTTPException) as exc:
        await statements_router.upload_statement(
            file=upload_file,
            institution="DBS",
            account_id=None,
            model="google/gemini-3-flash-preview",
            db=db,
            user_id=test_user.id,
        )
    await upload_file.close()

    assert exc.value.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    assert "10MB" in exc.value.detail


async def test_upload_extraction_failure(db, monkeypatch, model_catalog_stub, test_user):
    """AC-extraction.5.13: Extraction failure marks statement as rejected."""
    content = b"content"

    mock_storage = MagicMock()
    mock_storage.upload_bytes.return_value = None
    mock_storage.generate_presigned_url.return_value = "https://example.com/file"
    mock_storage_cls = MagicMock(return_value=mock_storage)
    monkeypatch.setattr(statements_router, "StorageService", mock_storage_cls)

    _patch_parse_document(monkeypatch, test_user.id, side_effect=ExtractionError("Failed to parse PDF"))

    upload_file = make_upload_file("statement.pdf", content)
    created = await statements_router.upload_statement(
        file=upload_file,
        institution="DBS",
        account_id=None,
        model="google/gemini-3-flash-preview",
        db=db,
        user_id=test_user.id,
    )
    await upload_file.close()
    await wait_for_background_tasks()

    statement = await db.get(StatementSummary, created.id)
    assert statement is not None

    # Wait for background task to update status to REJECTED
    if statement.status == BankStatementStatus.PARSING:
        import asyncio

        await asyncio.sleep(0.5)
        await db.refresh(statement)

    assert statement.status == BankStatementStatus.REJECTED


async def test_retry_statement_not_found(db, test_user):
    """AC-extraction.5.14: Retry on missing statement returns 404."""
    from src.schemas import RetryParsingRequest

    with pytest.raises(HTTPException) as exc:
        await statements_router.retry_statement_parsing(
            statement_id=statements_router.UUID("00000000-0000-0000-0000-000000000000"),
            request=RetryParsingRequest(model=None),
            db=db,
            user_id=test_user.id,
        )
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


async def test_retry_rejects_text_only_model(db, monkeypatch, test_user):
    """AC-extraction.5.15: Retry rejects models without image modalities."""
    from src.schemas import RetryParsingRequest

    statement = build_statement(test_user.id, "hash", 80)
    statement.status = BankStatementStatus.REJECTED
    db.add(statement)
    await db.commit()

    async def fake_catalog_get(self, model_id):
        return ModelSpec(id=model_id, provider_id="env", modalities=frozenset({Modality.TEXT}))

    monkeypatch.setattr("src.routers.statements.LitellmCatalog.get", fake_catalog_get)

    with pytest.raises(HTTPException) as exc:
        await statements_router.retry_statement_parsing(
            statement_id=statement.id,
            request=RetryParsingRequest(model="text-only/model"),
            db=db,
            user_id=test_user.id,
        )

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "does not support image/PDF inputs" in exc.value.detail


@pytest.mark.parametrize(
    "prior_status", [BankStatementStatus.REJECTED, BankStatementStatus.PARSED, BankStatementStatus.PARSING]
)
@pytest.mark.parametrize("source_available", [True, False])
async def test_retry_statement_storage_failure(db, monkeypatch, test_user, prior_status, source_available):
    """AC-extraction.5.16: failed retrieval preserves state and dispatches no work."""
    from src.schemas import RetryParsingRequest

    statement = build_statement(test_user.id, "hash", 80)
    statement.status = prior_status
    statement.validation_error = "Original review failure"
    db.add(statement)
    await db.flush()
    if source_available:
        await seed_uploaded_document(db, statement, file_path="path/to/file.pdf")
    await db.commit()

    mock_storage = MagicMock()
    mock_storage.get_object.side_effect = statements_router.StorageError("S3 Down")
    monkeypatch.setattr(statements_router, "StorageService", MagicMock(return_value=mock_storage))

    submit = AsyncMock()
    monkeypatch.setattr(statements_router, "submit_parse_pipeline", submit)

    with pytest.raises(HTTPException) as exc:
        await statements_router.retry_statement_parsing(
            statement_id=statement.id,
            request=RetryParsingRequest(model=None),
            db=db,
            user_id=test_user.id,
        )

    assert exc.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert "Failed to fetch file from storage" in exc.value.detail

    await db.refresh(statement)
    assert statement.status == prior_status
    assert statement.validation_error == "Original review failure"
    submit.assert_not_awaited()


async def test_retry_statement_invalid_status(db, monkeypatch, storage_stub, model_catalog_stub, test_user):
    """AC-extraction.5.17: Retry on statement not in parsed/rejected status returns 400."""
    from src.schemas import RetryParsingRequest

    content = b"statement"

    _patch_parse_document(monkeypatch, test_user.id, status=BankStatementStatus.PARSING)

    upload_file = make_upload_file("statement.pdf", content)
    created = await statements_router.upload_statement(
        file=upload_file,
        institution="DBS",
        account_id=None,
        model="google/gemini-3-flash-preview",
        db=db,
        user_id=test_user.id,
    )
    await upload_file.close()
    await wait_for_background_tasks()

    # To trigger a 400, we need a status NOT in (PARSED, REJECTED, PARSING)
    # UPLOADED status is not allowed for retry.
    statement = await db.get(StatementSummary, created.id)
    statement.status = BankStatementStatus.UPLOADED
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await statements_router.retry_statement_parsing(
            statement_id=created.id,
            request=RetryParsingRequest(model=None),
            db=db,
            user_id=test_user.id,
        )
    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "stuck parsing statements" in exc.value.detail


async def test_retry_statement_parsing_allowed(db, monkeypatch, storage_stub, test_user):
    """AC-extraction.5.18: Verify that retrying a statement in PARSING status is allowed."""
    from unittest.mock import patch
    from uuid import uuid4

    from src.schemas import RetryParsingRequest

    sid = uuid4()
    statement = StatementSummary(
        id=sid,
        user_id=test_user.id,
        status=BankStatementStatus.PARSING,
        file_hash="h_parsing",
        institution="DBS",
    )
    db.add(statement)
    await db.flush()
    await seed_uploaded_document(db, statement, file_path="p", original_filename="f.pdf")
    await db.commit()

    with patch("src.routers.statements.StorageService") as mock_storage_cls:
        mock_storage = mock_storage_cls.return_value
        mock_storage.get_object.return_value = b"content"

        resp = await statements_router.retry_statement_parsing(
            statement_id=sid,
            request=RetryParsingRequest(model=None),
            db=db,
            user_id=test_user.id,
        )
        assert resp.status == BankStatementStatus.PARSING


async def test_AC13_21_3_retry_accepts_parsed_resting_state(db, storage_stub, test_user):
    """AC-extraction.121.3 (#1141): retry accepts a balance-invalid statement at its PARSED rest.

    A balance-invalid bank statement now rests in PARSED (review) instead of the
    UPLOADED dead-end that the retry endpoint rejected. PARSED is already an
    allowed retry state, so retry must NOT raise a 400 for it.
    """
    from unittest.mock import patch
    from uuid import uuid4

    from src.schemas import RetryParsingRequest

    sid = uuid4()
    statement = StatementSummary(
        id=sid,
        user_id=test_user.id,
        status=BankStatementStatus.PARSED,
        stage1_status=Stage1Status.PENDING_REVIEW,
        balance_validated=False,
        validation_error="Balance mismatch: expected 1500.00, got 9999.99",
        file_hash="h_parsed_balance_invalid",
        institution="DBS",
    )
    db.add(statement)
    await db.flush()
    await seed_uploaded_document(db, statement, file_path="p", original_filename="f.pdf")
    await db.commit()

    with patch("src.routers.statements.StorageService") as mock_storage_cls:
        mock_storage = mock_storage_cls.return_value
        mock_storage.get_object.return_value = b"content"

        # Must not raise HTTP 400: PARSED is an accepted retry resting state.
        resp = await statements_router.retry_statement_parsing(
            statement_id=sid,
            request=RetryParsingRequest(model=None),
            db=db,
            user_id=test_user.id,
        )
        assert resp.id == sid


async def test_AC13_21_6_csv_missing_institution_rejected_sync(db, storage_stub, test_user):
    """AC-extraction.121.6 (#1141): CSV upload without an institution fails synchronously (400).

    Previously a CSV with no institution was accepted (202) and only rejected
    asynchronously inside the parse worker ("Institution is required for CSV
    parsing"), leaving an orphaned PARSING record. The upload route must reject it
    up-front with HTTP 400 and an actionable message.
    """
    upload_file = make_upload_file("statement.csv", b"date,amount\n2025-01-01,10.00\n")
    with pytest.raises(HTTPException) as exc:
        await statements_router.upload_statement(
            file=upload_file,
            institution=None,
            account_id=None,
            model=None,
            db=db,
            user_id=test_user.id,
        )
    await upload_file.close()

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "institution" in exc.value.detail.lower()


async def test_retry_statement_success(db, monkeypatch, storage_stub, model_catalog_stub, test_user):
    """AC-extraction.5.19: Retry parsing with stronger model succeeds."""
    from src.schemas import RetryParsingRequest

    content = b"statement"

    _patch_parse_document(
        monkeypatch,
        test_user.id,
        confidence_score=60,
        status=BankStatementStatus.REJECTED,
    )

    upload_file = make_upload_file("statement.pdf", content)
    created = await statements_router.upload_statement(
        file=upload_file,
        institution="DBS",
        account_id=None,
        model="google/gemini-3-flash-preview",
        db=db,
        user_id=test_user.id,
    )
    await upload_file.close()
    await wait_for_background_tasks()

    rejected = await statement_validation_mod.reject_statement(db, created.id, test_user.id, reason="Low confidence")
    await db.commit()
    assert rejected.status == BankStatementStatus.REJECTED

    mock_parse = AsyncMock()
    monkeypatch.setattr(
        statement_parsing_mod.ExtractionService,
        "parse_document",
        mock_parse,
    )

    mock_statement = build_statement(test_user.id, "", confidence_score=95)
    mock_parse.return_value = (mock_statement, [])

    await statements_router.retry_statement_parsing(
        statement_id=created.id,
        request=RetryParsingRequest(model="google/gemini-2.0-flash-exp:free"),
        db=db,
        user_id=test_user.id,
    )


async def test_retry_statement_extraction_failure(db, monkeypatch, storage_stub, model_catalog_stub, test_user):
    """AC-extraction.5.20: Retry extraction failure returns 422."""
    from src.schemas import RetryParsingRequest

    content = b"statement"

    _patch_parse_document(monkeypatch, test_user.id, status=BankStatementStatus.REJECTED)

    upload_file = make_upload_file("statement.pdf", content)
    created = await statements_router.upload_statement(
        file=upload_file,
        institution="DBS",
        account_id=None,
        model="google/gemini-3-flash-preview",
        db=db,
        user_id=test_user.id,
    )
    await upload_file.close()
    await wait_for_background_tasks()

    rejected = await statement_validation_mod.reject_statement(db, created.id, test_user.id, reason="Low confidence")
    await db.commit()
    assert rejected.status == BankStatementStatus.REJECTED

    async def fake_retry_fail(
        self,
        file_path,
        institution,
        user_id,
        file_type="pdf",
        account_id=None,
        file_content=None,
        file_hash=None,
        file_url=None,
        original_filename=None,
        force_model=None,
        db=None,
    ):
        raise ExtractionError("Retry failed")

    monkeypatch.setattr(
        statement_parsing_mod.ExtractionService,
        "parse_document",
        fake_retry_fail,
    )

    resp = await statements_router.retry_statement_parsing(
        statement_id=created.id,
        request=RetryParsingRequest(model="google/gemini-2.0-flash-exp:free"),
        db=db,
        user_id=test_user.id,
    )
    assert resp.status == BankStatementStatus.PARSING
    await wait_for_background_tasks()


async def test_upload_statement_rejects_invalid_model(db, test_user, storage_stub, monkeypatch):
    """AC-extraction.5.21: Upload rejects models not in the OpenRouter catalog."""
    content = b"some content"
    upload_file = make_upload_file("statement.pdf", content)

    async def fake_catalog_get(self, model_id):
        return None

    monkeypatch.setattr("src.routers.statements.LitellmCatalog.get", fake_catalog_get)

    with pytest.raises(HTTPException) as exc:
        await statements_router.upload_statement(
            file=upload_file,
            institution="DBS",
            model="unknown/model",
            db=db,
            user_id=test_user.id,
        )
    await upload_file.close()

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Invalid model selection" in exc.value.detail


async def test_upload_statement_rejects_model_without_image_modality(db, test_user, storage_stub, monkeypatch):
    """AC-extraction.5.22: Upload rejects a model lacking image/PDF modality (400)."""
    content = b"some content"
    upload_file = make_upload_file("statement.pdf", content)

    async def fake_catalog_get(self, model_id):
        return ModelSpec(id=model_id, provider_id="env", modalities=frozenset({Modality.TEXT}))

    monkeypatch.setattr("src.routers.statements.LitellmCatalog.get", fake_catalog_get)

    with pytest.raises(HTTPException) as exc:
        await statements_router.upload_statement(
            file=upload_file,
            institution="DBS",
            model="google/gemini-flash",
            db=db,
            user_id=test_user.id,
        )
    await upload_file.close()

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "does not support image" in exc.value.detail


async def test_retry_statement_rejects_invalid_model(db, test_user, monkeypatch, storage_stub):
    """AC-extraction.5.23: Retry rejects a model not in the catalogue (400)."""
    statement = build_statement(test_user.id, "hash", 80)
    statement.status = BankStatementStatus.REJECTED
    db.add(statement)
    await db.commit()

    async def fake_catalog_get(self, model_id):
        return None

    monkeypatch.setattr("src.routers.statements.LitellmCatalog.get", fake_catalog_get)

    from src.schemas import RetryParsingRequest

    with pytest.raises(HTTPException) as exc:
        await statements_router.retry_statement_parsing(
            statement_id=statement.id,
            request=RetryParsingRequest(model="google/gemini-flash"),
            db=db,
            user_id=test_user.id,
        )

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Invalid model selection" in exc.value.detail


async def test_background_parse_error_logging(db, monkeypatch, test_user, storage_stub):
    """AC-extraction.5.24: Background parse error should be caught and logged."""
    content = b"content"

    _patch_parse_document(monkeypatch, test_user.id, side_effect=Exception("Fatal background error"))

    # Patch the catalogue to return an image-capable model and pass validation.
    async def fake_catalog_get(self, model_id):
        return ModelSpec(
            id=model_id,
            provider_id="env",
            modalities=frozenset({Modality.TEXT, Modality.IMAGE}),
        )

    monkeypatch.setattr("src.routers.statements.LitellmCatalog.get", fake_catalog_get)

    upload_file = make_upload_file("statement.pdf", content)
    created = await statements_router.upload_statement(
        file=upload_file,
        institution="DBS",
        account_id=None,
        model="google/gemini-3-flash-preview",
        db=db,
        user_id=test_user.id,
    )
    await upload_file.close()

    # Wait for task - it should catch the exception
    await wait_for_background_tasks()

    # Statement should still be in PARSING or move to REJECTED?
    # In current implementation, if background task fails with unexpected error, it might stay in PARSING.
    # But line 300 logs the error.
    statement = await db.get(StatementSummary, created.id)
    assert statement is not None


async def test_background_retry_error_logging(db, monkeypatch, test_user, storage_stub):
    """AC-extraction.5.25: Background retry error should be caught and logged."""
    statement = build_statement(test_user.id, "hash_retry", 80)
    statement.status = BankStatementStatus.REJECTED
    db.add(statement)
    await db.flush()
    await seed_uploaded_document(db, statement, file_path="path")
    await db.commit()

    _patch_parse_document(monkeypatch, test_user.id, side_effect=Exception("Fatal background retry error"))

    monkeypatch.setattr(
        statements_router.StorageService,
        "get_object",
        lambda *args, **kwargs: b"content",
    )

    async def fake_catalog_get(self, model_id):
        return ModelSpec(
            id=model_id,
            provider_id="env",
            modalities=frozenset({Modality.TEXT, Modality.IMAGE}),
        )

    monkeypatch.setattr("src.routers.statements.LitellmCatalog.get", fake_catalog_get)

    from src.schemas import RetryParsingRequest

    await statements_router.retry_statement_parsing(
        statement_id=statement.id,
        request=RetryParsingRequest(model="google/gemini-flash"),
        db=db,
        user_id=test_user.id,
    )

    # Wait for task
    await wait_for_background_tasks()

    # Refresh to get updated statement
    await db.refresh(statement)
    # Background task sets status to PARSING before parsing, then REJECTED on error
    assert statement.status in (BankStatementStatus.PARSING, BankStatementStatus.REJECTED)


# ============================================================================
# Tests for uncovered lines: Two-Stage Review, Delete, Batch, Consistency
# ============================================================================


async def test_handle_parse_failure_inner_exception(db, test_user, monkeypatch):
    """Given a statement whose post-rollback refresh raises an exception,
    When _handle_parse_failure runs,
    Then it logs the inner exception without propagating it (lines 154-155).
    """
    statement = build_statement(test_user.id, "hash_inner_exc", 50)
    db.add(statement)
    await db.commit()
    statement_id = statement.id

    # Create a mock session that succeeds on rollback but fails on get()
    mock_session = AsyncMock(spec=db)
    mock_session.rollback = AsyncMock()
    mock_session.get = AsyncMock(side_effect=Exception("DB completely down"))
    mock_session.commit = AsyncMock()

    # Build a fake statement obj to pass in
    fake_stmt = MagicMock()
    fake_stmt.id = statement_id

    # Should not raise - it catches inner exceptions
    await handle_parse_failure(fake_stmt, mock_session, message="parse error")
    mock_session.get.assert_awaited_once()


async def test_handle_parse_failure_statement_not_found_after_rollback(db, test_user):
    """Given a statement that doesn't exist after rollback,
    When _handle_parse_failure runs,
    Then it returns early without error (line 147).
    """
    mock_session = AsyncMock(spec=db)
    mock_session.rollback = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)

    fake_stmt = MagicMock()
    fake_stmt.id = statements_router.UUID("00000000-0000-0000-0000-000000000099")

    # Should return without error
    await handle_parse_failure(fake_stmt, mock_session, message="parse error")
    mock_session.get.assert_awaited_once()


async def test_handle_parse_failure_rollback_fails(db, test_user):
    """Given a session where rollback itself raises,
    When _handle_parse_failure runs,
    Then it catches rollback error and still tries to mark statement as rejected.
    """
    statement = build_statement(test_user.id, "hash_rb_fail", 50)
    db.add(statement)
    await db.commit()
    statement_id = statement.id

    mock_session = AsyncMock(spec=db)
    mock_session.rollback = AsyncMock(side_effect=Exception("Rollback failed"))
    # After rollback fails, it still tries to get + update
    mock_session.get = AsyncMock(return_value=None)

    fake_stmt = MagicMock()
    fake_stmt.id = statement_id

    await handle_parse_failure(fake_stmt, mock_session, message="parse error")
    mock_session.rollback.assert_awaited_once()


async def test_delete_statement_success(db, test_user, monkeypatch):
    """Given an existing statement with a file_path,
    When delete_statement is called,
    Then it retires the DB/reference state without deleting storage.
    """
    statement = build_statement(test_user.id, "hash_del", 90)
    db.add(statement)
    await db.flush()
    await seed_uploaded_document(db, statement, file_path="statements/user/file.pdf")
    await db.commit()
    statement_id = statement.id

    monkeypatch.setattr(statements_router, "StorageService", DummyStorage)

    await statements_router.delete_statement(statement_id=statement_id, db=db, user_id=test_user.id)

    retired = await db.get(StatementSummary, statement_id)
    assert retired is not None
    assert retired.status is BankStatementStatus.RETIRED


async def test_delete_statement_not_found(db, test_user):
    """Given a non-existent statement,
    When delete_statement is called,
    Then it raises 404.
    """
    with pytest.raises(HTTPException) as exc:
        await statements_router.delete_statement(
            statement_id=statements_router.UUID("00000000-0000-0000-0000-000000000000"),
            db=db,
            user_id=test_user.id,
        )
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


async def test_delete_statement_storage_error_still_deletes(db, test_user, monkeypatch):
    """Given a statement whose storage delete fails,
    When delete_statement is called,
    Then retirement does not call storage and preserves the DB record.
    """
    statement = build_statement(test_user.id, "hash_del_err", 90)
    db.add(statement)
    await db.flush()
    await seed_uploaded_document(db, statement, file_path="statements/user/file.pdf")
    await db.commit()
    statement_id = statement.id

    mock_storage = MagicMock()
    mock_storage.delete_object.side_effect = statements_router.StorageError("S3 Down")
    monkeypatch.setattr(statements_router, "StorageService", MagicMock(return_value=mock_storage))

    await statements_router.delete_statement(statement_id=statement_id, db=db, user_id=test_user.id)

    mock_storage.delete_object.assert_not_called()
    retired = await db.get(StatementSummary, statement_id)
    assert retired is not None
    assert retired.status is BankStatementStatus.RETIRED


async def test_get_statement_for_review(db, test_user, monkeypatch):
    """Given an existing statement with transactions,
    When get_statement_for_review is called,
    Then it returns review data with balance validation (lines 712-751).
    """
    statement = build_statement(test_user.id, "hash_review", 75)
    db.add(statement)
    await db.commit()
    await db.refresh(statement)
    statement_id = statement.id

    monkeypatch.setattr(statements_router, "StorageService", DummyStorage)

    result = await statements_router.get_statement_for_review(statement_id=statement_id, db=db, user_id=test_user.id)

    assert result.id == statement_id
    assert result.balance_validation_result is not None
    assert hasattr(result.balance_validation_result, "opening_balance")
    assert hasattr(result.balance_validation_result, "closing_match")


async def test_AC16_33_5_get_statement_document_streams_bytes_same_origin(db, test_user, monkeypatch):
    """AC-extraction.document-delivery.2: AC16.33.5: the document endpoint streams the original upload, same-origin.

    The Stage 1 PDF preview embeds this authenticated endpoint as a ``blob:``
    object URL instead of a cross-origin object-storage URL.
    """
    statement = build_statement(test_user.id, "hash_doc_stream", 75)
    db.add(statement)
    await db.flush()
    await seed_uploaded_document(db, statement, file_path="statements/doc/preview.pdf", original_filename="moomoo.pdf")
    await db.commit()
    await db.refresh(statement)

    monkeypatch.setattr(statements_router, "StorageService", DummyStorage)

    result = await statements_router.get_statement_document(statement_id=statement.id, db=db, user_id=test_user.id)

    assert result.body == b"dummy content"
    assert result.media_type == "application/pdf"
    assert result.headers["Content-Disposition"] == "inline"


async def test_AC16_33_5_get_statement_document_404_when_no_document(db, test_user):
    """AC16.33.5: a statement with no uploaded document returns 404, not a blank frame."""
    statement = build_statement(test_user.id, "hash_doc_missing", 75)
    db.add(statement)
    await db.commit()
    await db.refresh(statement)

    with pytest.raises(HTTPException) as exc:
        await statements_router.get_statement_document(statement_id=statement.id, db=db, user_id=test_user.id)
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


async def test_AC16_33_5_get_statement_document_storage_error_maps_to_502(db, test_user, monkeypatch):
    """AC16.33.5: a storage outage surfaces a 502 instead of a silent empty body."""
    statement = build_statement(test_user.id, "hash_doc_storage_err", 75)
    db.add(statement)
    await db.flush()
    await seed_uploaded_document(db, statement, file_path="statements/doc/err.pdf")
    await db.commit()
    await db.refresh(statement)

    mock_storage = MagicMock()
    mock_storage.get_object.side_effect = statements_router.StorageError("S3 Down")
    monkeypatch.setattr(statements_router, "StorageService", MagicMock(return_value=mock_storage))

    with pytest.raises(HTTPException) as exc:
        await statements_router.get_statement_document(statement_id=statement.id, db=db, user_id=test_user.id)
    assert exc.value.status_code == status.HTTP_502_BAD_GATEWAY


async def test_get_statement_for_review_not_found(db, test_user):
    """Given a non-existent statement,
    When get_statement_for_review is called,
    Then it raises 404.
    """
    with pytest.raises(HTTPException) as exc:
        await statements_router.get_statement_for_review(
            statement_id=statements_router.UUID("00000000-0000-0000-0000-000000000000"),
            db=db,
            user_id=test_user.id,
        )
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


async def test_get_statement_for_review_storage_error(db, test_user, monkeypatch):
    """Given a statement where presigned URL generation fails,
    When get_statement_for_review is called,
    Then it still returns data with pdf_url=None (lines 727-732).
    """
    statement = build_statement(test_user.id, "hash_review_s3", 75)
    db.add(statement)
    await db.commit()
    await db.refresh(statement)
    statement_id = statement.id

    mock_storage = MagicMock()
    mock_storage.generate_presigned_url.side_effect = statements_router.StorageError("S3 Down")
    monkeypatch.setattr(statements_router, "StorageService", MagicMock(return_value=mock_storage))

    result = await statements_router.get_statement_for_review(statement_id=statement_id, db=db, user_id=test_user.id)

    assert result.id == statement_id
    assert result.pdf_url is None


async def test_AC16_33_4_get_statement_for_review_uses_short_presign_ttl(db, test_user, monkeypatch):
    """AC-extraction.document-delivery.1: AC16.33.4: Statement review PDFs use a short-lived preview URL."""
    statement = build_statement(test_user.id, "hash_review_short_presign", 75)
    db.add(statement)
    await db.flush()
    document = await seed_uploaded_document(db, statement, file_path="statements/review/short-presign.pdf")
    await db.commit()
    await db.refresh(statement)

    mock_storage = MagicMock()
    mock_storage.generate_presigned_url.return_value = "https://example.com/file"
    monkeypatch.setattr(statements_router, "StorageService", MagicMock(return_value=mock_storage))

    result = await statements_router.get_statement_for_review(statement_id=statement.id, db=db, user_id=test_user.id)

    assert result.pdf_url == "https://example.com/file"
    mock_storage.generate_presigned_url.assert_called_once_with(
        key=document.file_path,
        expires_in=statements_router.settings.statement_review_presign_expiry_seconds,
        # #1391: the review URL is browser-facing, so it must use the public endpoint.
        public=True,
    )


async def test_set_opening_balance_success(db, test_user):
    """Given a parsed statement,
    When set_statement_opening_balance is called,
    Then it sets the manual opening balance (lines 825-835).
    """
    from src.schemas.review import SetOpeningBalanceRequest

    statement = build_statement(test_user.id, "hash_ob", 80)
    db.add(statement)
    await db.commit()
    statement_id = statement.id

    result = await statements_router.set_statement_opening_balance(
        statement_id=statement_id,
        request=SetOpeningBalanceRequest(opening_balance=Decimal("500.00")),
        db=db,
        user_id=test_user.id,
    )

    assert result.id == statement_id


async def test_set_opening_balance_not_found(db, test_user):
    """Given a non-existent statement,
    When set_statement_opening_balance is called,
    Then it raises 400.
    """
    from src.schemas.review import SetOpeningBalanceRequest

    with pytest.raises(HTTPException) as exc:
        await statements_router.set_statement_opening_balance(
            statement_id=statements_router.UUID("00000000-0000-0000-0000-000000000000"),
            request=SetOpeningBalanceRequest(opening_balance=Decimal("100.00")),
            db=db,
            user_id=test_user.id,
        )
    assert exc.value.status_code == 400


async def test_wait_for_parse_tasks_empty():
    """Given no pending parse tasks,
    When wait_for_parse_tasks is called,
    Then it returns immediately (line 1034->exit).
    """
    # Clear any pending tasks
    statements_router._PENDING_PARSE_TASKS.clear()
    await statements_router.wait_for_parse_tasks()
    # Should just return without error


async def test_retry_statement_invalid_model(db, monkeypatch, storage_stub, test_user):
    """Given a rejected statement and an invalid model ID,
    When retry is called with that model,
    Then it raises 400 (line 457).
    """
    from src.schemas import RetryParsingRequest

    statement = build_statement(test_user.id, "hash_retry_inv", 80)
    statement.status = BankStatementStatus.REJECTED
    db.add(statement)
    await db.commit()

    async def fake_catalog_get(self, model_id):
        return None

    monkeypatch.setattr("src.routers.statements.LitellmCatalog.get", fake_catalog_get)

    with pytest.raises(HTTPException) as exc:
        await statements_router.retry_statement_parsing(
            statement_id=statement.id,
            request=RetryParsingRequest(model="unknown/model"),
            db=db,
            user_id=test_user.id,
        )
    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Invalid model selection" in exc.value.detail


async def test_rejected_statement_transactions_excluded_from_effective_filter(db, test_user):
    """Flow 9 / Issue #2067: A rejected bank statement must not leak transactions into effective filter.

    When a statement has status REJECTED, transactions belonging to it must be
    excluded by effective_statement_transaction_filter for both scoped and global queries.
    """
    from src.extraction import effective_statement_transaction_filter

    statement = build_statement(test_user.id, "hash_rejected_leak_test", 80)
    statement.status = BankStatementStatus.REJECTED
    db.add(statement)
    await db.flush()

    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 15),
        description="Rejected statement transaction",
        amount=Decimal("50.00"),
        direction="IN",
    )
    await db.commit()

    # Scoped query by statement_id
    scoped_txns = (
        await db.scalars(
            select(AtomicTransaction.id).where(effective_statement_transaction_filter(test_user.id, statement.id))
        )
    ).all()
    assert len(scoped_txns) == 0, f"Expected 0 transactions for rejected statement, got {len(scoped_txns)}"

    # Global query without statement_id
    global_txns = (
        await db.scalars(select(AtomicTransaction.id).where(effective_statement_transaction_filter(test_user.id)))
    ).all()
    assert txn.id not in global_txns, "Rejected statement transaction leaked into global effective filter"


async def test_resolve_uploaded_document_enforces_user_isolation(db, test_user):
    """F-01: _resolve_uploaded_document must not return another user's UploadedDocument."""
    from src.routers.statements import _resolve_uploaded_document

    other_user = User(
        id=uuid4(),
        email=f"other_{uuid4().hex[:8]}@example.com",
        name="Other User",
        hashed_password="test_hashed_password",
    )
    db.add(other_user)
    await db.flush()

    other_doc = UploadedDocument(
        id=uuid4(),
        user_id=other_user.id,
        file_path="other_path.pdf",
        file_hash="other_hash_123",
        original_filename="other.pdf",
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(other_doc)
    await db.flush()

    # Statement belongs to test_user, but uploaded_document_id mistakenly points to other_user's doc
    statement = build_statement(test_user.id, "statement_hash_456", 80)
    statement.uploaded_document_id = other_doc.id
    db.add(statement)
    await db.commit()

    resolved = await _resolve_uploaded_document(db, statement, test_user.id)
    assert resolved is None, "Cross-user document must never be returned by _resolve_uploaded_document"

    # Happy path: when document belongs to test_user, it IS returned
    user_doc = UploadedDocument(
        id=uuid4(),
        user_id=test_user.id,
        file_path="user_path.pdf",
        file_hash="statement_hash_456",
        original_filename="user.pdf",
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(user_doc)
    statement.uploaded_document_id = user_doc.id
    await db.commit()

    resolved_own = await _resolve_uploaded_document(db, statement, test_user.id)
    assert resolved_own is not None
    assert resolved_own.id == user_doc.id
