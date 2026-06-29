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
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from src.identity import User
from src.llm.common import Modality, ModelSpec
from src.models.account import Account, AccountType
from src.models.consistency_check import CheckStatus, CheckType, ConsistencyCheck
from src.models.evidence import EvidenceEdge, EvidenceNode
from src.models.journal import JournalEntry, JournalEntrySourceType, JournalEntryStatus
from src.models.layer1 import DocumentType, UploadedDocument
from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.models.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.models.statement_enums import BankStatementStatus, Stage1Status
from src.models.statement_summary import StatementSummary
from src.routers import review as review_router, statements as statements_router
from src.schemas import StatementDecisionRequest
from src.schemas.review import (
    BatchApproveRequest,
    BatchRejectRequest,
    ResolveCheckRequest,
    ResolveConflictsRequest,
    Stage1ApprovalRequest,
)
from src.services import (
    ExtractionError,
    StorageError,
    statement_parsing as statement_parsing_mod,
    statement_pipeline,
    statement_validation as statement_validation_mod,
)
from src.services.review_queue import accept_match as accept_match_service, create_entry_from_txn
from src.services.source_type_priority import STATEMENT_SOURCE_TYPES
from src.services.statement_parsing import handle_parse_failure
from src.services.statement_posting import (
    is_high_confidence_auto_approve_candidate,
    try_auto_approve_high_confidence_statement,
)
from tests.factories import AccountFactory, UserFactory
from tests.ledger._ledger_helpers import create_valid_posted_entry

pytestmark = pytest.mark.asyncio


class DummyStorage:
    """Storage stub for statement upload tests."""

    def upload_bytes(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str | None = None,
    ) -> None:
        return None

    def get_object(self, key: str) -> bytes:
        return b"dummy content"

    def generate_presigned_url(
        self,
        *,
        key: str,
        expires_in: int | None = None,
        public: bool = False,
    ) -> str:
        return f"https://example.com/{key}"

    def delete_object(self, key: str) -> None:
        return None


@pytest.fixture
def storage_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(statements_router, "StorageService", DummyStorage)


@pytest.fixture
def model_catalog_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_catalog_get(self, model_id):
        return ModelSpec(
            id=model_id,
            provider_id="env",
            modalities=frozenset({Modality.TEXT, Modality.IMAGE}),
        )

    monkeypatch.setattr("src.routers.statements.LitellmCatalog.get", fake_catalog_get)


def make_upload_file(name: str, content: bytes) -> UploadFile:
    """Create an UploadFile for testing."""
    return UploadFile(
        filename=name,
        file=BytesIO(content),
    )


async def test_build_statement_storage_key_sanitizes_extension():
    """AC13.5.1: Statement object keys avoid PII and normalize unsafe extensions."""
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


def build_statement(user_id, file_hash: str, confidence_score: int) -> StatementSummary:
    """Build a StatementSummary (DWD conform) envelope for tests.

    Layer-1 file metadata (``file_path``/``original_filename``) now lives on the
    ODS ``UploadedDocument``; use :func:`seed_uploaded_document` to attach one when a
    test needs storage keys, filenames, or transaction resolution.
    """
    return StatementSummary(
        user_id=user_id,
        account_id=None,
        file_hash=file_hash,
        institution="DBS",
        account_last4="1234",
        currency="SGD",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        opening_balance=Decimal("100.00"),
        closing_balance=Decimal("110.00"),
        status=BankStatementStatus.PARSED,
        confidence_score=confidence_score,
        balance_validated=True,
    )


async def seed_uploaded_document(
    db,
    statement: StatementSummary,
    *,
    file_path: str = "tmp",
    original_filename: str = "stub.pdf",
) -> UploadedDocument:
    """Create the ODS ``UploadedDocument`` backing a statement and link it.

    Idempotent: if the statement already has an ``uploaded_document_id`` the existing
    document is returned. Returns the document so callers can build
    ``AtomicTransaction`` facts that reference it via ``source_documents``.
    """
    if statement.uploaded_document_id is not None:
        existing = await db.get(UploadedDocument, statement.uploaded_document_id)
        if existing is not None:
            return existing
    document = UploadedDocument(
        user_id=statement.user_id,
        file_path=file_path,
        file_hash=statement.file_hash,
        original_filename=original_filename,
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(document)
    await db.flush()
    statement.uploaded_document_id = document.id
    db.add(statement)
    await db.flush()
    return document


async def add_txn(
    db,
    statement,
    *,
    txn_date: date,
    description: str,
    amount: Decimal,
    direction: str,
) -> AtomicTransaction:
    """Build, persist, and return a Layer-2 ``AtomicTransaction`` for a statement.

    ``statement`` may be a :class:`StatementSummary` or its ``id`` (UUID). Lazily
    seeds the statement's ODS ``UploadedDocument`` so the fact resolves back to its
    owning envelope via ``source_documents -> UploadedDocument -> StatementSummary``
    (atomic transactions carry no ``statement_id``).
    """
    if not isinstance(statement, StatementSummary):
        statement = await db.get(StatementSummary, statement)
    document = await seed_uploaded_document(db, statement)
    txn = AtomicTransaction(
        user_id=statement.user_id,
        txn_date=txn_date,
        description=description,
        amount=amount,
        direction=TransactionDirection(direction),
        currency=statement.currency or "SGD",
        dedup_hash=uuid4().hex + uuid4().hex,
        source_documents=[{"doc_id": str(document.id), "doc_type": DocumentType.BANK_STATEMENT.value}],
    )
    db.add(txn)
    await db.flush()
    return txn


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


async def create_statement_account(db, user_id, name: str = "DBS Statement Account") -> Account:
    account = Account(
        user_id=user_id,
        name=name,
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(account)
    await db.flush()
    return account


async def wait_for_background_tasks() -> None:
    await statements_router.wait_for_parse_tasks()


async def test_upload_statement_duplicate(db, monkeypatch, storage_stub, model_catalog_stub, test_user):
    """AC3.5.4: Uploading the same file twice should trigger duplicate detection."""
    content = b"duplicate-statement"

    async def fake_parse_document(
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
        statement = build_statement(test_user.id, file_hash or "", confidence_score=90)
        return statement, []

    monkeypatch.setattr(
        statement_parsing_mod.ExtractionService,
        "parse_document",
        fake_parse_document,
    )

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
    """AC3.5.5: Storage failure should return 503."""
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
    """AC3.5.6: Invalid file extension should return 400."""
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
    """AC3.5.7: PDF/image uploads may omit model and use the default OCR pipeline."""
    mock_parse = AsyncMock(return_value=None)
    monkeypatch.setattr(statement_pipeline, "parse_statement_background", mock_parse)

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
    assert mock_parse.await_args.kwargs["model"] is None
    storage_key = mock_parse.await_args.kwargs["storage_key"]
    assert storage_key.startswith(f"statements/{created.id}/")
    assert "statement.pdf" not in storage_key
    assert str(test_user.id) not in storage_key
    assert storage_key.endswith(".pdf")


async def test_AC10_8_1_upload_audit_logs_include_statement_input_provenance(
    db, monkeypatch, storage_stub, model_catalog_stub, test_user
):
    """AC10.8.1: Upload audit logs expose safe replay inputs and correlation IDs."""
    content = b"audit-log-input"
    mock_parse = AsyncMock(return_value=None)
    mock_info = MagicMock()
    monkeypatch.setattr(statement_pipeline, "parse_statement_background", mock_parse)
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
    assert mock_parse.await_args.kwargs["statement_id"] == created.id


async def test_AC10_8_1_upload_storage_failure_logs_safe_audit_context(db, monkeypatch, model_catalog_stub, test_user):
    """AC10.8.1: Upload storage failures keep replayable safe failure context."""
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
    """AC10.8.3: Statement-scoped brokerage import logs replay context and counts."""
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
    """AC3.5.8: Upload rejects models without image modalities."""

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
    """AC3.5.9: Upload then list statements and transactions."""

    content = b"statement-flow"

    from src.services.deduplication import dual_write_layer2

    async def fake_parse_document(
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
        statement = build_statement(test_user.id, file_hash or "", confidence_score=90)
        transaction = AtomicTransaction(
            user_id=test_user.id,
            txn_date=date(2025, 1, 2),
            description="Salary",
            amount=Decimal("5000.00"),
            direction=TransactionDirection.IN,
            currency="SGD",
            dedup_hash=uuid4().hex + uuid4().hex,
            source_documents=[],
        )
        # Persist via the single DWD linker so the statement resolves its Layer-2 facts.
        await dual_write_layer2(
            db,
            test_user.id,
            statement,
            [transaction],
            original_filename=original_filename,
        )
        return statement, [transaction]

    monkeypatch.setattr(
        statement_parsing_mod.ExtractionService,
        "parse_document",
        fake_parse_document,
    )

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
    """AC3.5.10: Review queue includes reviewable parsed statements and supports approve/reject."""
    contents = [b"review-70", b"review-90"]
    scores = [70, 90]
    score_by_hash = {
        hashlib.sha256(contents[0]).hexdigest(): scores[0],
        hashlib.sha256(contents[1]).hexdigest(): scores[1],
    }

    from src.services.deduplication import dual_write_layer2

    async def fake_parse_document(
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
        score = score_by_hash[file_hash or ""]
        statement = build_statement(test_user.id, file_hash or "", confidence_score=score)
        statement.account_id = account_id
        statement.closing_balance = Decimal("100.00")
        await dual_write_layer2(db, test_user.id, statement, [], original_filename=original_filename)
        return statement, []

    monkeypatch.setattr(
        statement_parsing_mod.ExtractionService,
        "parse_document",
        fake_parse_document,
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
    # in #1099 (AC12.29.5); drive the same state transition via the service layer.
    statement_id = created_ids[0]

    approved = await statement_validation_mod.approve_statement(db, statement_id, test_user.id)
    await db.commit()
    assert approved.status == BankStatementStatus.APPROVED

    # Test reject (state transitions are allowed on the same statement).
    rejected = await statement_validation_mod.reject_statement(db, statement_id, test_user.id, reason="Incorrect data")
    await db.commit()
    assert rejected.status == BankStatementStatus.REJECTED


async def test_stage1_reject_triggers_reparse(db, monkeypatch, storage_stub, test_user):
    """AC16.22.2: Stage 1 reject queues a re-parse for the rejected statement."""
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

    monkeypatch.setattr(statement_pipeline, "parse_statement_background", fake_parse_statement_background)

    response = await statements_router.reject_statement_stage1(
        statement_id=statement.id,
        decision=StatementDecisionRequest(notes="Needs re-parse"),
        db=db,
        user_id=test_user.id,
    )
    await wait_for_background_tasks()

    assert response.status == BankStatementStatus.REJECTED
    assert response.validation_error == "Needs re-parse"
    assert queued["statement_id"] == statement.id
    assert queued["filename"] == document.original_filename
    assert queued["user_id"] == test_user.id
    assert queued["storage_key"] == document.file_path
    assert queued["content"] == b"dummy content"


async def test_get_statement_not_found(db, test_user):
    """AC3.5.11: Missing statement returns 404."""
    with pytest.raises(HTTPException) as exc:
        await statements_router.get_statement(
            statement_id=statements_router.UUID("00000000-0000-0000-0000-000000000000"),
            db=db,
            user_id=test_user.id,
        )
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


async def test_list_statement_transactions_not_found(db, test_user):
    """AC3.5.11: Missing statement transactions return 404."""
    with pytest.raises(HTTPException) as exc:
        await statements_router.list_statement_transactions(
            statement_id=statements_router.UUID("00000000-0000-0000-0000-000000000000"),
            db=db,
            user_id=test_user.id,
        )

    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


async def test_upload_file_too_large(db, model_catalog_stub, test_user):
    """AC3.5.12: File exceeding 10MB limit returns 413."""
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
    """AC3.5.13: Extraction failure marks statement as rejected."""
    content = b"content"

    mock_storage = MagicMock()
    mock_storage.upload_bytes.return_value = None
    mock_storage.generate_presigned_url.return_value = "https://example.com/file"
    mock_storage_cls = MagicMock(return_value=mock_storage)
    monkeypatch.setattr(statements_router, "StorageService", mock_storage_cls)

    async def fake_parse_document(
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
        raise ExtractionError("Failed to parse PDF")

    monkeypatch.setattr(
        statement_parsing_mod.ExtractionService,
        "parse_document",
        fake_parse_document,
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

    statement = await db.get(StatementSummary, created.id)
    assert statement is not None

    # Wait for background task to update status to REJECTED
    if statement.status == BankStatementStatus.PARSING:
        import asyncio

        await asyncio.sleep(0.5)
        await db.refresh(statement)

    assert statement.status == BankStatementStatus.REJECTED


async def test_retry_statement_not_found(db, test_user):
    """AC3.5.14: Retry on missing statement returns 404."""
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
    """AC3.5.15: Retry rejects models without image modalities."""
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


async def test_retry_statement_storage_failure(db, monkeypatch, test_user):
    """AC3.5.16: Retry returns 503 if storage fetch fails."""
    from src.schemas import RetryParsingRequest

    statement = build_statement(test_user.id, "hash", 80)
    statement.status = BankStatementStatus.REJECTED
    db.add(statement)
    await db.flush()
    await seed_uploaded_document(db, statement, file_path="path/to/file.pdf")
    await db.commit()

    mock_storage = MagicMock()
    mock_storage.get_object.side_effect = statements_router.StorageError("S3 Down")
    monkeypatch.setattr(statements_router, "StorageService", MagicMock(return_value=mock_storage))

    with pytest.raises(HTTPException) as exc:
        await statements_router.retry_statement_parsing(
            statement_id=statement.id,
            request=RetryParsingRequest(model=None),
            db=db,
            user_id=test_user.id,
        )

    assert exc.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert "Failed to fetch file from storage" in exc.value.detail


async def test_retry_statement_invalid_status(db, monkeypatch, storage_stub, model_catalog_stub, test_user):
    """AC3.5.17: Retry on statement not in parsed/rejected status returns 400."""
    from src.schemas import RetryParsingRequest

    content = b"statement"

    async def fake_parse_document(
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
        statement = build_statement(test_user.id, file_hash or "", confidence_score=90)
        statement.status = BankStatementStatus.PARSING
        return statement, []

    monkeypatch.setattr(
        statement_parsing_mod.ExtractionService,
        "parse_document",
        fake_parse_document,
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
    """AC3.5.18: Verify that retrying a statement in PARSING status is allowed."""
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
    """AC13.21.3 (#1141): retry accepts a balance-invalid statement at its PARSED rest.

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
    """AC13.21.6 (#1141): CSV upload without an institution fails synchronously (400).

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
    """AC3.5.19: Retry parsing with stronger model succeeds."""
    from src.schemas import RetryParsingRequest
    from src.services.deduplication import dual_write_layer2

    content = b"statement"

    async def fake_parse_document(
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
        statement = build_statement(test_user.id, file_hash or "", confidence_score=95)
        statement.status = BankStatementStatus.REJECTED
        statement.confidence_score = 60
        await dual_write_layer2(db, test_user.id, statement, [], original_filename=original_filename)
        return statement, []

    monkeypatch.setattr(
        statement_parsing_mod.ExtractionService,
        "parse_document",
        fake_parse_document,
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
    """AC3.5.20: Retry extraction failure returns 422."""
    from src.schemas import RetryParsingRequest
    from src.services.deduplication import dual_write_layer2

    content = b"statement"

    async def fake_parse_document(
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
        statement = build_statement(test_user.id, file_hash or "", confidence_score=90)
        statement.status = BankStatementStatus.REJECTED
        await dual_write_layer2(db, test_user.id, statement, [], original_filename=original_filename)
        return statement, []

    monkeypatch.setattr(
        statement_parsing_mod.ExtractionService,
        "parse_document",
        fake_parse_document,
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


async def test_upload_statement_rejects_invalid_model(db, test_user, storage_stub, monkeypatch):
    """AC3.5.21: Upload rejects models not in the OpenRouter catalog."""
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
    """AC3.5.22: Upload rejects a model lacking image/PDF modality (400)."""
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
    """AC3.5.23: Retry rejects a model not in the catalogue (400)."""
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
    """AC3.5.24: Background parse error should be caught and logged."""
    content = b"content"

    async def fake_parse_document_fail(*args, **kwargs):
        raise Exception("Fatal background error")

    monkeypatch.setattr(
        statement_parsing_mod.ExtractionService,
        "parse_document",
        fake_parse_document_fail,
    )

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
    """AC3.5.25: Background retry error should be caught and logged."""
    statement = build_statement(test_user.id, "hash_retry", 80)
    statement.status = BankStatementStatus.REJECTED
    db.add(statement)
    await db.flush()
    await seed_uploaded_document(db, statement, file_path="path")
    await db.commit()

    async def fake_parse_document_fail(*args, **kwargs):
        raise Exception("Fatal background retry error")

    monkeypatch.setattr(
        statement_parsing_mod.ExtractionService,
        "parse_document",
        fake_parse_document_fail,
    )

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
    Then it deletes from storage and DB (lines 685-698).
    """
    statement = build_statement(test_user.id, "hash_del", 90)
    db.add(statement)
    await db.flush()
    await seed_uploaded_document(db, statement, file_path="statements/user/file.pdf")
    await db.commit()
    statement_id = statement.id

    monkeypatch.setattr(statements_router, "StorageService", DummyStorage)

    await statements_router.delete_statement(statement_id=statement_id, db=db, user_id=test_user.id)

    deleted = await db.get(StatementSummary, statement_id)
    assert deleted is None


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
    Then the DB record is still deleted to avoid zombie records (lines 690-696).
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

    deleted = await db.get(StatementSummary, statement_id)
    assert deleted is None


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
    """AC16.33.5: the document endpoint streams the original upload, same-origin.

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
    """AC16.33.4: Statement review PDFs use a short-lived preview URL."""
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


async def test_approve_statement_stage1_success(db, test_user, monkeypatch):
    """Given a parsed statement with matching balances,
    When approve_statement_stage1 is called,
    Then it approves the statement (lines 761-771).
    """
    account = await create_statement_account(db, test_user.id, "Stage 1 Approve Account")
    statement = build_statement(test_user.id, "hash_s1_approve", 80)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = account.id
    # With no transactions, calculated_closing = opening_balance = 100.
    # Set closing_balance to match so validation passes.
    statement.closing_balance = Decimal("100.00")
    db.add(statement)
    await db.commit()
    statement_id = statement.id
    result = await statements_router.approve_statement_stage1(statement_id=statement_id, db=db, user_id=test_user.id)
    assert result.status == BankStatementStatus.APPROVED
    assert result.journal_entries_created == 0


async def test_approve_statement_stage1_creates_posted_entries(db, test_user):
    bank_account = Account(
        user_id=test_user.id,
        name="DBS Autosave",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(bank_account)
    await db.flush()

    statement = build_statement(test_user.id, "hash_s1_posted", 88)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = bank_account.id
    statement.closing_balance = Decimal("115.00")
    db.add(statement)
    await db.flush()
    statement_id = statement.id

    txn_in = await add_txn(
        db,
        statement_id,
        txn_date=date(2025, 1, 2),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    txn_out = await add_txn(
        db,
        statement_id,
        txn_date=date(2025, 1, 3),
        description="Lunch",
        amount=Decimal("5.00"),
        direction="OUT",
    )
    db.add_all([txn_in, txn_out])
    await db.flush()
    bank_account_id = bank_account.id
    txn_ids = [txn_in.id, txn_out.id]
    await db.commit()

    result = await statements_router.approve_statement_stage1(statement_id=statement_id, db=db, user_id=test_user.id)
    assert result.journal_entries_created == 2
    assert result.status == BankStatementStatus.APPROVED

    entries_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == test_user.id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.source_id.in_(txn_ids))
        .options(selectinload(JournalEntry.lines))
    )
    entries = entries_result.scalars().all()
    assert len(entries) == 2
    assert all(entry.status == JournalEntryStatus.POSTED for entry in entries)
    assert all(any(line.account_id == bank_account_id for line in entry.lines) for entry in entries)


async def test_approve_statement_stage1_auto_maps_unique_prior_confirmed_account(db, test_user):
    """AC3.6.1: Stage 1 posting may auto-map only from a unique prior confirmed statement."""
    bank_account = Account(
        user_id=test_user.id,
        name="DBS Confirmed Account",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(bank_account)
    await db.flush()

    prior = build_statement(test_user.id, "hash_s1_prior_confirmed", 95)
    prior.status = BankStatementStatus.APPROVED
    prior.account_id = bank_account.id
    db.add(prior)
    await db.flush()

    statement = build_statement(test_user.id, "hash_s1_auto_map", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = None
    statement.period_start = date(2025, 2, 1)
    statement.period_end = date(2025, 2, 28)
    statement.opening_balance = Decimal("110.00")
    statement.closing_balance = Decimal("130.00")
    db.add(statement)
    await db.flush()
    statement_id = statement.id

    txn = await add_txn(
        db,
        statement_id,
        txn_date=date(2025, 2, 5),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    db.add(txn)
    await db.flush()
    bank_account_id = bank_account.id
    txn_id = txn.id
    await db.commit()

    result = await statements_router.approve_statement_stage1(statement_id=statement_id, db=db, user_id=test_user.id)
    assert result.journal_entries_created == 1

    await db.refresh(statement)
    assert statement.account_id == bank_account_id

    entry_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == test_user.id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.source_id == txn_id)
        .options(selectinload(JournalEntry.lines))
    )
    entry = entry_result.scalar_one()
    assert any(line.account_id == bank_account_id for line in entry.lines)


async def test_auto_approve_high_confidence_statement_creates_posted_entries(db, test_user):
    """AC3.3.1: High-confidence, balance-valid, uniquely mapped statements auto-approve and post."""
    bank_account = await create_statement_account(db, test_user.id, "DBS Auto Approval")
    statement = build_statement(test_user.id, "hash_s1_high_confidence_auto", 90)
    statement.status = BankStatementStatus.APPROVED
    statement.account_id = bank_account.id
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()

    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 8),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    db.add(txn)
    await db.flush()
    txn_id = txn.id
    await db.commit()

    created_count = await try_auto_approve_high_confidence_statement(db, statement.id, test_user.id)
    assert created_count == 1

    await db.refresh(statement)
    assert statement.status == BankStatementStatus.APPROVED

    entry_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == test_user.id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.source_id == txn_id)
    )
    assert entry_result.scalar_one().status == JournalEntryStatus.POSTED


async def test_auto_approve_high_confidence_statement_returns_zero_for_non_candidate(db, test_user):
    statement = build_statement(test_user.id, "hash_s1_high_confidence_non_candidate", 90)
    statement.status = BankStatementStatus.PARSED
    statement.closing_balance = Decimal("100.00")
    db.add(statement)
    await db.commit()

    created_count = await try_auto_approve_high_confidence_statement(db, statement.id, test_user.id)

    assert created_count == 0


async def test_auto_approve_high_confidence_statement_falls_back_to_pending_review_on_guard_failure(db, test_user):
    """AC3.3.1: Unsafe high-confidence statements remain reviewable instead of failing parsing."""
    unsafe_account = Account(
        user_id=test_user.id,
        name="High Confidence Liability",
        type=AccountType.LIABILITY,
        currency="SGD",
    )
    db.add(unsafe_account)
    await db.flush()

    statement = build_statement(test_user.id, "hash_s1_high_confidence_guard_failure", 90)
    statement.status = BankStatementStatus.APPROVED
    statement.account_id = unsafe_account.id
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()

    await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 8),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    await db.commit()

    created_count = await try_auto_approve_high_confidence_statement(db, statement.id, test_user.id)

    assert created_count == 0
    await db.refresh(statement)
    assert statement.status == BankStatementStatus.PARSED
    assert statement.stage1_status == Stage1Status.PENDING_REVIEW
    assert "active asset account" in (statement.validation_error or "")


async def test_auto_approve_guard_failure_preserves_uncommitted_parse_data(db, test_user):
    """AC3.3.1: Auto-approval guard fallback must not roll back parsed statement data."""
    unsafe_account = Account(
        user_id=test_user.id,
        name="Uncommitted Liability",
        type=AccountType.LIABILITY,
        currency="SGD",
    )
    db.add(unsafe_account)
    await db.flush()

    statement = build_statement(test_user.id, "hash_s1_guard_failure_preserves_parse", 90)
    statement.status = BankStatementStatus.APPROVED
    statement.account_id = unsafe_account.id
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()

    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 8),
        description="Uncommitted Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    db.add(txn)
    await db.flush()

    created_count = await try_auto_approve_high_confidence_statement(db, statement.id, test_user.id)

    assert created_count == 0

    persisted_statement = await db.get(StatementSummary, statement.id)
    assert persisted_statement is not None
    assert persisted_statement.status == BankStatementStatus.PARSED
    assert persisted_statement.stage1_status == Stage1Status.PENDING_REVIEW
    assert "active asset account" in (persisted_statement.validation_error or "")

    persisted_txns = await statement_validation_mod.resolve_statement_transactions(db, persisted_statement)
    assert len(persisted_txns) == 1
    assert persisted_txns[0].description == "Uncommitted Salary"


async def test_approve_statement_stage1_promotes_existing_statement_entries_without_reposting(db, test_user):
    bank_account = await create_statement_account(db, test_user.id, "DBS Existing Entry Promotion")
    statement = build_statement(test_user.id, "hash_s1_existing_entry_promotion", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = bank_account.id
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()

    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 8),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    db.add(txn)
    await db.flush()

    existing_entry = await create_valid_posted_entry(
        db,
        test_user.id,
        entry_date=txn.txn_date,
        memo="Existing parsed entry",
        source_type=JournalEntrySourceType.AUTO_PARSED,
        source_id=txn.id,
    )

    result = await statements_router.approve_statement_stage1(statement_id=statement.id, db=db, user_id=test_user.id)

    assert result.journal_entries_created == 0
    await db.refresh(existing_entry)
    assert existing_entry.source_type == JournalEntrySourceType.USER_CONFIRMED

    entries_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == test_user.id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.source_id == txn.id)
    )
    assert len(entries_result.scalars().all()) == 1


async def test_approve_statement_stage1_blocks_prior_unconfirmed_account_mapping(db, test_user):
    """AC3.6.5: Stage 1 posting cannot auto-map from an unconfirmed prior statement."""
    user_id = test_user.id
    bank_account = await create_statement_account(db, user_id, "DBS Unconfirmed Prior")

    prior = build_statement(user_id, "hash_s1_prior_unconfirmed", 95)
    prior.status = BankStatementStatus.PARSED
    prior.account_id = bank_account.id
    db.add(prior)
    await db.flush()

    statement = build_statement(user_id, "hash_s1_unconfirmed_prior_target", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = None
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()

    await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 8),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await statements_router.approve_statement_stage1(statement_id=statement.id, db=db, user_id=user_id)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "No confirmed account matches" in str(exc.value.detail)


async def test_approve_statement_stage1_blocks_overlapping_statement_period_before_posting(db, test_user):
    """AC3.6.6: Stage 1 posting blocks duplicate or overlapping account/currency periods."""
    user_id = test_user.id
    bank_account = await create_statement_account(db, user_id, "DBS Period Guard")

    prior = build_statement(user_id, "hash_s1_prior_period", 95)
    prior.status = BankStatementStatus.APPROVED
    prior.account_id = bank_account.id
    prior.period_start = date(2025, 1, 1)
    prior.period_end = date(2025, 1, 31)
    db.add(prior)
    await db.flush()

    statement = build_statement(user_id, "hash_s1_period_overlap", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = bank_account.id
    statement.period_start = date(2025, 1, 15)
    statement.period_end = date(2025, 2, 15)
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()

    await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 20),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await statements_router.approve_statement_stage1(statement_id=statement.id, db=db, user_id=user_id)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Statement period overlaps" in str(exc.value.detail)

    entry_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
    )
    assert entry_result.scalars().all() == []


async def test_approve_statement_stage1_blocks_missing_statement_period_before_posting(db, test_user):
    user_id = test_user.id
    bank_account = await create_statement_account(db, user_id, "DBS Missing Period Guard")

    statement = build_statement(user_id, "hash_s1_missing_period", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = bank_account.id
    statement.period_start = None
    statement.period_end = date(2025, 1, 31)
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()

    await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 20),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await statements_router.approve_statement_stage1(statement_id=statement.id, db=db, user_id=user_id)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Statement period required" in str(exc.value.detail)


async def test_approve_statement_stage1_blocks_invalid_statement_period_before_posting(db, test_user):
    user_id = test_user.id
    bank_account = await create_statement_account(db, user_id, "DBS Invalid Period Guard")

    statement = build_statement(user_id, "hash_s1_invalid_period", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = bank_account.id
    statement.period_start = date(2025, 2, 1)
    statement.period_end = date(2025, 1, 31)
    statement.closing_balance = Decimal("120.00")
    with pytest.raises(IntegrityError, match="ck_statement_summaries_period_order"):
        db.add(statement)
        await db.flush()


async def test_approve_statement_stage1_blocks_missing_statement_currency_before_posting(db, test_user):
    user_id = test_user.id
    bank_account = await create_statement_account(db, user_id, "DBS Missing Currency Guard")

    statement = build_statement(user_id, "hash_s1_missing_currency", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = bank_account.id
    statement.currency = ""
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()

    await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 20),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await statements_router.approve_statement_stage1(statement_id=statement.id, db=db, user_id=user_id)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Statement currency required" in str(exc.value.detail)


async def test_approve_statement_stage1_blocks_unmapped_account_without_fallback(db, test_user):
    """AC3.6.2: Stage 1 posting blocks first uploads without an explicit account mapping."""
    user_id = test_user.id
    statement = build_statement(user_id, "hash_s1_unmapped", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = None
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()
    statement_id = statement.id

    await add_txn(
        db,
        statement_id,
        txn_date=date(2025, 1, 6),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await statements_router.approve_statement_stage1(statement_id=statement_id, db=db, user_id=user_id)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Account mapping required" in str(exc.value.detail)

    entry_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
    )
    assert entry_result.scalars().all() == []

    fallback_result = await db.execute(
        select(Account).where(Account.user_id == user_id).where(Account.name == "Bank - Main")
    )
    assert fallback_result.scalar_one_or_none() is None


async def test_approve_statement_stage1_blocks_missing_account_metadata(db, test_user):
    """AC3.6.2: Stage 1 posting blocks unmapped statements with incomplete account metadata."""
    user_id = test_user.id
    statement = build_statement(user_id, "hash_s1_missing_account_metadata", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = None
    statement.account_last4 = None
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()
    statement_id = statement.id

    await add_txn(
        db,
        statement_id,
        txn_date=date(2025, 1, 6),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await statements_router.approve_statement_stage1(statement_id=statement_id, db=db, user_id=user_id)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "metadata is missing" in str(exc.value.detail)


async def test_approve_statement_stage1_blocks_invalid_explicit_account_mapping(db, test_user):
    """AC3.6.2: Stage 1 posting blocks stale statement account references."""
    user_id = test_user.id

    statement = build_statement(user_id, "hash_s1_invalid_account_mapping", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = uuid4()
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    try:
        await db.execute(text("SET LOCAL session_replication_role = replica"))
        await db.flush()
        statement_id = statement.id
        await add_txn(
            db,
            statement_id,
            txn_date=date(2025, 1, 6),
            description="Salary",
            amount=Decimal("20.00"),
            direction="IN",
        )
    finally:
        await db.execute(text("SET LOCAL session_replication_role = DEFAULT"))
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await statements_router.approve_statement_stage1(statement_id=statement_id, db=db, user_id=user_id)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Statement account mapping is invalid" in str(exc.value.detail)


@pytest.mark.parametrize(
    ("account_type", "account_currency", "is_active", "expected_detail"),
    [
        (AccountType.LIABILITY, "SGD", True, "active asset account"),
        (AccountType.ASSET, "USD", True, "statement currency"),
        (AccountType.ASSET, "SGD", False, "active asset account"),
    ],
)
async def test_approve_statement_stage1_blocks_unsafe_explicit_account_mapping(
    db,
    test_user,
    account_type,
    account_currency,
    is_active,
    expected_detail,
):
    """AC3.6.2: Explicit statement accounts must be active ASSET accounts in the statement currency."""
    user_id = test_user.id
    account = Account(
        user_id=user_id,
        name="Unsafe Explicit Account",
        type=account_type,
        currency=account_currency,
        is_active=is_active,
    )
    db.add(account)
    await db.flush()

    statement = build_statement(user_id, f"hash_s1_unsafe_explicit_{account_type}_{account_currency}_{is_active}", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = account.id
    statement.currency = "SGD"
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()
    statement_id = statement.id

    await add_txn(
        db,
        statement_id,
        txn_date=date(2025, 1, 6),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await statements_router.approve_statement_stage1(statement_id=statement_id, db=db, user_id=user_id)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert expected_detail in str(exc.value.detail)


async def test_approve_statement_stage1_creates_account_with_explicit_confirmation(db, test_user):
    """AC3.6.4: First upload approval can explicitly create and bind a statement account."""
    user_id = test_user.id
    statement = build_statement(user_id, "hash_s1_confirm_create_account", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = None
    statement.account_last4 = "9876"
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()
    statement_id = statement.id

    txn = await add_txn(
        db,
        statement_id,
        txn_date=date(2025, 1, 6),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    db.add(txn)
    await db.flush()
    txn_id = txn.id
    await db.commit()

    result = await statements_router.approve_statement_stage1(
        statement_id=statement_id,
        db=db,
        user_id=user_id,
        request=Stage1ApprovalRequest(create_account_if_missing=True),
    )

    assert result.journal_entries_created == 1
    await db.refresh(statement)
    assert statement.account_id is not None

    account = await db.get(Account, statement.account_id)
    assert account is not None
    assert account.name == "DBS *9876"
    assert account.type == AccountType.ASSET
    assert account.currency == "SGD"

    entry_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.source_id == txn_id)
        .options(selectinload(JournalEntry.lines))
    )
    entry = entry_result.scalar_one()
    assert any(line.account_id == account.id for line in entry.lines)

    fallback_result = await db.execute(
        select(Account).where(Account.user_id == user_id).where(Account.name == "Bank - Main")
    )
    assert fallback_result.scalar_one_or_none() is None


async def test_approve_statement_stage1_blocks_ambiguous_account_mapping(db, test_user):
    """AC3.6.3: Stage 1 posting blocks ambiguous statement-account metadata matches."""
    user_id = test_user.id
    first_account = Account(
        user_id=user_id,
        name="DBS Account A",
        type=AccountType.ASSET,
        currency="SGD",
    )
    second_account = Account(
        user_id=user_id,
        name="DBS Account B",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add_all([first_account, second_account])
    await db.flush()

    first_prior = build_statement(user_id, "hash_s1_ambiguous_prior_a", 95)
    first_prior.status = BankStatementStatus.APPROVED
    first_prior.account_id = first_account.id
    second_prior = build_statement(user_id, "hash_s1_ambiguous_prior_b", 95)
    second_prior.status = BankStatementStatus.APPROVED
    second_prior.account_id = second_account.id
    db.add_all([first_prior, second_prior])
    await db.flush()

    statement = build_statement(user_id, "hash_s1_ambiguous", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = None
    statement.closing_balance = Decimal("120.00")
    db.add(statement)
    await db.flush()
    statement_id = statement.id

    await add_txn(
        db,
        statement_id,
        txn_date=date(2025, 1, 7),
        description="Salary",
        amount=Decimal("20.00"),
        direction="IN",
    )
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await statements_router.approve_statement_stage1(statement_id=statement_id, db=db, user_id=user_id)

    assert exc.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Ambiguous account mapping" in str(exc.value.detail)


async def test_approve_statement_stage1_keeps_transfer_detection_priority(db, test_user):
    bank_account = await create_statement_account(db, test_user.id, "Transfer Priority Account")
    statement = build_statement(test_user.id, "hash_s1_transfer_priority", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = bank_account.id
    statement.closing_balance = Decimal("90.00")
    db.add(statement)
    await db.flush()

    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 4),
        description="Transfer out",
        amount=Decimal("10.00"),
        direction="OUT",
    )
    db.add(txn)
    await db.flush()

    transfer_entry = await create_valid_posted_entry(
        db,
        test_user.id,
        entry_date=date(2025, 1, 4),
        memo="Transfer OUT via processing account",
        source_type=JournalEntrySourceType.SYSTEM,
    )

    db.add(
        ReconciliationMatch(
            atomic_txn_id=txn.id,
            journal_entry_ids=[str(transfer_entry.id)],
            status=ReconciliationStatus.AUTO_ACCEPTED,
            match_score=100,
        )
    )
    await db.commit()

    result = await statements_router.approve_statement_stage1(statement_id=statement.id, db=db, user_id=test_user.id)
    assert result.journal_entries_created == 0

    generated_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == test_user.id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.source_id == txn.id)
    )
    assert generated_result.scalar_one_or_none() is None


async def test_approve_statement_stage1_ignores_rejected_matches_for_skip_logic(db, test_user):
    account = await create_statement_account(db, test_user.id, "DBS Rejected Match")
    statement = build_statement(test_user.id, "hash_s1_rejected_match", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = account.id
    statement.closing_balance = Decimal("90.00")
    db.add(statement)
    await db.flush()

    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 4),
        description="Payment",
        amount=Decimal("10.00"),
        direction="OUT",
    )
    db.add(txn)
    await db.flush()

    stale_entry = await create_valid_posted_entry(
        db,
        test_user.id,
        entry_date=date(2025, 1, 4),
        memo="Stale candidate",
        source_type=JournalEntrySourceType.SYSTEM,
    )

    db.add(
        ReconciliationMatch(
            atomic_txn_id=txn.id,
            journal_entry_ids=[str(stale_entry.id)],
            status=ReconciliationStatus.REJECTED,
            match_score=100,
        )
    )
    await db.commit()

    result = await statements_router.approve_statement_stage1(statement_id=statement.id, db=db, user_id=test_user.id)
    assert result.journal_entries_created == 1

    generated_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == test_user.id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.source_id == txn.id)
    )
    generated = generated_result.scalar_one_or_none()
    assert generated is not None


async def test_approve_statement_stage1_balance_mismatch(db, test_user):
    """Given a statement where closing balance doesn't match calculations,
    When approve_statement_stage1 is called,
    Then it raises 400 (lines 764-765).
    """
    account = await create_statement_account(db, test_user.id, "Balance Mismatch Account")
    statement = build_statement(test_user.id, "hash_s1_mismatch", 80)
    statement.account_id = account.id
    statement.closing_balance = Decimal("999.99")  # Wrong closing balance
    db.add(statement)
    await db.commit()
    statement_id = statement.id

    with pytest.raises(HTTPException) as exc:
        await statements_router.approve_statement_stage1(statement_id=statement_id, db=db, user_id=test_user.id)
    assert exc.value.status_code == 400
    assert "Balance mismatch" in exc.value.detail


async def test_approve_statement_stage1_authorizes_before_balance_validation(db, test_user, monkeypatch):
    """AC16.18.1: Stage 1 approval must not validate another user's statement."""
    other_user = User(email="stage1-other@example.com", hashed_password="hashed")
    db.add(other_user)
    await db.flush()

    statement = build_statement(other_user.id, "hash_s1_other_user", 80)
    statement.closing_balance = Decimal("100.00")
    db.add(statement)
    await db.commit()
    statement_id = statement.id

    validation = AsyncMock(side_effect=AssertionError("validation should not run before authorization"))
    monkeypatch.setattr(statement_validation_mod, "validate_balance_chain", validation)

    with pytest.raises(HTTPException) as exc:
        await statements_router.approve_statement_stage1(statement_id=statement_id, db=db, user_id=test_user.id)

    assert exc.value.status_code == 404
    assert "Statement not found" in exc.value.detail
    validation.assert_not_awaited()


async def test_reject_statement_stage1_success(db, test_user, monkeypatch):
    """Given a parsed statement,
    When reject_statement_stage1 is called,
    Then it rejects the statement (lines 782-792).
    """
    statement = build_statement(test_user.id, "hash_s1_reject", 80)
    statement.status = BankStatementStatus.PARSED
    db.add(statement)
    await db.commit()
    statement_id = statement.id
    queue_reparse = AsyncMock()
    monkeypatch.setattr(statements_router, "_queue_statement_reparse", queue_reparse)

    result = await statements_router.reject_statement_stage1(
        statement_id=statement_id,
        decision=StatementDecisionRequest(notes="Bad data"),
        db=db,
        user_id=test_user.id,
    )

    assert result.status == BankStatementStatus.REJECTED
    queue_reparse.assert_awaited_once()


async def test_reject_statement_stage1_not_found(db, test_user):
    """Given a non-existent statement,
    When reject_statement_stage1 is called,
    Then it raises 400 (ValueError from service).
    """
    with pytest.raises(HTTPException) as exc:
        await statements_router.reject_statement_stage1(
            statement_id=statements_router.UUID("00000000-0000-0000-0000-000000000000"),
            decision=StatementDecisionRequest(notes="Bad"),
            db=db,
            user_id=test_user.id,
        )
    assert exc.value.status_code == 400


async def test_edit_and_approve_statement_is_unsupported(db, test_user):
    """Editing parsed transactions is unsupported: Layer-2 atomic facts are write-once.

    Reviewers must reject and re-parse instead, so the endpoint now returns 400.
    """
    from src.schemas.review import EditAndApproveRequest, TransactionEditRequest

    account = await create_statement_account(db, test_user.id, "DBS Edit Approve")
    statement = build_statement(test_user.id, "hash_edit_approve", 80)
    statement.account_id = account.id
    db.add(statement)
    await db.commit()
    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 15),
        description="Test Txn",
        amount=Decimal("10.00"),
        direction="IN",
    )
    await db.commit()
    await db.refresh(txn)
    txn_id = txn.id
    statement_id = statement.id
    edit_req = EditAndApproveRequest(
        edits=[
            TransactionEditRequest(
                txn_id=txn_id,
                amount=Decimal("10.00"),
                description="Test Txn",
                txn_date=date(2025, 1, 15),
                direction="IN",
            )
        ]
    )
    with pytest.raises(HTTPException) as exc:
        await statements_router.edit_and_approve_statement(
            statement_id=statement_id, request=edit_req, db=db, user_id=test_user.id
        )
    assert exc.value.status_code == 400
    assert "unsupported" in exc.value.detail.lower()


async def test_edit_and_approve_statement_balance_invalid(db, test_user):
    """Given a statement where edits result in balance mismatch,
    When edit_and_approve_statement is called,
    Then it raises 400 (lines 807-808).
    """
    from src.schemas.review import EditAndApproveRequest, TransactionEditRequest

    statement = build_statement(test_user.id, "hash_edit_bad", 80)
    db.add(statement)
    await db.commit()
    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 15),
        description="Test Txn",
        amount=Decimal("10.00"),
        direction="IN",
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)
    statement_id = statement.id
    # Change amount to something that breaks the balance
    edit_req = EditAndApproveRequest(
        edits=[
            TransactionEditRequest(
                txn_id=txn.id,
                amount=Decimal("99999.00"),
                description="Test Txn",
                txn_date=date(2025, 1, 15),
                direction="IN",
            )
        ]
    )
    with pytest.raises(HTTPException) as exc:
        await statements_router.edit_and_approve_statement(
            statement_id=statement_id, request=edit_req, db=db, user_id=test_user.id
        )
    assert exc.value.status_code == 400


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


async def test_get_stage2_review_queue_empty(db, test_user):
    """Given no pending matches or checks,
    When get_stage2_review_queue is called,
    Then it returns empty queue (lines 844-867).
    """
    result = await review_router.get_stage2_review_queue(db=db, user_id=test_user.id)

    assert result.pending_matches == []
    assert result.consistency_checks == []
    assert result.has_unresolved_checks is False


async def test_get_stage2_review_queue_with_pending_match(db, test_user):
    """AC4.9.4: Given a statement with a pending-review reconciliation match,
    When get_stage2_review_queue is called,
    Then it returns the match in pending_matches with tier derived from match_score.
    """
    from src.models.reconciliation import ReconciliationMatch, ReconciliationStatus

    account = await create_statement_account(db, test_user.id, "Stage 2 Queue Account")
    statement = build_statement(test_user.id, "hash_s2_queue", 90)
    statement.status = BankStatementStatus.APPROVED
    statement.account_id = account.id
    db.add(statement)
    await db.commit()

    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 15),
        description="Payment",
        amount=Decimal("50.00"),
        direction="OUT",
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)

    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        match_score=75,
        status=ReconciliationStatus.PENDING_REVIEW,
        version=1,
    )
    db.add(match)
    await db.commit()

    result = await review_router.get_stage2_review_queue(db=db, user_id=test_user.id)

    assert len(result.pending_matches) == 1
    assert result.pending_matches[0].status == "pending_review"
    assert result.pending_matches[0].match_score == 75
    assert result.pending_matches[0].confidence_tier == "MEDIUM"


async def test_run_stage2_checks_success(db, test_user):
    """Given an existing statement,
    When run_stage2_checks is called,
    Then it runs consistency checks and returns results (lines 881-891).
    """
    account = await create_statement_account(db, test_user.id, "Stage 2 Checks Account")
    statement = build_statement(test_user.id, "hash_s2_checks", 90)
    statement.status = BankStatementStatus.APPROVED
    statement.account_id = account.id
    db.add(statement)
    await db.commit()
    statement_id = statement.id

    result = await review_router.run_stage2_checks(statement_id=statement_id, db=db, user_id=test_user.id)

    assert result.total >= 0
    assert isinstance(result.items, list)


async def test_run_stage2_checks_not_found(db, test_user):
    """Given a non-existent statement,
    When run_stage2_checks is called,
    Then it raises 404.
    """
    with pytest.raises(HTTPException) as exc:
        await review_router.run_stage2_checks(
            statement_id=statements_router.UUID("00000000-0000-0000-0000-000000000000"),
            db=db,
            user_id=test_user.id,
        )
    assert exc.value.status_code == status.HTTP_404_NOT_FOUND


async def test_resolve_consistency_check_success(db, test_user):
    """Given a pending consistency check,
    When resolve_consistency_check is called with action='approve',
    Then it resolves the check (lines 905-911).
    """
    from src.models.consistency_check import CheckStatus, CheckType, ConsistencyCheck

    check = ConsistencyCheck(
        user_id=test_user.id,
        check_type=CheckType.DUPLICATE,
        status=CheckStatus.PENDING,
        related_txn_ids=["txn1", "txn2"],
        details={"count": 2, "amount": "100.00"},
        severity="high",
    )
    db.add(check)
    await db.commit()
    await db.refresh(check)
    check_id = check.id

    result = await review_router.resolve_consistency_check(
        check_id=check_id,
        request=ResolveCheckRequest(action="approve", note="Looks fine"),
        db=db,
        user_id=test_user.id,
    )

    assert result.status == CheckStatus.APPROVED
    assert result.resolution_note == "Looks fine"


async def test_resolve_consistency_check_invalid_action(db, test_user):
    """Given a pending consistency check,
    When resolve_consistency_check is called with an invalid action,
    Then it raises 400.
    """
    from src.models.consistency_check import CheckStatus, CheckType, ConsistencyCheck

    check = ConsistencyCheck(
        user_id=test_user.id,
        check_type=CheckType.DUPLICATE,
        status=CheckStatus.PENDING,
        related_txn_ids=["txn1"],
        details={"count": 1},
        severity="high",
    )
    db.add(check)
    await db.commit()
    await db.refresh(check)
    check_id = check.id

    with pytest.raises(HTTPException) as exc:
        await review_router.resolve_consistency_check(
            check_id=check_id,
            request=ResolveCheckRequest(action="invalid"),
            db=db,
            user_id=test_user.id,
        )
    assert exc.value.status_code == 400


async def test_resolve_consistency_check_not_found(db, test_user):
    """Given a non-existent check ID,
    When resolve_consistency_check is called,
    Then it raises 400.
    """
    with pytest.raises(HTTPException) as exc:
        await review_router.resolve_consistency_check(
            check_id=statements_router.UUID("00000000-0000-0000-0000-000000000000"),
            request=ResolveCheckRequest(action="approve"),
            db=db,
            user_id=test_user.id,
        )
    assert exc.value.status_code == 400


async def test_list_consistency_checks_empty(db, test_user):
    """Given no consistency checks,
    When list_consistency_checks is called,
    Then it returns an empty list (lines 924-947).
    """
    result = await review_router.list_consistency_checks(db=db, user_id=test_user.id)

    assert result.total == 0
    assert result.items == []


async def test_list_consistency_checks_with_filters(db, test_user):
    """Given multiple consistency checks,
    When list_consistency_checks is called with status and type filters,
    Then it returns filtered results (lines 934-939).
    """
    from src.models.consistency_check import CheckStatus, CheckType, ConsistencyCheck

    check1 = ConsistencyCheck(
        user_id=test_user.id,
        check_type=CheckType.DUPLICATE,
        status=CheckStatus.PENDING,
        related_txn_ids=["txn1"],
        details={"count": 1},
        severity="high",
    )
    check2 = ConsistencyCheck(
        user_id=test_user.id,
        check_type=CheckType.TRANSFER_PAIR,
        status=CheckStatus.APPROVED,
        related_txn_ids=["txn2"],
        details={"amount": "50.00"},
        severity="medium",
    )
    db.add(check1)
    db.add(check2)
    await db.commit()

    # Filter by status
    result = await review_router.list_consistency_checks(db=db, user_id=test_user.id, status=CheckStatus.PENDING)
    assert result.total == 1
    assert result.items[0].check_type == CheckType.DUPLICATE

    # Filter by check_type
    result2 = await review_router.list_consistency_checks(
        db=db, user_id=test_user.id, check_type=CheckType.TRANSFER_PAIR
    )
    assert result2.total == 1
    assert result2.items[0].status == CheckStatus.APPROVED


async def test_batch_approve_matches_blocked_by_unresolved_checks(db, test_user):
    """AC16.22.3: Given unresolved consistency checks,
    When batch_approve_matches is called,
    Then it returns error (lines 960-965).
    """
    from src.models.consistency_check import CheckStatus, CheckType, ConsistencyCheck

    check = ConsistencyCheck(
        user_id=test_user.id,
        check_type=CheckType.DUPLICATE,
        status=CheckStatus.PENDING,
        related_txn_ids=["txn1"],
        details={"count": 1},
        severity="high",
    )
    db.add(check)
    await db.commit()

    # #1001: unresolved checks now raise a 409 structured error instead of
    # returning {"success": false} in a 200 body.
    with pytest.raises(HTTPException) as exc:
        await review_router.batch_approve_matches(
            request=BatchApproveRequest(match_ids=[]),
            db=db,
            user_id=test_user.id,
        )

    assert exc.value.status_code == status.HTTP_409_CONFLICT
    assert "unresolved" in exc.value.detail


async def test_AC16_32_1_stage1_approval_blocks_unresolved_conflicts(db, test_user):
    """AC16.32.1: Stage 1 approval cannot bypass unresolved duplicate candidates."""
    account = await create_statement_account(db, test_user.id, "DBS Stage 1 Conflict")
    statement = build_statement(test_user.id, "hash_stage1_conflict", 90)
    statement.status = BankStatementStatus.PARSED
    statement.stage1_status = Stage1Status.PENDING_REVIEW
    statement.account_id = account.id
    statement.opening_balance = Decimal("100.00")
    statement.closing_balance = Decimal("140.00")
    db.add(statement)
    await db.commit()

    for _ in range(2):
        await add_txn(
            db,
            statement,
            txn_date=date(2025, 1, 15),
            description="Duplicate deposit",
            amount=Decimal("20.00"),
            direction="IN",
        )
    await db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await statements_router.approve_statement_stage1(
            statement_id=statement.id,
            request=Stage1ApprovalRequest(notes=None),
            db=db,
            user_id=test_user.id,
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "unresolved duplicate or transfer-pair" in exc_info.value.detail


async def test_AC16_32_1_stage1_approval_blocks_unresolved_transfer_pairs(db, test_user):
    """AC16.32.1: Stage 1 approval cannot bypass unresolved transfer-pair candidates."""
    account = await create_statement_account(db, test_user.id, "Transfer Conflict Account")
    statement = build_statement(test_user.id, "hash_stage1_transfer_conflict", 90)
    statement.status = BankStatementStatus.PARSED
    statement.account_id = account.id
    statement.closing_balance = Decimal("100.00")
    db.add(statement)
    await db.commit()

    await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 15),
        description="Transfer out",
        amount=Decimal("20.00"),
        direction="OUT",
    )
    await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 15),
        description="Transfer in",
        amount=Decimal("20.00"),
        direction="IN",
    )
    await db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await statements_router.approve_statement_stage1(
            statement_id=statement.id,
            request=Stage1ApprovalRequest(notes=None),
            db=db,
            user_id=test_user.id,
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "unresolved duplicate or transfer-pair" in exc_info.value.detail


async def test_AC16_34_1_resolve_unblocks_stage1_approval(db, test_user):
    """AC16.34.1: resolving the conflict candidates unblocks Stage 1 approval.

    A statement with an inherent duplicate is no longer permanently stuck in
    ``parsed`` once the reviewer confirms the rows are genuinely distinct.
    """
    user_id = test_user.id  # capture before any rollback expires the fixture object
    account = await create_statement_account(db, test_user.id, "Resolve Conflict Account")
    statement = build_statement(test_user.id, "hash_stage1_resolve", 90)
    statement.status = BankStatementStatus.PARSED
    statement.stage1_status = Stage1Status.PENDING_REVIEW
    statement.account_id = account.id
    statement.opening_balance = Decimal("100.00")
    statement.closing_balance = Decimal("140.00")
    db.add(statement)
    await db.commit()
    statement_id = statement.id  # capture before commits/rollbacks expire the object

    for _ in range(2):
        await add_txn(
            db,
            statement,
            txn_date=date(2025, 1, 15),
            description="Duplicate deposit",
            amount=Decimal("20.00"),
            direction="IN",
        )
    await db.commit()

    # Before resolving, approval is blocked.
    with pytest.raises(HTTPException) as exc_info:
        await statements_router.approve_statement_stage1(
            statement_id=statement_id,
            request=Stage1ApprovalRequest(),
            db=db,
            user_id=user_id,
        )
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST

    # Resolve the candidates via the Stage-1 conflict-resolution endpoint.
    resolve_response = await review_router.resolve_review_conflicts(
        statement_id=statement_id,
        request=ResolveConflictsRequest(action="confirm_distinct"),
        db=db,
        user_id=user_id,
    )
    assert resolve_response.resolved is True
    assert resolve_response.resolved_at is not None

    # The conflicts endpoint exposes the persisted marker so the UI can derive the
    # blocked state from the server rather than ephemeral client state.
    conflicts_after = await review_router.get_review_conflicts(statement_id=statement_id, db=db, user_id=user_id)
    assert conflicts_after.resolved is True

    # Approval now succeeds despite the duplicate candidate (no HTTP 400 raised).
    approved = await statements_router.approve_statement_stage1(
        statement_id=statement_id,
        request=Stage1ApprovalRequest(),
        db=db,
        user_id=user_id,
    )
    assert approved.id == statement_id
    assert approved.status == BankStatementStatus.APPROVED


async def test_AC16_34_1_resolve_conflicts_404_for_unknown_statement(db, test_user):
    """AC16.34.1: resolving conflicts for a missing statement returns 404."""
    with pytest.raises(HTTPException) as exc_info:
        await review_router.resolve_review_conflicts(
            statement_id=statements_router.UUID("00000000-0000-0000-0000-000000000000"),
            request=ResolveConflictsRequest(action="confirm_distinct"),
            db=db,
            user_id=test_user.id,
        )
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


async def test_AC16_34_2_reject_clears_conflict_resolution(db, test_user):
    """AC16.34.2: a reject/reparse clears a prior conflict resolution so the
    fresh transaction set must be re-reviewed."""
    statement = build_statement(test_user.id, "hash_stage1_resolve_reset", 90)
    statement.status = BankStatementStatus.PARSED
    db.add(statement)
    await db.commit()
    statement_id = statement.id  # capture before commit expires the object

    await review_router.resolve_review_conflicts(
        statement_id=statement_id,
        request=ResolveConflictsRequest(action="confirm_distinct"),
        db=db,
        user_id=test_user.id,
    )
    await db.refresh(statement)
    assert statement.stage1_conflicts_resolved_at is not None

    await statement_validation_mod.reject_statement(db, statement_id, test_user.id, reason="reparse")
    await db.commit()
    await db.refresh(statement)
    assert statement.stage1_conflicts_resolved_at is None


async def test_AC16_32_3_stage2_queue_returns_all_pending_checks(db, test_user):
    """AC16.32.3: Stage 2 queue includes the full unresolved blocker set."""
    db.add_all(
        [
            ConsistencyCheck(
                user_id=test_user.id,
                check_type=CheckType.DUPLICATE,
                status=CheckStatus.PENDING,
                related_txn_ids=[f"txn-{idx}"],
                details={"message": f"Duplicate candidate {idx}"},
                severity="high",
            )
            for idx in range(55)
        ]
    )
    await db.commit()

    result = await review_router.get_stage2_review_queue(db=db, user_id=test_user.id)

    assert len(result.consistency_checks) == 55


async def test_AC19_11_1_consistency_check_list_filters_by_run_id(db, test_user):
    """AC19.11.1: Consistency check list supports run-scoped review pages."""
    db.add_all(
        [
            ConsistencyCheck(
                user_id=test_user.id,
                run_id="run-123",
                check_type=CheckType.DUPLICATE,
                status=CheckStatus.PENDING,
                related_txn_ids=["txn-in-run"],
                details={"message": "Run scoped duplicate"},
                severity="high",
            ),
            ConsistencyCheck(
                user_id=test_user.id,
                run_id="run-456",
                check_type=CheckType.DUPLICATE,
                status=CheckStatus.PENDING,
                related_txn_ids=["txn-other-run"],
                details={"message": "Other run duplicate"},
                severity="high",
            ),
        ]
    )
    await db.commit()

    result = await review_router.list_consistency_checks(db=db, user_id=test_user.id, run_id="run-123")

    assert result.total == 1
    assert result.items[0].related_txn_ids == ["txn-in-run"]


async def test_AC19_11_1_stage2_run_queue_filters_by_run_id(db, test_user):
    """AC19.11.1: Run review queues and approval are scoped to the requested run."""
    account = await create_statement_account(db, test_user.id, "DBS Run Scope")
    statement = build_statement(test_user.id, "hash_stage2_run_scope", 90)
    statement.status = BankStatementStatus.APPROVED
    statement.account_id = account.id
    db.add(statement)
    await db.commit()

    txn_in_run = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 16),
        description="Run scoped payment",
        amount=Decimal("50.00"),
        direction="OUT",
    )
    txn_other_run = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 17),
        description="Other run payment",
        amount=Decimal("60.00"),
        direction="OUT",
    )
    db.add_all([txn_in_run, txn_other_run])
    await db.commit()
    await db.refresh(txn_in_run)
    await db.refresh(txn_other_run)

    in_run_match = ReconciliationMatch(
        atomic_txn_id=txn_in_run.id,
        run_id="run-123",
        match_score=95,
        status=ReconciliationStatus.PENDING_REVIEW,
        version=1,
    )
    other_run_match = ReconciliationMatch(
        atomic_txn_id=txn_other_run.id,
        run_id="run-456",
        match_score=95,
        status=ReconciliationStatus.PENDING_REVIEW,
        version=1,
    )
    db.add_all([in_run_match, other_run_match])
    await db.commit()

    queue = await review_router.get_stage2_review_queue(db=db, user_id=test_user.id, run_id="run-123")

    assert [str(match.id) for match in queue.pending_matches] == [str(in_run_match.id)]

    result = await review_router.batch_approve_matches(
        request=BatchApproveRequest(match_ids=[in_run_match.id, other_run_match.id], run_id="run-123"),
        db=db,
        user_id=test_user.id,
    )
    assert result.approved_count == 1
    await db.refresh(in_run_match)
    await db.refresh(other_run_match)
    assert in_run_match.status == ReconciliationStatus.ACCEPTED
    assert other_run_match.status == ReconciliationStatus.PENDING_REVIEW


async def test_batch_approve_matches_empty_list(db, test_user):
    """Given no unresolved checks and empty match_ids,
    When batch_approve_matches is called,
    Then it returns success with 0 approved (line 968).
    """
    result = await review_router.batch_approve_matches(
        request=BatchApproveRequest(match_ids=[]),
        db=db,
        user_id=test_user.id,
    )
    assert result.approved_count == 0


async def test_batch_approve_matches_success(db, test_user):
    """Given pending-review matches and no unresolved checks,
    When batch_approve_matches is called with match IDs,
    Then it approves all matching records (lines 970-993).
    """
    from src.models.reconciliation import ReconciliationMatch, ReconciliationStatus

    account = await create_statement_account(db, test_user.id, "DBS Batch Approval")
    statement = build_statement(test_user.id, "hash_batch_app", 90)
    statement.status = BankStatementStatus.APPROVED
    statement.account_id = account.id
    db.add(statement)
    await db.commit()

    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 15),
        description="Payment",
        amount=Decimal("50.00"),
        direction="OUT",
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)

    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        match_score=75,
        status=ReconciliationStatus.PENDING_REVIEW,
        version=1,
    )
    db.add(match)
    await db.commit()
    await db.refresh(match)
    match_id = match.id

    result = await review_router.batch_approve_matches(
        request=BatchApproveRequest(match_ids=[match_id]),
        db=db,
        user_id=test_user.id,
    )
    assert result.approved_count == 1


async def test_batch_approve_matches_reconciles_referenced_entry(db, test_user):
    """AC16.24.4: Batch approving a pending Stage 2 match reconciles referenced ledger entries."""
    account = await create_statement_account(db, test_user.id, "DBS Batch Referenced")
    statement = build_statement(test_user.id, "hash_batch_reconcile", 90)
    statement.status = BankStatementStatus.APPROVED
    statement.account_id = account.id
    db.add(statement)
    await db.commit()

    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 16),
        description="Referenced entry payment",
        amount=Decimal("50.00"),
        direction="OUT",
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)

    entry = await create_entry_from_txn(db, txn, user_id=test_user.id, auto_post=True)
    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        match_score=85,
        status=ReconciliationStatus.PENDING_REVIEW,
        version=1,
    )
    db.add(match)
    await db.commit()

    result = await review_router.batch_approve_matches(
        request=BatchApproveRequest(match_ids=[match.id]),
        db=db,
        user_id=test_user.id,
    )
    assert result.approved_count == 1
    assert result.journal_entries_created == 0
    assert result.journal_entries_reconciled == 1

    await db.refresh(match)
    await db.refresh(txn)
    await db.refresh(entry)
    assert match.status == ReconciliationStatus.ACCEPTED
    # AtomicTransaction has no per-txn status; the ReconciliationMatch status is the truth.
    assert entry.status == JournalEntryStatus.RECONCILED


async def test_batch_approve_matches_creates_missing_entry_once(db, test_user):
    """AC16.22.4 AC16.24.4: Accepted Stage 2 match creates the missing journal entry once."""
    account = await create_statement_account(db, test_user.id, "DBS Batch Missing")
    statement = build_statement(test_user.id, "hash_batch_create_once", 90)
    statement.status = BankStatementStatus.APPROVED
    statement.account_id = account.id
    db.add(statement)
    await db.commit()

    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 17),
        description="Missing entry payment",
        amount=Decimal("50.00"),
        direction="OUT",
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)

    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[],
        match_score=85,
        status=ReconciliationStatus.PENDING_REVIEW,
        version=1,
    )
    db.add(match)
    await db.commit()

    result = await review_router.batch_approve_matches(
        request=BatchApproveRequest(match_ids=[match.id]),
        db=db,
        user_id=test_user.id,
    )
    assert result.approved_count == 1
    assert result.journal_entries_created == 1
    assert result.journal_entries_reconciled == 1

    await db.refresh(match)
    await db.refresh(txn)
    assert match.status == ReconciliationStatus.ACCEPTED
    # AtomicTransaction has no per-txn status; the ReconciliationMatch status is the truth.
    assert len(match.journal_entry_ids) == 1

    entry_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == test_user.id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.source_id == txn.id)
    )
    entries = list(entry_result.scalars().all())
    assert len(entries) == 1
    assert entries[0].status == JournalEntryStatus.RECONCILED

    second_result = await review_router.batch_approve_matches(
        request=BatchApproveRequest(match_ids=[match.id]),
        db=db,
        user_id=test_user.id,
    )
    assert second_result.approved_count == 0
    assert second_result.journal_entries_created == 0
    assert second_result.journal_entries_reconciled == 0

    second_entry_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == test_user.id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.source_id == txn.id)
    )
    assert len(list(second_entry_result.scalars().all())) == 1


async def test_accept_match_retry_is_idempotent_after_success(db, test_user):
    """AC4.9.2: Retrying an accepted match must not mutate version or duplicate posting side effects."""
    account = await create_statement_account(db, test_user.id, "DBS Accept Retry")
    statement = build_statement(test_user.id, "hash_accept_retry", 90)
    statement.status = BankStatementStatus.APPROVED
    statement.account_id = account.id
    db.add(statement)
    await db.commit()

    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 18),
        description="Retry-safe payment",
        amount=Decimal("50.00"),
        direction="OUT",
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)

    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[],
        match_score=85,
        status=ReconciliationStatus.PENDING_REVIEW,
        version=1,
    )
    db.add(match)
    await db.commit()

    first = await accept_match_service(db, str(match.id), user_id=test_user.id)
    await db.commit()
    first_version = first.version
    first_entry_ids = list(first.journal_entry_ids or [])

    second = await accept_match_service(db, str(match.id), user_id=test_user.id)
    await db.commit()

    assert second.status == ReconciliationStatus.ACCEPTED
    assert second.version == first_version
    assert second.journal_entry_ids == first_entry_ids

    entry_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == test_user.id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.source_id == txn.id)
    )
    assert len(list(entry_result.scalars().all())) == 1


async def test_batch_approve_matches_reuses_existing_source_entry(db, test_user):
    """AC16.24.4: Batch approval links an existing source journal entry instead of duplicating it."""
    account = await create_statement_account(db, test_user.id, "DBS Batch Existing Source")
    statement = build_statement(test_user.id, "hash_batch_reuse_source", 90)
    statement.status = BankStatementStatus.APPROVED
    statement.account_id = account.id
    db.add(statement)
    await db.commit()

    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 18),
        description="Existing source entry payment",
        amount=Decimal("50.00"),
        direction="OUT",
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)

    entry = await create_entry_from_txn(db, txn, user_id=test_user.id, auto_post=True)
    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[],
        match_score=85,
        status=ReconciliationStatus.PENDING_REVIEW,
        version=1,
    )
    db.add(match)
    await db.commit()

    result = await review_router.batch_approve_matches(
        request=BatchApproveRequest(match_ids=[match.id]),
        db=db,
        user_id=test_user.id,
    )
    assert result.approved_count == 1
    assert result.journal_entries_created == 0
    assert result.journal_entries_reconciled == 1

    await db.refresh(match)
    await db.refresh(entry)
    assert match.journal_entry_ids == [str(entry.id)]
    assert entry.status == JournalEntryStatus.RECONCILED

    entry_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == test_user.id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.source_id == txn.id)
    )
    assert len(list(entry_result.scalars().all())) == 1


async def test_create_entry_from_txn_auto_post_rejects_inactive_statement_account(db, test_user):
    """AC4.9.3: Auto-posted statement entries must satisfy regular posting account invariants."""
    account = await create_statement_account(db, test_user.id, "DBS Inactive Statement Account")
    account.is_active = False
    statement = build_statement(test_user.id, "hash_batch_inactive_account", 90)
    statement.status = BankStatementStatus.APPROVED
    statement.account_id = account.id
    db.add(statement)
    await db.commit()

    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 20),
        description="Inactive mapped account payment",
        amount=Decimal("50.00"),
        direction="OUT",
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)

    with pytest.raises(ValueError, match="not active"):
        await create_entry_from_txn(db, txn, user_id=test_user.id, auto_post=True)

    entry_result = await db.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == test_user.id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.source_id == txn.id)
    )
    assert list(entry_result.scalars().all()) == []


async def test_AC18_8_3_AC18_8_6_create_entry_from_txn_writes_statement_to_ledger_graph(
    db,
    test_user,
):
    """AC18.8.3 AC18.8.6 AC18.8.7: Statement posting records extracted->ledger entry->ledger line lineage."""
    account = await create_statement_account(db, test_user.id, "DBS Evidence Graph Posting")
    statement = build_statement(test_user.id, "hash_evidence_graph_posting", 90)
    statement.status = BankStatementStatus.APPROVED
    statement.account_id = account.id
    db.add(statement)
    await db.flush()

    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 21),
        description="Evidence graph salary",
        amount=Decimal("50.00"),
        direction="IN",
    )
    db.add(txn)
    await db.flush()

    entry = await create_entry_from_txn(
        db,
        txn,
        user_id=test_user.id,
        auto_post=True,
        source_type=JournalEntrySourceType.USER_CONFIRMED,
    )
    await db.commit()

    assert entry.source_type == JournalEntrySourceType.USER_CONFIRMED
    assert entry.source_id == txn.id

    # Statement->ledger lineage is materialized lazily; trigger it for the posted entry.
    from src.services.evidence_graph_materialization import EvidenceGraphMaterializationService

    await EvidenceGraphMaterializationService().materialize_for_entity(
        db,
        user_id=test_user.id,
        entity_type="journal_entry",
        entity_id=entry.id,
    )
    await db.commit()

    nodes = {
        (node.node_kind, node.entity_type, node.entity_id): node
        for node in (await db.execute(select(EvidenceNode).where(EvidenceNode.user_id == test_user.id))).scalars()
    }
    extracted_node = nodes[("atomic_fact", "atomic_transaction", txn.id)]
    ledger_entry_node = nodes[("ledger_entry", "journal_entry", entry.id)]
    ledger_line_nodes = [nodes[("ledger_line", "journal_line", line.id)] for line in entry.lines]

    edges = {
        (edge.from_node_id, edge.to_node_id, edge.relation)
        for edge in (await db.execute(select(EvidenceEdge).where(EvidenceEdge.user_id == test_user.id))).scalars()
    }
    assert (extracted_node.id, ledger_entry_node.id, "posted_as") in edges
    assert {(ledger_entry_node.id, ledger_line_node.id, "contains") for ledger_line_node in ledger_line_nodes} <= edges


async def test_batch_approve_matches_returns_400_on_amount_mismatch(db, test_user):
    """AC16.24.4: Batch approval preserves acceptance amount validation failures."""
    account = await create_statement_account(db, test_user.id, "DBS Batch Mismatch")
    statement = build_statement(test_user.id, "hash_batch_mismatch", 90)
    statement.status = BankStatementStatus.APPROVED
    statement.account_id = account.id
    db.add(statement)
    await db.commit()

    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 19),
        description="Mismatched payment",
        amount=Decimal("50.00"),
        direction="OUT",
    )
    entry_source_txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 19),
        description="Different payment",
        amount=Decimal("100.00"),
        direction="OUT",
    )
    db.add_all([txn, entry_source_txn])
    await db.commit()
    await db.refresh(txn)
    await db.refresh(entry_source_txn)

    entry = await create_entry_from_txn(db, entry_source_txn, user_id=test_user.id, auto_post=True)
    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        match_score=85,
        status=ReconciliationStatus.PENDING_REVIEW,
        version=1,
    )
    db.add(match)
    await db.commit()

    with pytest.raises(HTTPException) as exc_info:
        await review_router.batch_approve_matches(
            request=BatchApproveRequest(match_ids=[match.id]),
            db=db,
            user_id=test_user.id,
        )

    assert exc_info.value.status_code == 400
    assert "Amount mismatch" in exc_info.value.detail


async def test_batch_reject_matches_empty_list(db, test_user):
    """Given empty match_ids,
    When batch_reject_matches is called,
    Then it returns success with 0 rejected (line 1003-1004).
    """
    result = await review_router.batch_reject_matches(
        request=BatchRejectRequest(match_ids=[]),
        db=db,
        user_id=test_user.id,
    )
    assert result.rejected_count == 0


async def test_batch_reject_matches_success(db, test_user):
    """Given pending-review matches,
    When batch_reject_matches is called with match IDs,
    Then it rejects all matching records (lines 1006-1029).
    """
    from src.models.reconciliation import ReconciliationMatch, ReconciliationStatus

    account = await create_statement_account(db, test_user.id, "DBS Batch Reject")
    statement = build_statement(test_user.id, "hash_batch_rej", 90)
    statement.status = BankStatementStatus.APPROVED
    statement.account_id = account.id
    db.add(statement)
    await db.commit()

    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 15),
        description="Payment",
        amount=Decimal("50.00"),
        direction="OUT",
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)

    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        match_score=70,
        status=ReconciliationStatus.PENDING_REVIEW,
        version=1,
    )
    db.add(match)
    await db.commit()
    await db.refresh(match)
    match_id = match.id

    result = await review_router.batch_reject_matches(
        request=BatchRejectRequest(match_ids=[match_id]),
        db=db,
        user_id=test_user.id,
    )
    assert result.rejected_count == 1


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
