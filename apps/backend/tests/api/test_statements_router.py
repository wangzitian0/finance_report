from __future__ import annotations

import hashlib
import time
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

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
from src.extraction.extension.deduplication import DeduplicationService
from src.extraction.orm.evidence import EvidenceNode
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import JournalEntry, JournalEntryStatus, JournalLine
from src.runtime import StorageError
from tests.api._statement_router_fixtures import (
    _compose_mock_ingestion,
    add_statement,
    build_statement,
    create_statement_account,
    failing_storage,
    persist_mock_result,
    seed_uploaded_document,
)
from tests.api.conftest import DummyStorage
from tests.factories import AccountFactory, UserFactory

pytestmark = pytest.mark.asyncio

_ZERO_UUID = "00000000-0000-0000-0000-000000000000"
_FLASH_MODEL = "google/gemini-3-flash-preview"


def _post_upload(
    client: AsyncClient,
    filename: str,
    content: bytes,
    *,
    institution: str | None = "DBS",
    account_id=None,
):
    data = {k: str(v) for k, v in (("institution", institution), ("account_id", account_id)) if v is not None}
    return client.post(
        "/statements",
        files={"file": (filename, content, "text/csv" if filename.endswith(".csv") else "application/pdf")},
        data=data,
    )


def _patch_parse_document(
    monkeypatch, test_user_id, *, confidence_score=90, transactions=None, side_effect=None, modifier=None
):
    if side_effect is not None:
        monkeypatch.setattr(
            statement_parsing_mod.ExtractionService, "parse_documents", AsyncMock(side_effect=side_effect)
        )
        return

    async def fake_parse(self, source: DocumentSource, institution, *, user_id, db=None, **_kw):
        stmt = build_statement(
            test_user_id,
            source.content_hash,
            confidence_score=confidence_score(source.content_hash) if callable(confidence_score) else confidence_score,
        )
        if modifier:
            modifier(stmt, source)
        return [await persist_mock_result(db, source=source, statement=stmt, transactions=transactions or [])]

    monkeypatch.setattr(statement_parsing_mod.ExtractionService, "parse_documents", fake_parse)


async def test_upload_statement_duplicate(client: AsyncClient, monkeypatch, storage_stub, test_user):
    _patch_parse_document(monkeypatch, test_user.id)
    assert (await _post_upload(client, "statement.pdf", b"duplicate-statement")).status_code == status.HTTP_202_ACCEPTED
    await statement_pipeline.wait_for_parse_tasks()
    assert (await _post_upload(client, "statement.pdf", b"duplicate-statement")).status_code == status.HTTP_409_CONFLICT


@pytest.mark.parametrize(
    ("filename", "content", "institution", "expected_status", "detail_part"),
    [
        ("statement.exe", b"content", "DBS", status.HTTP_400_BAD_REQUEST, "unsupported file type"),
        (
            "large-statement.pdf",
            b"x" * (10 * 1024 * 1024 + 1),
            "DBS",
            status.HTTP_413_CONTENT_TOO_LARGE,
            "10mb",
        ),
        (
            "statement.csv",
            b"date,amount\n2025-01-01,10.00\n",
            None,
            status.HTTP_400_BAD_REQUEST,
            "institution",
        ),
    ],
    ids=["bad_ext", "too_large", "missing_inst"],
)
async def test_upload_validation_rejections(
    client: AsyncClient,
    storage_stub,
    filename,
    content,
    institution,
    expected_status,
    detail_part,
):
    resp = await _post_upload(client, filename, content, institution=institution)
    assert resp.status_code == expected_status and detail_part in resp.json()["detail"].lower()


async def test_upload_file_too_large(client: AsyncClient, storage_stub, test_user, monkeypatch):
    """#2956: Streamed upload enforces 10MB ceiling in bounded chunks and accepts exact 10MB files."""
    from starlette.datastructures import UploadFile

    read_sizes: list[int] = []
    original_read = UploadFile.read

    async def spy_read(self, size: int = -1):
        read_sizes.append(size)
        return await original_read(self, size)

    monkeypatch.setattr(UploadFile, "read", spy_read)
    content = b"x" * (10 * 1024 * 1024 + 1)
    resp = await _post_upload(client, "large-statement.pdf", content, institution="DBS")
    assert resp.status_code == status.HTTP_413_CONTENT_TOO_LARGE
    assert "10MB" in resp.json()["detail"]
    assert read_sizes and all(0 < size <= 10 * 1024 * 1024 + 1 for size in read_sizes), f"Unbounded read: {read_sizes}"

    read_sizes.clear()
    exact = b"y" * (10 * 1024 * 1024)
    _patch_parse_document(monkeypatch, test_user.id)
    ok_resp = await _post_upload(client, "exact-10mb.pdf", exact, institution="DBS")
    assert ok_resp.status_code == status.HTTP_202_ACCEPTED
    await statement_pipeline.wait_for_parse_tasks()
    assert read_sizes and all(0 < size <= 10 * 1024 * 1024 + 1 for size in read_sizes)


async def test_upload_rejects_cross_user_account_id(client: AsyncClient, db, monkeypatch):
    other_user = await UserFactory.create_async(db)
    other_account = await AccountFactory.create_async(db, user_id=other_user.id, name="Other User Cash")
    await db.commit()
    mock_storage = MagicMock()
    monkeypatch.setattr("src.routers.statements.StorageService", MagicMock(return_value=mock_storage))

    resp = await _post_upload(client, "statement.pdf", b"content", account_id=other_account.id)
    assert resp.status_code == status.HTTP_404_NOT_FOUND and resp.json()["detail"] == "Account not found"
    assert mock_storage.upload_bytes.call_count == 0


async def test_upload_ocr_pipeline_source_and_audit_logs(client: AsyncClient, db, monkeypatch, storage_stub, test_user):
    content = b"audit-log-input"
    mock_parse, mock_info = AsyncMock(return_value=None), MagicMock()
    monkeypatch.setattr("src.composition.compose_statement_ingestion_use_case", _compose_mock_ingestion(mock_parse))
    monkeypatch.setattr("src.routers.statements.logger.info", mock_info)

    assert (resp := await _post_upload(client, "staging-audit.pdf", content)).status_code == status.HTTP_202_ACCEPTED
    created = resp.json()
    document = await db.get(UploadedDocument, (await db.get(StatementSummary, created["id"])).uploaded_document_id)
    source_node = (
        await db.execute(
            select(EvidenceNode).where(
                EvidenceNode.entity_type == "uploaded_document", EvidenceNode.entity_id == document.id
            )
        )
    ).scalar_one()
    assert (
        created["status"],
        document.original_filename,
        document.file_path,
        document.status,
        source_node.properties["original_filename"],
    ) == (
        BankStatementStatus.PARSING.value,
        "staging-audit.pdf",
        created["file_path"],
        DocumentStatus.UPLOADED,
        "staging-audit.pdf",
    )
    await statement_pipeline.wait_for_parse_tasks()
    job = mock_parse.await_args.kwargs["job"]
    assert isinstance(job, ParseJob) and str(job.statement_id) == created["id"]
    assert (
        job.storage_key.startswith(f"statements/{created['id']}/")
        and job.storage_key.endswith(".pdf")
        and "staging-audit.pdf" not in job.storage_key
        and str(test_user.id) not in job.storage_key
    )

    by_event = {call.args[0]: call.kwargs for call in mock_info.call_args_list}
    prefix = hashlib.sha256(content).hexdigest()[:12]
    accepted = by_event["statement.upload.accepted"]
    assert accepted["request_id"] and "content" not in accepted
    for event, expected in (
        (
            "statement.upload.accepted",
            {
                "audit_event": "statement.upload.accepted",
                "statement_id": created["id"],
                "filename": "staging-audit.pdf",
                "file_type": "pdf",
                "institution": "DBS",
                "file_size_bytes": len(content),
                "file_hash_prefix": prefix,
            },
        ),
        (
            "statement.upload.storage_saved",
            {
                "audit_event": "statement.upload.storage_saved",
                "request_id": accepted["request_id"],
                "statement_id": created["id"],
                "file_hash_prefix": prefix,
            },
        ),
        (
            "statement.parse.enqueued",
            {
                "audit_event": "statement.parse.enqueued",
                "request_id": accepted["request_id"],
                "statement_id": created["id"],
            },
        ),
    ):
        assert by_event[event].items() >= expected.items()


async def test_upload_storage_failure_logs_safe_audit_context(client: AsyncClient, monkeypatch):
    content, mock_error = b"storage-failure-input", MagicMock()
    monkeypatch.setattr("src.routers.statements.logger.error", mock_error)
    failing_storage(monkeypatch, detail="object store rejected upload without source bytes")

    assert (
        resp := await _post_upload(client, "staging-failure.pdf", content)
    ).status_code == status.HTTP_503_SERVICE_UNAVAILABLE and "object store rejected" in resp.json()["detail"]
    failed = next(c.kwargs for c in mock_error.call_args_list if c.args[0] == "statement.upload.storage_failed")
    assert failed["request_id"] and failed["statement_id"] and "content" not in failed
    assert (
        failed.items()
        >= {
            "audit_event": "statement.upload.storage_failed",
            "phase": "storage_upload_failed",
            "progress": None,
            "filename": "staging-failure.pdf",
            "file_type": "pdf",
            "file_size_bytes": len(content),
            "file_hash_prefix": hashlib.sha256(content).hexdigest()[:12],
            "error_type": "StorageError",
            "safe_error_message": "object store rejected upload without source bytes",
        }.items()
    )


async def test_statement_scoped_brokerage_import_audit_logs(client: AsyncClient, db, test_user, monkeypatch):
    statement = await add_statement(db, test_user.id, "manual_brokerage_audit", confidence=95, institution="Moomoo")
    await db.commit()
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
    monkeypatch.setattr("src.routers.portfolio.logger.info", mock_info)
    monkeypatch.setattr(
        "src.routers.portfolio._brokerage_import_service.import_positions", AsyncMock(return_value=result)
    )

    resp = await client.post("/portfolio/brokerage-imports", json={"statement_id": str(statement.id)})
    assert resp.status_code == status.HTTP_200_OK and resp.json()["created_atomic_positions"] == 1
    by_event = {call.args[0]: call.kwargs for call in mock_info.call_args_list}
    assert (
        by_event["statement.brokerage_import.started"].items()
        >= {
            "audit_event": "statement.brokerage_import.started",
            "statement_id": str(statement.id),
            "phase": "brokerage_import_started",
        }.items()
    )
    assert (
        by_event["statement.brokerage_import.completed"].items()
        >= {
            "audit_event": "statement.brokerage_import.completed",
            "statement_id": str(statement.id),
            "phase": "brokerage_import_completed",
            "created_atomic_positions": 1,
        }.items()
    )


async def test_pending_review_and_decisions(client: AsyncClient, db, monkeypatch, storage_stub, test_user):
    contents = [b"review-70", b"review-90"]
    score_by_hash = {hashlib.sha256(c).hexdigest(): s for c, s in zip(contents, [70, 90])}
    _patch_parse_document(
        monkeypatch,
        test_user.id,
        confidence_score=lambda h: score_by_hash[h],
        modifier=lambda s, _: setattr(s, "closing_balance", Decimal("100.00")),
    )
    account = await create_statement_account(db, test_user.id, "Review Queue Account")
    await db.commit()
    created_ids = [
        (await _post_upload(client, f"statement-{i}.pdf", c, account_id=account.id)).json()["id"]
        for i, c in enumerate(contents)
    ]
    await statement_pipeline.wait_for_parse_tasks()
    pending = (await client.get("/statements/pending-review")).json()
    assert pending["total"] == 2 and {item["id"] for item in pending["items"]} == set(created_ids)

    statement_id = created_ids[0]
    source_result = await get_current_statement_extraction_result(db, user_id=test_user.id, statement_id=statement_id)
    envelope_resp = await client.post(
        f"/statements/{statement_id}/review-envelopes",
        json={
            "source_result_digest": source_result.content_digest,
            "account_id": str(account.id),
            "currency": "SGD",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "100.00",
            "closing_balance": "100.00",
            "rationale": "Reviewed the dormant original source and confirmed its balances.",
        },
    )
    assert envelope_resp.status_code == status.HTTP_200_OK
    approved, _ = await statement_validation_mod.approve_statement_with_transactions(db, statement_id, test_user.id)
    await db.commit()
    assert approved.status == BankStatementStatus.APPROVED
    rejected = await statement_validation_mod.reject_statement(db, statement_id, test_user.id, reason="Incorrect data")
    await db.commit()
    assert rejected.status == BankStatementStatus.REJECTED


async def test_stage1_reject_triggers_reparse(client: AsyncClient, db, monkeypatch, storage_stub, test_user):
    statement = await add_statement(db, test_user.id, "hash_stage1_reject_reparse", confidence=70)
    document = await seed_uploaded_document(
        db, statement, file_path="statements/reject-reparse.pdf", original_filename="reject-reparse.pdf"
    )
    statement_id, doc_name, doc_path = statement.id, document.original_filename, document.file_path
    await db.commit()
    queued: dict[str, object] = {}

    async def fake_parse_bg(**kwargs):
        queued.update(kwargs)

    monkeypatch.setattr("src.composition.compose_statement_ingestion_use_case", _compose_mock_ingestion(fake_parse_bg))
    resp = await client.post(f"/statements/{statement_id}/rejections", json={"notes": "Needs re-parse"})
    assert resp.status_code == status.HTTP_200_OK
    await statement_pipeline.wait_for_parse_tasks()
    job = queued["job"]
    assert (resp.json()["status"], resp.json()["validation_error"]) == (BankStatementStatus.PARSING.value, None)
    assert isinstance(job, ParseJob) and (
        job.statement_id,
        job.filename,
        job.user_id,
        job.storage_key,
        queued["content"],
    ) == (statement_id, doc_name, test_user.id, doc_path, b"dummy content")
    assert await db.scalar(select(func.count(JournalEntry.id)).where(JournalEntry.user_id == test_user.id)) == 0
    assert (
        await db.scalar(
            select(func.count(JournalLine.id))
            .join(JournalEntry)
            .where(
                JournalEntry.user_id == test_user.id,
                JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]),
            )
        )
        == 0
    )


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("GET", f"/statements/{_ZERO_UUID}", {}),
        ("POST", f"/statements/{_ZERO_UUID}/runs", {"json": {}}),
        ("DELETE", f"/statements/{_ZERO_UUID}", {}),
        ("GET", f"/statements/{_ZERO_UUID}/review", {}),
    ],
)
async def test_statement_not_found_endpoints(client: AsyncClient, method, path, kwargs):
    assert (await client.request(method, path, **kwargs)).status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.parametrize(
    "prior_status", [BankStatementStatus.REJECTED, BankStatementStatus.PARSED, BankStatementStatus.PARSING]
)
@pytest.mark.parametrize("source_available", [True, False])
async def test_retry_statement_storage_failure(
    client: AsyncClient, db, monkeypatch, test_user, prior_status, source_available
):
    statement = await add_statement(
        db, test_user.id, "hash", confidence=80, status=prior_status, validation_error="Original review failure"
    )
    if source_available:
        await seed_uploaded_document(db, statement, file_path="path/to/file.pdf")
    await db.commit()
    failing_storage(monkeypatch, method="get_object")
    submit = AsyncMock()
    monkeypatch.setattr("src.routers.statements.submit_parse_pipeline", submit)

    resp = await client.post(f"/statements/{statement.id}/runs", json={})
    await db.refresh(statement)
    assert (
        resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        and "Failed to fetch file from storage" in resp.json()["detail"]
    )
    assert (statement.status, statement.validation_error) == (prior_status, "Original review failure")
    submit.assert_not_awaited()


async def test_retry_statement_invalid_status(client: AsyncClient, db, test_user):
    statement = await add_statement(db, test_user.id, "hash_inv_status", status=BankStatementStatus.UPLOADED)
    await db.commit()
    resp = await client.post(f"/statements/{statement.id}/runs", json={})
    assert resp.status_code == status.HTTP_400_BAD_REQUEST and "stuck parsing statements" in resp.json()["detail"]


@pytest.mark.parametrize(
    ("stmt_status", "extra"),
    [
        (BankStatementStatus.PARSING, {}),
        (
            BankStatementStatus.PARSED,
            {
                "stage1_status": Stage1Status.PENDING_REVIEW,
                "balance_validated": False,
                "validation_error": "Balance mismatch",
            },
        ),
    ],
)
async def test_retry_statement_allowed_states(client: AsyncClient, db, storage_stub, test_user, stmt_status, extra):
    statement = await add_statement(db, test_user.id, f"h_{stmt_status.value}", status=stmt_status, **extra)
    await seed_uploaded_document(db, statement, file_path="p", original_filename="f.pdf")
    await db.commit()
    resp = await client.post(f"/statements/{statement.id}/runs", json={})
    await db.refresh(statement)
    assert resp.status_code == status.HTTP_202_ACCEPTED and resp.json()["state"] in ("requested", "running")
    assert (resp.json()["kind"], resp.json()["trigger"], statement.status) == (
        "extract",
        "rerun",
        BankStatementStatus.PARSING,
    )
    await statement_pipeline.wait_for_parse_tasks()


@pytest.mark.parametrize("fail_retry", [False, True])
async def test_retry_statement_completion_and_failure(
    client: AsyncClient, db, monkeypatch, storage_stub, test_user, fail_retry
):
    _patch_parse_document(monkeypatch, test_user.id, confidence_score=60)
    upload_resp = await _post_upload(client, "statement.pdf", b"statement-retry")
    assert upload_resp.status_code == status.HTTP_202_ACCEPTED
    stmt_id = upload_resp.json()["id"]
    await statement_pipeline.wait_for_parse_tasks()
    rejected = await statement_validation_mod.reject_statement(db, stmt_id, test_user.id, reason="Low confidence")
    await db.commit()
    assert rejected.status == BankStatementStatus.REJECTED

    _patch_parse_document(
        monkeypatch,
        test_user.id,
        confidence_score=95,
        side_effect=ExtractionError("Retry failed") if fail_retry else None,
    )
    resp = await client.post(f"/statements/{stmt_id}/runs", json={})
    assert resp.status_code == status.HTTP_202_ACCEPTED
    if fail_retry:
        refreshed = await db.get(StatementSummary, stmt_id, populate_existing=True)
        assert resp.json()["state"] in ("requested", "running") and refreshed.status == BankStatementStatus.PARSING
    await statement_pipeline.wait_for_parse_tasks()


@pytest.mark.parametrize(
    ("is_retry", "exc"),
    [
        (False, ExtractionError("Failed to parse PDF")),
        (False, Exception("Fatal background error")),
        (True, Exception("Fatal background retry error")),
    ],
)
async def test_background_parse_error_logging(
    client: AsyncClient, db, monkeypatch, test_user, storage_stub, is_retry, exc
):
    started = time.monotonic()
    monkeypatch.setattr(statement_parsing_mod, "PARSE_RETRY_DELAY_SECONDS", 0)
    _patch_parse_document(monkeypatch, test_user.id, side_effect=exc)
    if is_retry:
        statement = await add_statement(
            db, test_user.id, "hash_retry", confidence=80, status=BankStatementStatus.REJECTED
        )
        await seed_uploaded_document(db, statement, file_path="path")
        await db.commit()
        resp = await client.post(f"/statements/{statement.id}/runs", json={})
        stmt_id = statement.id
    else:
        resp = await _post_upload(client, "statement.pdf", b"content")
        stmt_id = resp.json()["id"]
    assert resp.status_code == status.HTTP_202_ACCEPTED
    await statement_pipeline.wait_for_parse_tasks()
    refreshed = await db.get(StatementSummary, stmt_id, populate_existing=True)
    assert refreshed is not None and time.monotonic() - started < 5
    if isinstance(exc, ExtractionError):
        assert refreshed.status == BankStatementStatus.REJECTED
    elif is_retry:
        assert refreshed.status in (BankStatementStatus.PARSING, BankStatementStatus.REJECTED)


@pytest.mark.parametrize("storage_fails", [False, True])
async def test_delete_statement_success(client: AsyncClient, db, test_user, monkeypatch, storage_fails):
    statement = await add_statement(db, test_user.id, f"hash_del_{storage_fails}", confidence=90)
    await seed_uploaded_document(db, statement, file_path="statements/user/file.pdf")
    statement_id = statement.id
    await db.commit()
    mock_storage = failing_storage(monkeypatch, method="delete_object") if storage_fails else None
    if not storage_fails:
        monkeypatch.setattr("src.routers.statements.StorageService", DummyStorage)
    assert (await client.delete(f"/statements/{statement_id}")).status_code == status.HTTP_204_NO_CONTENT
    if mock_storage is not None:
        mock_storage.delete_object.assert_not_called()
    assert (await db.get(StatementSummary, statement_id, populate_existing=True)).status is BankStatementStatus.RETIRED


async def test_get_statement_for_review_omits_unused_presigned_pdf_url(client: AsyncClient, db, test_user, monkeypatch):
    """#2959: Review response no longer mints an unused presigned pdf_url."""
    statement = await add_statement(db, test_user.id, "hash_review_no_presign", confidence=75)
    await seed_uploaded_document(db, statement, file_path="statements/review/no-presign.pdf")
    await db.commit()
    mock_storage = MagicMock()
    monkeypatch.setattr("src.routers.statements.StorageService", MagicMock(return_value=mock_storage))

    resp = await client.get(f"/statements/{statement.id}/review")
    result = resp.json()
    assert resp.status_code == status.HTTP_200_OK and result["id"] == str(statement.id)
    assert "pdf_url" not in result
    assert {"opening_balance", "closing_match"} <= result["balance_validation_result"].keys()
    mock_storage.generate_presigned_url.assert_not_called()


async def test_approve_statement_rejects_stale_source_result_digest(client: AsyncClient, db, test_user):
    """#3025: Stale tab digest returns 409 Conflict instead of posting an unseen extraction result."""
    from pathlib import Path

    from src.composition import compose_statement_posting_dependencies
    from src.extraction.extension.extraction_trace import build_extraction_trace_records
    from src.extraction.extension.reviewed_statement_envelope import persist_statement_extraction_result

    account = await create_statement_account(db, test_user.id, "Digest Pin Account")
    statement = build_statement(test_user.id, "hash_approve_digest_pin", 90)
    statement.account_id = account.id
    statement.currency = "SGD"
    statement.opening_balance = Decimal("100.00")
    statement.closing_balance = Decimal("100.00")
    db.add(statement)
    await db.flush()
    await seed_uploaded_document(db, statement, file_path="statements/doc/digest.pdf")
    source = DocumentSource.resolve(path=Path("digest.pdf"), content=b"%PDF-1.7-digest")
    result = await persist_mock_result(db, source=source, statement=statement, transactions=[])
    trace_records = build_extraction_trace_records(
        result,
        user_id=test_user.id,
        execution_id=f"statement:{statement.id}:result:{result.result_id}",
        occurred_at=statement.created_at,
    )
    await compose_statement_posting_dependencies().trace_emitter_factory(db).emit_many(trace_records)
    await persist_statement_extraction_result(
        db, statement=statement, result=result, source_trace_record_id=trace_records[0].record_id
    )
    await db.commit()

    for body in (None, {}, {"create_account_if_missing": True}):
        missing_resp = await client.post(f"/statements/{statement.id}/approvals", json=body)
        assert missing_resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert "expected_source_result_digest" in missing_resp.json()["detail"]
    await db.refresh(statement)
    assert statement.status == BankStatementStatus.PARSED

    stale_resp = await client.post(
        f"/statements/{statement.id}/approvals",
        json={"expected_source_result_digest": "0" * 64},
    )
    assert stale_resp.status_code == status.HTTP_409_CONFLICT
    assert "changed" in stale_resp.json()["detail"].lower() or "reload" in stale_resp.json()["detail"].lower()

    fresh_resp = await client.post(
        f"/statements/{statement.id}/approvals",
        json={"expected_source_result_digest": result.content_digest},
    )
    assert fresh_resp.status_code == status.HTTP_200_OK


@pytest.mark.parametrize(
    ("has_doc", "storage_err", "expected_status"),
    [
        (True, False, status.HTTP_200_OK),
        (False, False, status.HTTP_404_NOT_FOUND),
        (True, True, status.HTTP_502_BAD_GATEWAY),
    ],
)
async def test_get_statement_document_streams_and_handles_errors(
    client: AsyncClient, db, test_user, monkeypatch, has_doc, storage_err, expected_status
):
    statement = await add_statement(db, test_user.id, f"hash_doc_{has_doc}_{storage_err}", confidence=75)
    if has_doc:
        await seed_uploaded_document(
            db, statement, file_path="statements/doc/preview.pdf", original_filename="moomoo.pdf"
        )
    await db.commit()
    if storage_err:
        failing_storage(monkeypatch, method="get_object")
    else:
        monkeypatch.setattr("src.routers.statements.StorageService", DummyStorage)
    resp = await client.get(f"/statements/{statement.id}/document")
    assert resp.status_code == expected_status
    if expected_status == status.HTTP_200_OK:
        assert (
            resp.content == b"dummy content"
            and resp.headers["content-type"].startswith("application/pdf")
            and resp.headers["content-disposition"] == "inline"
        )


async def test_list_and_transactions_flow(client: AsyncClient, monkeypatch, storage_stub, test_user):
    _patch_parse_document(
        monkeypatch,
        test_user.id,
        transactions=[
            ExtractedTransactionRow(
                user_id=test_user.id,
                txn_date=date(2025, 1, 2),
                description="Salary",
                amount=Decimal("5000.00"),
                direction="IN",
                reference=None,
                currency="SGD",
                currency_unresolved=False,
                balance_after=None,
                occurrence_index=0,
                dedup_hash=DeduplicationService.calculate_transaction_hash(
                    test_user.id, date(2025, 1, 2), Decimal("5000.00"), TransactionDirection.IN, "Salary"
                ),
            )
        ],
    )
    assert (
        upload_resp := await _post_upload(client, "statement.pdf", b"statement-flow")
    ).status_code == status.HTTP_202_ACCEPTED
    statement_id = upload_resp.json()["id"]
    await statement_pipeline.wait_for_parse_tasks()
    listed, fetched = (await client.get("/statements")).json(), (await client.get(f"/statements/{statement_id}")).json()
    assert (
        listed["total"],
        listed["items"][0]["id"],
        fetched["id"],
        len(fetched["transactions"]),
        fetched["transactions"][0]["description"],
        fetched["transactions"][0]["source_row"],
    ) == (1, statement_id, statement_id, 1, "Salary", 1)


async def test_upload_statement_releases_db_transaction_during_s3_and_handles_concurrent_duplicate(
    client: AsyncClient, db, db_engine, monkeypatch, test_user
):
    """Verify S3 upload runs outside any DB transaction and concurrent duplicates return 409 with S3 cleanup."""
    from fastapi.concurrency import run_in_threadpool as orig_run_in_threadpool
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from src.database import get_db
    from src.main import app

    _patch_parse_document(monkeypatch, test_user.id)
    account = await create_statement_account(db, test_user.id, "S3 Release Check")
    await db.commit()

    sessions: list[AsyncSession] = []
    in_tx_during_s3: list[bool] = []
    uploaded_keys: list[str] = []
    deleted_keys: list[str] = []
    concurrent_dup_hash: str | None = None

    class SpyStorage(DummyStorage):
        def upload_bytes(self, *, key: str, content: bytes, content_type: str | None = None) -> None:
            uploaded_keys.append(key)

        def delete_object(self, key: str) -> None:
            deleted_keys.append(key)

    monkeypatch.setattr("src.routers.statements.StorageService", SpyStorage)

    async def spy_run_in_threadpool(fn, *args, **kwargs):
        if getattr(fn, "__name__", None) == "upload_bytes":
            assert sessions, "Expected request DB session to be opened before upload_bytes"
            in_tx_during_s3.append(sessions[-1].in_transaction())
            result = await orig_run_in_threadpool(fn, *args, **kwargs)
            if concurrent_dup_hash is not None:
                maker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
                async with maker() as concurrent_db:
                    await add_statement(concurrent_db, test_user.id, concurrent_dup_hash, confidence=90)
                    await concurrent_db.commit()
            return result
        return await orig_run_in_threadpool(fn, *args, **kwargs)

    monkeypatch.setattr("src.routers.statements.run_in_threadpool", spy_run_in_threadpool)

    async def override_get_db():
        async for session in get_db():
            sessions.append(session)
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        ok_resp = await _post_upload(
            client,
            "s3-release.pdf",
            b"release-tx-content",
            account_id=account.id,
        )
        assert ok_resp.status_code == status.HTTP_202_ACCEPTED
        await statement_pipeline.wait_for_parse_tasks()
        assert in_tx_during_s3 == [False]
        assert len(uploaded_keys) == 1 and deleted_keys == []

        dup_bytes = b"concurrent-dup-content"
        concurrent_dup_hash = hashlib.sha256(dup_bytes).hexdigest()
        dup_resp = await _post_upload(
            client,
            "concurrent-dup.pdf",
            dup_bytes,
            account_id=account.id,
        )
        assert dup_resp.status_code == status.HTTP_409_CONFLICT
        assert "duplicate statement upload" in dup_resp.json()["detail"].lower()
        assert in_tx_during_s3 == [False, False]
        assert len(uploaded_keys) == 2 and deleted_keys == [uploaded_keys[1]]
    finally:
        app.dependency_overrides.pop(get_db, None)
