from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import func, select
from src.config import settings
from src.extraction import (
    BankStatementStatus,
    DocumentSource,
    DocumentStatus,
    ExtractedTransactionRow,
    ExtractionError,
    ParseJob,
    Stage1Status,
    TransactionDirection,
    UploadedDocument,
    get_current_statement_extraction_result,
)
from src.extraction.extension import (
    statement_parsing as statement_parsing_mod,
    statement_pipeline,
    statement_validation as statement_validation_mod,
)
from src.extraction.orm.evidence import EvidenceNode
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import JournalEntry, JournalEntryStatus, JournalLine
from src.llm.base import Modality, ModelSpec
from src.runtime import StorageError
from tests.api._statement_router_fixtures import (
    _compose_mock_ingestion,
    build_statement,
    create_statement_account,
    persist_mock_result,
    seed_uploaded_document,
)
from tests.api.conftest import DummyStorage
from tests.factories import AccountFactory, UserFactory

pytestmark = pytest.mark.asyncio  # AC-platform.29.5


def _post_upload(client: AsyncClient, filename: str, content: bytes, *, institution: str | None = "DBS", account_id=None, model: str | None = None):
    data = {}
    if institution is not None:
        data["institution"] = institution
    if account_id is not None:
        data["account_id"] = str(account_id)
    if model is not None:
        data["model"] = model
    content_type = "text/csv" if filename.endswith(".csv") else "application/pdf"
    return client.post("/statements", files={"file": (filename, content, content_type)}, data=data)


async def wait_for_background_tasks() -> None:
    await statement_pipeline.wait_for_parse_tasks()


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
        monkeypatch.setattr(statement_parsing_mod.ExtractionService, "parse_document", AsyncMock(side_effect=side_effect))
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
        hints=None,
    ):
        score = confidence_score(source.content_hash) if callable(confidence_score) else confidence_score
        stmt = build_statement(test_user_id, source.content_hash, confidence_score=score)
        if status is not None:
            stmt.status = status
        if account_id is not None:
            stmt.account_id = account_id
        if modifier:
            modifier(stmt, source)
        txns = transactions(source) if callable(transactions) else transactions or []
        return await persist_mock_result(db, source=source, statement=stmt, transactions=txns)

    monkeypatch.setattr(statement_parsing_mod.ExtractionService, "parse_document", fake_parse)


async def test_upload_statement_duplicate(client: AsyncClient, monkeypatch, storage_stub, model_catalog_stub, test_user):
    "AC-extraction.5.4"
    content = b"duplicate-statement"
    _patch_parse_document(monkeypatch, test_user.id)
    first = await _post_upload(client, "statement.pdf", content, institution="DBS", model="google/gemini-3-flash-preview")
    assert first.status_code == status.HTTP_202_ACCEPTED, first.text
    await wait_for_background_tasks()

    dup = await _post_upload(client, "statement.pdf", content, institution="DBS", model="google/gemini-3-flash-preview")
    assert dup.status_code == status.HTTP_409_CONFLICT


async def test_upload_storage_failure(client: AsyncClient, monkeypatch, model_catalog_stub):
    "AC-extraction.5.5"
    mock_storage = MagicMock()
    mock_storage.upload_bytes.side_effect = StorageError("S3 Down")
    monkeypatch.setattr("src.routers.statements.StorageService", MagicMock(return_value=mock_storage))

    resp = await _post_upload(client, "statement.pdf", b"content", institution="DBS", model="google/gemini-3-flash-preview")
    assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert "S3 Down" in resp.json()["detail"]


async def test_upload_invalid_extension(client: AsyncClient):
    "AC-extraction.5.6"
    resp = await _post_upload(client, "statement.exe", b"content", institution="DBS")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "Unsupported file type" in resp.json()["detail"]


async def test_AC3_5_upload_rejects_cross_user_account_id(client: AsyncClient, db, monkeypatch):
    other_user = await UserFactory.create_async(db)
    other_account = await AccountFactory.create_async(db, user_id=other_user.id, name="Other User Cash")
    await db.commit()
    mock_storage = MagicMock()
    monkeypatch.setattr("src.routers.statements.StorageService", MagicMock(return_value=mock_storage))

    resp = await _post_upload(client, "statement.pdf", b"content", institution="DBS", account_id=other_account.id)
    assert resp.status_code == status.HTTP_404_NOT_FOUND
    assert resp.json()["detail"] == "Account not found"
    assert mock_storage.upload_bytes.call_count == 0


async def test_upload_uses_default_ocr_pipeline_for_pdf(client: AsyncClient, monkeypatch, storage_stub, test_user):
    "AC-extraction.5.7"
    mock_parse = AsyncMock(return_value=None)
    monkeypatch.setattr(statement_pipeline, "compose_statement_ingestion_use_case", _compose_mock_ingestion(mock_parse))

    resp = await _post_upload(client, "statement.pdf", b"content", institution="DBS")
    assert resp.status_code == status.HTTP_202_ACCEPTED, resp.text
    created = resp.json()
    await wait_for_background_tasks()
    assert created["status"] == BankStatementStatus.PARSING.value
    job = mock_parse.await_args.kwargs["job"]
    assert isinstance(job, ParseJob)
    assert job.model is None
    storage_key = job.storage_key
    assert storage_key.startswith(f"statements/{created['id']}/")
    assert "statement.pdf" not in storage_key
    assert str(test_user.id) not in storage_key
    assert storage_key.endswith(".pdf")


async def test_AC_extraction_1913_9_upload_registers_source_before_dispatch(
    client: AsyncClient, db, monkeypatch, storage_stub
):
    "AC-extraction.1913.9"
    mock_parse = AsyncMock(return_value=None)
    monkeypatch.setattr(statement_pipeline, "compose_statement_ingestion_use_case", _compose_mock_ingestion(mock_parse))

    resp = await _post_upload(client, "june-statement.csv", b"date,amount\n2026-06-01,10.00\n", institution="DBS")
    assert resp.status_code == status.HTTP_202_ACCEPTED, resp.text
    created = resp.json()
    statement = await db.get(StatementSummary, created["id"])
    assert statement is not None
    assert statement.uploaded_document_id is not None
    document = await db.get(UploadedDocument, statement.uploaded_document_id)
    assert document is not None
    assert document.original_filename == "june-statement.csv"
    assert document.file_path == created["file_path"]
    assert document.status is DocumentStatus.UPLOADED
    assert created["original_filename"] == document.original_filename
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
    client: AsyncClient, monkeypatch, storage_stub, model_catalog_stub
):
    "AC-observability.8.1"
    content = b"audit-log-input"
    mock_parse = AsyncMock(return_value=None)
    mock_info = MagicMock()
    monkeypatch.setattr(statement_pipeline, "compose_statement_ingestion_use_case", _compose_mock_ingestion(mock_parse))
    monkeypatch.setattr("src.routers.statements.logger.info", mock_info)

    resp = await _post_upload(
        client, "staging-audit.pdf", content, institution="DBS", model="google/gemini-3-flash-preview"
    )
    assert resp.status_code == status.HTTP_202_ACCEPTED, resp.text
    created = resp.json()
    await wait_for_background_tasks()
    calls = [(call.args[0], call.kwargs) for call in mock_info.call_args_list]
    accepted = next(kwargs for event, kwargs in calls if event == "statement.upload.accepted")
    storage_saved = next(kwargs for event, kwargs in calls if event == "statement.upload.storage_saved")
    enqueued = next(kwargs for event, kwargs in calls if event == "statement.parse.enqueued")
    expected_hash_prefix = hashlib.sha256(content).hexdigest()[:12]
    assert accepted["audit_event"] == "statement.upload.accepted"
    assert accepted["request_id"]
    assert accepted["statement_id"] == created["id"]
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
    assert storage_saved["statement_id"] == created["id"]
    assert storage_saved["file_hash_prefix"] == expected_hash_prefix
    assert enqueued["audit_event"] == "statement.parse.enqueued"
    assert enqueued["request_id"] == accepted["request_id"]
    assert enqueued["statement_id"] == created["id"]
    assert enqueued["model_to_use"] == "google/gemini-3-flash-preview"
    job = mock_parse.await_args.kwargs["job"]
    assert isinstance(job, ParseJob)
    assert str(job.statement_id) == created["id"]


async def test_AC10_8_1_upload_storage_failure_logs_safe_audit_context(
    client: AsyncClient, monkeypatch, model_catalog_stub
):
    "AC-observability.8.1"
    content = b"storage-failure-input"
    mock_error = MagicMock()
    monkeypatch.setattr("src.routers.statements.logger.error", mock_error)

    class FailingStorage(DummyStorage):
        def upload_bytes(self, **_kwargs) -> None:
            raise StorageError("object store rejected upload without source bytes")

    monkeypatch.setattr("src.routers.statements.StorageService", FailingStorage)
    resp = await _post_upload(client, "staging-failure.pdf", content, institution="DBS")
    assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    failed = next(call.kwargs for call in mock_error.call_args_list if call.args[0] == "statement.upload.storage_failed")
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


async def test_AC10_8_3_statement_scoped_brokerage_import_audit_logs(client: AsyncClient, db, test_user, monkeypatch):
    "AC-observability.8.3"
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

    monkeypatch.setattr("src.routers.portfolio.logger.info", mock_info)
    monkeypatch.setattr("src.routers.portfolio._brokerage_import_service.import_positions", fake_import_positions)

    resp = await client.post("/portfolio/brokerage-imports", json={"statement_id": str(statement_id)})
    assert resp.status_code == status.HTTP_200_OK, resp.text
    calls = [(call.args[0], call.kwargs) for call in mock_info.call_args_list]
    started = next(kwargs for event, kwargs in calls if event == "statement.brokerage_import.started")
    completed = next(kwargs for event, kwargs in calls if event == "statement.brokerage_import.completed")
    assert resp.json()["created_atomic_positions"] == 1
    assert started["audit_event"] == "statement.brokerage_import.started"
    assert started["statement_id"] == str(statement_id)
    assert started["phase"] == "brokerage_import_started"
    assert started["model_to_use"] is None
    assert completed["audit_event"] == "statement.brokerage_import.completed"
    assert completed["statement_id"] == str(statement_id)
    assert completed["phase"] == "brokerage_import_completed"
    assert completed["created_atomic_positions"] == 1


async def test_upload_rejects_text_only_model(client: AsyncClient, monkeypatch):
    "AC-extraction.5.8"

    async def fake_catalog_get(self, model_id):
        return ModelSpec(id=model_id, provider_id="env", modalities=frozenset({Modality.TEXT}))

    monkeypatch.setattr("src.routers.statements.LitellmCatalog.get", fake_catalog_get)
    resp = await _post_upload(client, "statement.pdf", b"content", institution="DBS", model="text-only/model")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "does not support image/PDF inputs" in resp.json()["detail"]


async def test_pending_review_and_decisions(client: AsyncClient, db, monkeypatch, storage_stub, model_catalog_stub, test_user):
    "AC-extraction.5.10"
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
    account_id = account.id
    await db.commit()
    created_ids = []
    for index, content in enumerate(contents):
        resp = await _post_upload(
            client,
            f"statement-{index}.pdf",
            content,
            institution="DBS",
            account_id=account_id,
            model="google/gemini-3-flash-preview",
        )
        assert resp.status_code == status.HTTP_202_ACCEPTED, resp.text
        created_ids.append(resp.json()["id"])

    await wait_for_background_tasks()
    pending_resp = await client.get("/statements/pending-review")
    assert pending_resp.status_code == status.HTTP_200_OK, pending_resp.text
    pending = pending_resp.json()
    assert pending["total"] == 2
    assert {item["id"] for item in pending["items"]} == set(created_ids)
    statement_id = created_ids[0]
    source_result = await get_current_statement_extraction_result(db, user_id=test_user.id, statement_id=statement_id)
    envelope_resp = await client.post(
        f"/statements/{statement_id}/review-envelopes",
        json={
            "source_result_digest": source_result.content_digest,
            "account_id": str(account_id),
            "currency": "SGD",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "100.00",
            "closing_balance": "100.00",
            "rationale": "Reviewed the dormant original source and confirmed its balances.",
        },
    )
    assert envelope_resp.status_code == status.HTTP_200_OK, envelope_resp.text
    approved, _txns = await statement_validation_mod.approve_statement_with_transactions(db, statement_id, test_user.id)
    await db.commit()
    assert approved.status == BankStatementStatus.APPROVED
    rejected = await statement_validation_mod.reject_statement(db, statement_id, test_user.id, reason="Incorrect data")
    await db.commit()
    assert rejected.status == BankStatementStatus.REJECTED


async def test_stage1_reject_triggers_reparse(client: AsyncClient, db, monkeypatch, storage_stub, test_user):
    "AC-extraction.stage1-validation.9 AC16.22.2"
    statement = build_statement(test_user.id, "hash_stage1_reject_reparse", 70)
    statement.status = BankStatementStatus.PARSED
    db.add(statement)
    await db.flush()
    document = await seed_uploaded_document(
        db, statement, file_path="statements/reject-reparse.pdf", original_filename="reject-reparse.pdf"
    )
    statement_id = statement.id
    document_name = document.original_filename
    document_path = document.file_path
    await db.commit()
    queued: dict[str, object] = {}

    async def fake_parse_statement_background(**kwargs):
        queued.update(kwargs)

    monkeypatch.setattr(
        statement_pipeline, "compose_statement_ingestion_use_case", _compose_mock_ingestion(fake_parse_statement_background)
    )
    resp = await client.post(f"/statements/{statement_id}/rejections", json={"notes": "Needs re-parse"})
    assert resp.status_code == status.HTTP_200_OK, resp.text
    response = resp.json()
    await wait_for_background_tasks()
    assert response["status"] == BankStatementStatus.PARSING.value
    assert response["validation_error"] is None
    queued_job = queued["job"]
    assert isinstance(queued_job, ParseJob)
    assert queued_job.statement_id == statement_id
    assert queued_job.filename == document_name
    assert queued_job.user_id == test_user.id
    assert queued_job.storage_key == document_path
    assert queued["content"] == b"dummy content"
    entry_count = await db.scalar(select(func.count(JournalEntry.id)).where(JournalEntry.user_id == test_user.id))
    assert entry_count == 0, f"Expected 0 JournalEntries for rejected statement, found {entry_count}"
    line_count = await db.scalar(
        select(func.count(JournalLine.id))
        .join(JournalEntry)
        .where(JournalEntry.user_id == test_user.id)
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
    )
    assert line_count == 0, f"Expected 0 posted trial balance lines, found {line_count}"


async def test_get_statement_not_found(client: AsyncClient):
    "AC-extraction.5.11"
    resp = await client.get("/statements/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == status.HTTP_404_NOT_FOUND


async def test_upload_file_too_large(client: AsyncClient, model_catalog_stub):
    "AC-extraction.5.12"
    content = b"x" * (10 * 1024 * 1024 + 1)
    resp = await _post_upload(client, "large-statement.pdf", content, institution="DBS", model="google/gemini-3-flash-preview")
    assert resp.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    assert "10MB" in resp.json()["detail"]


async def test_upload_extraction_failure(client: AsyncClient, db, monkeypatch, model_catalog_stub, test_user):
    "AC-extraction.5.13"
    mock_storage = MagicMock()
    mock_storage.upload_bytes.return_value = None
    mock_storage.generate_presigned_url.return_value = "https://example.com/file"
    monkeypatch.setattr("src.routers.statements.StorageService", MagicMock(return_value=mock_storage))
    _patch_parse_document(monkeypatch, test_user.id, side_effect=ExtractionError("Failed to parse PDF"))

    resp = await _post_upload(client, "statement.pdf", b"content", institution="DBS", model="google/gemini-3-flash-preview")
    assert resp.status_code == status.HTTP_202_ACCEPTED, resp.text
    created = resp.json()
    await wait_for_background_tasks()
    statement = await db.get(StatementSummary, created["id"], populate_existing=True)
    assert statement is not None
    if statement.status == BankStatementStatus.PARSING:
        await asyncio.sleep(0.5)
        await db.refresh(statement)
    assert statement.status == BankStatementStatus.REJECTED


async def test_retry_statement_not_found(client: AsyncClient):
    "AC-extraction.5.14"
    resp = await client.post("/statements/00000000-0000-0000-0000-000000000000/runs", json={})
    assert resp.status_code == status.HTTP_404_NOT_FOUND


async def test_retry_rejects_text_only_model(client: AsyncClient, db, monkeypatch, test_user):
    "AC-extraction.5.15"
    statement = build_statement(test_user.id, "hash", 80)
    statement.status = BankStatementStatus.REJECTED
    db.add(statement)
    await db.commit()

    async def fake_catalog_get(self, model_id):
        return ModelSpec(id=model_id, provider_id="env", modalities=frozenset({Modality.TEXT}))

    monkeypatch.setattr("src.routers.statements.LitellmCatalog.get", fake_catalog_get)
    resp = await client.post(f"/statements/{statement.id}/runs", json={"model": "text-only/model"})
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "does not support image/PDF inputs" in resp.json()["detail"]


@pytest.mark.parametrize("prior_status", [BankStatementStatus.REJECTED, BankStatementStatus.PARSED, BankStatementStatus.PARSING])
@pytest.mark.parametrize("source_available", [True, False])
async def test_retry_statement_storage_failure(
    client: AsyncClient, db, monkeypatch, test_user, prior_status, source_available
):
    "AC-extraction.5.16"
    statement = build_statement(test_user.id, "hash", 80)
    statement.status = prior_status
    statement.validation_error = "Original review failure"
    db.add(statement)
    await db.flush()
    if source_available:
        await seed_uploaded_document(db, statement, file_path="path/to/file.pdf")
    await db.commit()
    mock_storage = MagicMock()
    mock_storage.get_object.side_effect = StorageError("S3 Down")
    monkeypatch.setattr("src.routers.statements.StorageService", MagicMock(return_value=mock_storage))
    submit = AsyncMock()
    monkeypatch.setattr("src.routers.statements.submit_parse_pipeline", submit)

    resp = await client.post(f"/statements/{statement.id}/runs", json={})
    assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert "Failed to fetch file from storage" in resp.json()["detail"]
    await db.refresh(statement)
    assert statement.status == prior_status
    assert statement.validation_error == "Original review failure"
    submit.assert_not_awaited()


async def test_retry_statement_invalid_status(
    client: AsyncClient, db, monkeypatch, storage_stub, model_catalog_stub, test_user
):
    "AC-extraction.5.17"
    _patch_parse_document(monkeypatch, test_user.id, status=BankStatementStatus.PARSING)
    upload_resp = await _post_upload(
        client, "statement.pdf", b"statement", institution="DBS", model="google/gemini-3-flash-preview"
    )
    assert upload_resp.status_code == status.HTTP_202_ACCEPTED, upload_resp.text
    created_id = upload_resp.json()["id"]
    await wait_for_background_tasks()
    statement = await db.get(StatementSummary, created_id, populate_existing=True)
    statement.status = BankStatementStatus.UPLOADED
    await db.commit()

    resp = await client.post(f"/statements/{created_id}/runs", json={})
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "stuck parsing statements" in resp.json()["detail"]


async def test_retry_statement_parsing_allowed(client: AsyncClient, db, storage_stub, test_user):
    "AC-extraction.5.18"
    sid = uuid4()
    statement = StatementSummary(
        id=sid, user_id=test_user.id, status=BankStatementStatus.PARSING, file_hash="h_parsing", institution="DBS"
    )
    db.add(statement)
    await db.flush()
    await seed_uploaded_document(db, statement, file_path="p", original_filename="f.pdf")
    await db.commit()

    with patch("src.routers.statements.StorageService") as mock_storage_cls:
        mock_storage_cls.return_value.get_object.return_value = b"content"
        resp = await client.post(f"/statements/{sid}/runs", json={})
        assert resp.status_code == status.HTTP_202_ACCEPTED, resp.text
        await db.refresh(statement)
        assert resp.json()["state"] in ("requested", "running")
        assert statement.status == BankStatementStatus.PARSING
        await wait_for_background_tasks()


async def test_AC13_21_3_retry_accepts_parsed_resting_state(client: AsyncClient, db, storage_stub, test_user):
    "AC-extraction.121.3"
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
        mock_storage_cls.return_value.get_object.return_value = b"content"
        resp = await client.post(f"/statements/{sid}/runs", json={})
        assert resp.status_code == status.HTTP_202_ACCEPTED, resp.text
        await db.refresh(statement)
        assert (resp.json()["kind"], resp.json()["trigger"]) == ("extract", "rerun")
        assert statement.status == BankStatementStatus.PARSING
        await wait_for_background_tasks()


async def test_AC13_21_6_csv_missing_institution_rejected_sync(client: AsyncClient, storage_stub):
    "AC-extraction.121.6"
    resp = await _post_upload(client, "statement.csv", b"date,amount\n2025-01-01,10.00\n", institution=None)
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "institution" in resp.json()["detail"].lower()


async def test_retry_statement_success(client: AsyncClient, db, monkeypatch, storage_stub, model_catalog_stub, test_user):
    "AC-extraction.5.19"
    _patch_parse_document(monkeypatch, test_user.id, confidence_score=60, status=BankStatementStatus.REJECTED)
    upload_resp = await _post_upload(
        client, "statement.pdf", b"statement", institution="DBS", model="google/gemini-3-flash-preview"
    )
    assert upload_resp.status_code == status.HTTP_202_ACCEPTED, upload_resp.text
    created_id = upload_resp.json()["id"]
    await wait_for_background_tasks()
    rejected = await statement_validation_mod.reject_statement(db, created_id, test_user.id, reason="Low confidence")
    await db.commit()
    assert rejected.status == BankStatementStatus.REJECTED

    _patch_parse_document(monkeypatch, test_user.id, confidence_score=95)
    retry_resp = await client.post(f"/statements/{created_id}/runs", json={"model": "google/gemini-2.0-flash-exp:free"})
    assert retry_resp.status_code == status.HTTP_202_ACCEPTED, retry_resp.text
    await wait_for_background_tasks()


async def test_retry_statement_extraction_failure(
    client: AsyncClient, db, monkeypatch, storage_stub, model_catalog_stub, test_user
):
    "AC-extraction.5.20"
    _patch_parse_document(monkeypatch, test_user.id, status=BankStatementStatus.REJECTED)
    upload_resp = await _post_upload(
        client, "statement.pdf", b"statement", institution="DBS", model="google/gemini-3-flash-preview"
    )
    assert upload_resp.status_code == status.HTTP_202_ACCEPTED, upload_resp.text
    created_id = upload_resp.json()["id"]
    await wait_for_background_tasks()
    rejected = await statement_validation_mod.reject_statement(db, created_id, test_user.id, reason="Low confidence")
    await db.commit()
    assert rejected.status == BankStatementStatus.REJECTED

    async def fake_retry_fail(*_args, **_kwargs):
        raise ExtractionError("Retry failed")

    monkeypatch.setattr(statement_parsing_mod.ExtractionService, "parse_document", fake_retry_fail)
    resp = await client.post(f"/statements/{created_id}/runs", json={"model": "google/gemini-2.0-flash-exp:free"})
    assert resp.status_code == status.HTTP_202_ACCEPTED, resp.text
    assert resp.json()["state"] in ("requested", "running")
    statement = await db.get(StatementSummary, created_id, populate_existing=True)
    assert statement.status == BankStatementStatus.PARSING
    await wait_for_background_tasks()


async def test_upload_statement_rejects_invalid_model(client: AsyncClient, storage_stub, monkeypatch):
    "AC-extraction.5.21"

    async def fake_catalog_get(self, model_id):
        return None

    monkeypatch.setattr("src.routers.statements.LitellmCatalog.get", fake_catalog_get)
    resp = await _post_upload(client, "statement.pdf", b"some content", institution="DBS", model="unknown/model")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "Invalid model selection" in resp.json()["detail"]


async def test_upload_statement_rejects_model_without_image_modality(client: AsyncClient, storage_stub, monkeypatch):
    "AC-extraction.5.22"

    async def fake_catalog_get(self, model_id):
        return ModelSpec(id=model_id, provider_id="env", modalities=frozenset({Modality.TEXT}))

    monkeypatch.setattr("src.routers.statements.LitellmCatalog.get", fake_catalog_get)
    resp = await _post_upload(client, "statement.pdf", b"some content", institution="DBS", model="google/gemini-flash")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "does not support image" in resp.json()["detail"]


async def test_retry_statement_rejects_invalid_model(client: AsyncClient, db, test_user, monkeypatch, storage_stub):
    "AC-extraction.5.23"
    statement = build_statement(test_user.id, "hash", 80)
    statement.status = BankStatementStatus.REJECTED
    db.add(statement)
    await db.commit()

    async def fake_catalog_get(self, model_id):
        return None

    monkeypatch.setattr("src.routers.statements.LitellmCatalog.get", fake_catalog_get)
    resp = await client.post(f"/statements/{statement.id}/runs", json={"model": "google/gemini-flash"})
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "Invalid model selection" in resp.json()["detail"]


async def test_background_parse_error_logging(client: AsyncClient, db, monkeypatch, test_user, storage_stub):
    "AC-extraction.5.24"
    started = time.monotonic()
    monkeypatch.setattr(statement_parsing_mod, "PARSE_RETRY_DELAY_SECONDS", 0)
    _patch_parse_document(monkeypatch, test_user.id, side_effect=Exception("Fatal background error"))

    async def fake_catalog_get(self, model_id):
        return ModelSpec(id=model_id, provider_id="env", modalities=frozenset({Modality.TEXT, Modality.IMAGE}))

    monkeypatch.setattr("src.routers.statements.LitellmCatalog.get", fake_catalog_get)
    resp = await _post_upload(
        client, "statement.pdf", b"content", institution="DBS", model="google/gemini-3-flash-preview"
    )
    assert resp.status_code == status.HTTP_202_ACCEPTED, resp.text
    await wait_for_background_tasks()
    statement = await db.get(StatementSummary, resp.json()["id"], populate_existing=True)
    assert statement is not None
    assert time.monotonic() - started < 5


async def test_background_retry_error_logging(client: AsyncClient, db, monkeypatch, test_user, storage_stub):
    "AC-extraction.5.25"
    started = time.monotonic()
    monkeypatch.setattr(statement_parsing_mod, "PARSE_RETRY_DELAY_SECONDS", 0)
    statement = build_statement(test_user.id, "hash_retry", 80)
    statement.status = BankStatementStatus.REJECTED
    db.add(statement)
    await db.flush()
    await seed_uploaded_document(db, statement, file_path="path")
    await db.commit()
    _patch_parse_document(monkeypatch, test_user.id, side_effect=Exception("Fatal background retry error"))
    monkeypatch.setattr("src.routers.statements.StorageService.get_object", lambda *args, **kwargs: b"content")

    async def fake_catalog_get(self, model_id):
        return ModelSpec(id=model_id, provider_id="env", modalities=frozenset({Modality.TEXT, Modality.IMAGE}))

    monkeypatch.setattr("src.routers.statements.LitellmCatalog.get", fake_catalog_get)
    resp = await client.post(f"/statements/{statement.id}/runs", json={"model": "google/gemini-flash"})
    assert resp.status_code == status.HTTP_202_ACCEPTED, resp.text
    await wait_for_background_tasks()
    await db.refresh(statement)
    assert statement.status in (BankStatementStatus.PARSING, BankStatementStatus.REJECTED)
    assert time.monotonic() - started < 5


async def test_delete_statement_success(client: AsyncClient, db, test_user, monkeypatch):
    statement = build_statement(test_user.id, "hash_del", 90)
    db.add(statement)
    await db.flush()
    await seed_uploaded_document(db, statement, file_path="statements/user/file.pdf")
    await db.commit()
    statement_id = statement.id
    monkeypatch.setattr("src.routers.statements.StorageService", DummyStorage)

    resp = await client.delete(f"/statements/{statement_id}")
    assert resp.status_code == status.HTTP_204_NO_CONTENT
    retired = await db.get(StatementSummary, statement_id, populate_existing=True)
    assert retired is not None
    assert retired.status is BankStatementStatus.RETIRED


async def test_delete_statement_not_found(client: AsyncClient):
    resp = await client.delete("/statements/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == status.HTTP_404_NOT_FOUND


async def test_delete_statement_storage_error_still_deletes(client: AsyncClient, db, test_user, monkeypatch):
    statement = build_statement(test_user.id, "hash_del_err", 90)
    db.add(statement)
    await db.flush()
    await seed_uploaded_document(db, statement, file_path="statements/user/file.pdf")
    await db.commit()
    statement_id = statement.id
    mock_storage = MagicMock()
    mock_storage.delete_object.side_effect = StorageError("S3 Down")
    monkeypatch.setattr("src.routers.statements.StorageService", MagicMock(return_value=mock_storage))

    resp = await client.delete(f"/statements/{statement_id}")
    assert resp.status_code == status.HTTP_204_NO_CONTENT
    mock_storage.delete_object.assert_not_called()
    retired = await db.get(StatementSummary, statement_id, populate_existing=True)
    assert retired is not None
    assert retired.status is BankStatementStatus.RETIRED


async def test_get_statement_for_review(client: AsyncClient, db, test_user, monkeypatch):
    statement = build_statement(test_user.id, "hash_review", 75)
    db.add(statement)
    await db.commit()
    statement_id = statement.id
    monkeypatch.setattr("src.routers.statements.StorageService", DummyStorage)

    resp = await client.get(f"/statements/{statement_id}/review")
    assert resp.status_code == status.HTTP_200_OK, resp.text
    result = resp.json()
    assert result["id"] == str(statement_id)
    assert result["balance_validation_result"] is not None
    assert "opening_balance" in result["balance_validation_result"]
    assert "closing_match" in result["balance_validation_result"]


async def test_AC16_33_5_get_statement_document_streams_bytes_same_origin(client: AsyncClient, db, test_user, monkeypatch):
    "AC-extraction.document-delivery.2 AC16.33.5"
    statement = build_statement(test_user.id, "hash_doc_stream", 75)
    db.add(statement)
    await db.flush()
    await seed_uploaded_document(db, statement, file_path="statements/doc/preview.pdf", original_filename="moomoo.pdf")
    await db.commit()
    monkeypatch.setattr("src.routers.statements.StorageService", DummyStorage)

    resp = await client.get(f"/statements/{statement.id}/document")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.content == b"dummy content"
    assert resp.headers["content-type"].startswith("application/pdf")
    assert resp.headers["content-disposition"] == "inline"


async def test_AC16_33_5_get_statement_document_404_when_no_document(client: AsyncClient, db, test_user):
    "AC16.33.5"
    statement = build_statement(test_user.id, "hash_doc_missing", 75)
    db.add(statement)
    await db.commit()

    resp = await client.get(f"/statements/{statement.id}/document")
    assert resp.status_code == status.HTTP_404_NOT_FOUND


async def test_AC16_33_5_get_statement_document_storage_error_maps_to_502(client: AsyncClient, db, test_user, monkeypatch):
    "AC16.33.5"
    statement = build_statement(test_user.id, "hash_doc_storage_err", 75)
    db.add(statement)
    await db.flush()
    await seed_uploaded_document(db, statement, file_path="statements/doc/err.pdf")
    await db.commit()
    mock_storage = MagicMock()
    mock_storage.get_object.side_effect = StorageError("S3 Down")
    monkeypatch.setattr("src.routers.statements.StorageService", MagicMock(return_value=mock_storage))

    resp = await client.get(f"/statements/{statement.id}/document")
    assert resp.status_code == status.HTTP_502_BAD_GATEWAY


async def test_get_statement_for_review_not_found(client: AsyncClient):
    resp = await client.get("/statements/00000000-0000-0000-0000-000000000000/review")
    assert resp.status_code == status.HTTP_404_NOT_FOUND


async def test_get_statement_for_review_storage_error(client: AsyncClient, db, test_user, monkeypatch):
    statement = build_statement(test_user.id, "hash_review_s3", 75)
    db.add(statement)
    await db.commit()
    statement_id = statement.id
    mock_storage = MagicMock()
    mock_storage.generate_presigned_url.side_effect = StorageError("S3 Down")
    monkeypatch.setattr("src.routers.statements.StorageService", MagicMock(return_value=mock_storage))

    resp = await client.get(f"/statements/{statement_id}/review")
    assert resp.status_code == status.HTTP_200_OK
    result = resp.json()
    assert result["id"] == str(statement_id)
    assert result["pdf_url"] is None


async def test_AC16_33_4_get_statement_for_review_uses_short_presign_ttl(client: AsyncClient, db, test_user, monkeypatch):
    "AC-extraction.document-delivery.1 AC16.33.4"
    statement = build_statement(test_user.id, "hash_review_short_presign", 75)
    db.add(statement)
    await db.flush()
    document = await seed_uploaded_document(db, statement, file_path="statements/review/short-presign.pdf")
    document_path = document.file_path
    await db.commit()
    mock_storage = MagicMock()
    mock_storage.generate_presigned_url.return_value = "https://example.com/file"
    monkeypatch.setattr("src.routers.statements.StorageService", MagicMock(return_value=mock_storage))

    resp = await client.get(f"/statements/{statement.id}/review")
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["pdf_url"] == "https://example.com/file"
    mock_storage.generate_presigned_url.assert_called_once_with(
        key=document_path, expires_in=settings.statement_review_presign_expiry_seconds, public=True
    )


async def test_retry_statement_invalid_model(client: AsyncClient, db, monkeypatch, storage_stub, test_user):
    statement = build_statement(test_user.id, "hash_retry_inv", 80)
    statement.status = BankStatementStatus.REJECTED
    db.add(statement)
    await db.commit()

    async def fake_catalog_get(self, model_id):
        return None

    monkeypatch.setattr("src.routers.statements.LitellmCatalog.get", fake_catalog_get)
    resp = await client.post(f"/statements/{statement.id}/runs", json={"model": "unknown/model"})
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "Invalid model selection" in resp.json()["detail"]


async def test_list_and_transactions_flow(client: AsyncClient, monkeypatch, storage_stub, model_catalog_stub, test_user):
    "AC-extraction.5.9"
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
            test_user.id, txn_date, amount, direction, description
        ),
    )
    _patch_parse_document(monkeypatch, test_user.id, transactions=[transaction])
    monkeypatch.setattr(
        "src.routers.statements.StorageService.generate_presigned_url",
        lambda self, key=None, expires_in=None, **kwargs: "http://fake.url",
    )

    upload_resp = await _post_upload(
        client, "statement.pdf", b"statement-flow", institution="DBS", model="google/gemini-3-flash-preview"
    )
    assert upload_resp.status_code == status.HTTP_202_ACCEPTED, upload_resp.text
    statement_id = upload_resp.json()["id"]
    await wait_for_background_tasks()

    listed_resp = await client.get("/statements")
    assert listed_resp.status_code == status.HTTP_200_OK
    listed = listed_resp.json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == statement_id

    fetched_resp = await client.get(f"/statements/{statement_id}")
    assert fetched_resp.status_code == status.HTTP_200_OK
    fetched = fetched_resp.json()
    assert fetched["id"] == statement_id
    assert len(fetched["transactions"]) == 1
    assert fetched["transactions"][0]["description"] == "Salary"
    assert fetched["transactions"][0]["source_row"] == 1
