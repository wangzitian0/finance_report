"""Background task functions for statement parsing."""

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import structlog
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.audit import TraceEmitter
from src.extraction.base.types import (
    DocumentSource,
    ParseJob,
    RetryableStatementIngestionError,
    StatementIngestionConfigurationError,
    StatementIngestionOutcome,
    StatementIngestionStatus,
)
from src.extraction.extension.brokerage_positions import looks_like_brokerage_payload
from src.extraction.extension.brokerage_statement_payload import _extract_brokerage_payload_from_metadata
from src.extraction.extension.extraction_trace import build_extraction_trace_records
from src.extraction.extension.reviewed_statement_envelope import persist_statement_extraction_result
from src.extraction.extension.service import ExtractionError, ExtractionService
from src.extraction.extension.statement_posting import (
    StatementPostingDependencies,
    try_auto_approve_high_confidence_statement,
)
from src.extraction.orm.layer1 import DocumentStatus, DocumentType, UploadedDocument
from src.extraction.orm.statement_enums import BankStatementStatus, Stage1Status
from src.extraction.orm.statement_summary import StatementSummary
from src.identity import User
from src.observability import get_logger, record_statement_parse_outcome, safe_error_message
from src.runtime import StorageError, StorageService

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

ContentLoader = Callable[[str], Awaitable[bytes]]
ExtractionServiceFactory = Callable[[], ExtractionService]
BrokerageRouter = Callable[..., Awaitable[None]]
Clock = Callable[[], float]
TraceEmitterFactory = Callable[[AsyncSession], TraceEmitter]


@dataclass(frozen=True, slots=True, kw_only=True)
class StatementIngestionUseCase:
    """The single application boundary for one statement ingestion attempt."""

    session_maker: async_sessionmaker[AsyncSession]
    content_loader: ContentLoader
    extraction_service_factory: ExtractionServiceFactory
    posting_dependencies: StatementPostingDependencies
    brokerage_router: BrokerageRouter
    trace_emitter_factory: TraceEmitterFactory
    clock: Clock

    def __post_init__(self) -> None:
        for name in (
            "session_maker",
            "content_loader",
            "extraction_service_factory",
            "posting_dependencies",
            "brokerage_router",
            "trace_emitter_factory",
            "clock",
        ):
            if getattr(self, name) is None:
                raise StatementIngestionConfigurationError(f"Missing statement ingestion dependency: {name}")

    async def execute(
        self,
        job: ParseJob,
        *,
        content: bytes | None = None,
    ) -> StatementIngestionOutcome:
        """Load missing content and execute the package-owned ingestion sequence."""
        if content is None:
            try:
                content = await self.content_loader(job.storage_key)
            except Exception as exc:
                raise RetryableStatementIngestionError(f"Statement content load failed: {exc}") from exc
        return await _execute_statement_ingestion(
            job=job,
            content=content,
            session_maker=self.session_maker,
            extraction_service_factory=self.extraction_service_factory,
            posting_dependencies=self.posting_dependencies,
            brokerage_router=self.brokerage_router,
            trace_emitter_factory=self.trace_emitter_factory,
            clock=self.clock,
        )


def build_statement_ingestion_use_case(
    *,
    session_maker: async_sessionmaker[AsyncSession],
    content_loader: ContentLoader,
    posting_dependencies: StatementPostingDependencies,
    trace_emitter_factory: TraceEmitterFactory,
) -> StatementIngestionUseCase:
    """Bind extraction-internal implementations around composed cross-domain ports."""
    return StatementIngestionUseCase(
        session_maker=session_maker,
        content_loader=content_loader,
        extraction_service_factory=ExtractionService,
        posting_dependencies=posting_dependencies,
        brokerage_router=route_brokerage_for_review_if_present,
        trace_emitter_factory=trace_emitter_factory,
        clock=time.perf_counter,
    )


def _redacted(message: str | None, *, limit: int = 500) -> str | None:
    """PII-redact and bound failure text, preserving ``None`` (no error)."""
    return safe_error_message(message, limit=limit) if message else None


def _count_brokerage_positions(payload: dict[str, Any] | None) -> int | None:
    if not payload:
        return None
    positions = payload.get("positions")
    if isinstance(positions, list):
        return len(positions)
    statement = payload.get("statement")
    if isinstance(statement, dict):
        holdings = statement.get("holdings") or statement.get("positions")
        if isinstance(holdings, list):
            return len(holdings)
    return None


def _append_validation_note(existing: str | None, note: str) -> str:
    if existing:
        combined = f"{existing}; {note}"
    else:
        combined = note
    return combined[:500]


async def route_brokerage_for_review_if_present(
    *,
    summary: StatementSummary,
    db: AsyncSession,
    user_id: UUID,
    filename: str,
    institution: str | None,
    payload: dict[str, Any] | None,
    request_id: str | None = None,
    model_to_use: str | None = None,
) -> None:
    """Route a detected brokerage statement to Stage-1 review WITHOUT importing positions (#1408).

    Brokerage positions used to be auto-imported into AtomicPosition (L2) + ManagedPosition
    (L3) during parse, before any human review, so a still-``pending_review`` brokerage
    statement immediately inflated ``/portfolio/holdings``, ``/portfolio/summary``, and
    ``/reports/net-worth/*`` (#1408). Positions must instead be created only by the explicit,
    user-initiated ``POST /statements/{statement_id}/brokerage/import`` endpoint.

    So at parse we ONLY surface the statement for review: a detected brokerage payload moves the
    statement into ``Stage1Status.PENDING_REVIEW`` (when ``PARSED`` and not already approved) so a
    human can trigger the explicit import. No ``AtomicPosition`` / ``ManagedPosition`` rows are
    created here. ``user_id`` is retained for signature parity with the explicit import path.
    """
    if not looks_like_brokerage_payload(payload, filename=filename, institution=institution or summary.institution):
        return

    request_id = request_id or str(uuid4())
    broker = None
    if payload:
        broker = payload.get("institution")
        if not broker and isinstance(payload.get("statement"), dict):
            broker = payload["statement"].get("institution")
    broker = broker or institution or summary.institution
    parsed_positions = _count_brokerage_positions(payload)
    logger.info(
        "statement.brokerage_review_routing.started",
        audit_event="statement.brokerage_review_routing.started",
        request_id=request_id,
        statement_id=str(summary.id),
        phase="brokerage_review_routing_started",
        model_to_use=model_to_use,
        broker=broker,
        parsed_positions=parsed_positions,
    )

    try:
        if parsed_positions == 0:
            # AC6 (#1408, formerly AC-B5/#1139): a brokerage document that yields zero
            # positions is a surfaced REVIEW FLAG, not a buried string — keep the
            # human-readable validation note in addition to the pending-review routing.
            summary.validation_error = _append_validation_note(
                summary.validation_error,
                "Brokerage import skipped: no positions detected in parsed brokerage payload",
            )
        # #1408: do NOT import positions at parse. Only surface the brokerage statement in
        # the Stage-1 review queue so the user can trigger the explicit import endpoint,
        # which remains the sole path that creates AtomicPosition/ManagedPosition rows.
        if summary.status == BankStatementStatus.PARSED and summary.stage1_status != Stage1Status.APPROVED:
            summary.stage1_status = Stage1Status.PENDING_REVIEW
        await db.flush()
        logger.info(
            "statement.brokerage_review_routing.completed",
            audit_event="statement.brokerage_review_routing.completed",
            request_id=request_id,
            statement_id=str(summary.id),
            phase="brokerage_review_routing_completed",
            model_to_use=model_to_use,
            broker=broker,
            parsed_positions=parsed_positions,
        )
    except Exception as exc:
        logger.exception(
            "statement.brokerage_review_routing.failed",
            audit_event="statement.brokerage_review_routing.failed",
            request_id=request_id,
            statement_id=str(summary.id),
            phase="brokerage_review_routing_failed",
            model_to_use=model_to_use,
            error_type=type(exc).__name__,
            safe_error_message=safe_error_message(str(exc)),
        )
        raise


def _mark_document_failed_unless_completed(document: UploadedDocument) -> None:
    """Mark a document failed, but never downgrade one a successful parse already completed."""
    if document.status != DocumentStatus.COMPLETED:
        document.status = DocumentStatus.FAILED


async def _find_document_by_hash(db: AsyncSession, user_id: UUID, file_hash: str) -> UploadedDocument | None:
    return (
        await db.execute(
            select(UploadedDocument)
            .where(UploadedDocument.user_id == user_id)
            .where(UploadedDocument.file_hash == file_hash)
        )
    ).scalar_one_or_none()


async def register_statement_source(
    db: AsyncSession,
    *,
    statement: StatementSummary,
    storage_key: str,
    original_filename: str,
) -> UploadedDocument:
    """Durably bind an accepted upload to its source artifact before dispatch.

    The upload request owns source registration; parsing only enriches this same
    artifact with extraction output and its resolved document type.  The
    ``(user_id, file_hash)`` identity makes the registration safe to retry
    without transient attributes on the DWD statement summary.
    """
    document = await _find_document_by_hash(db, statement.user_id, statement.file_hash)
    if document is None:
        document = UploadedDocument(
            user_id=statement.user_id,
            file_path=storage_key,
            file_hash=statement.file_hash,
            original_filename=original_filename,
            document_type=DocumentType.BANK_STATEMENT,
            status=DocumentStatus.UPLOADED,
        )
        try:
            # A concurrent retry can win the unique source identity.  Isolate
            # that race so the statement upload transaction remains usable.
            async with db.begin_nested():
                db.add(document)
                await db.flush()
        except IntegrityError:
            document = await _find_document_by_hash(db, statement.user_id, statement.file_hash)
            if document is None:
                raise

    statement.uploaded_document_id = document.id

    from src.extraction.extension.evidence_graph_integration import EvidenceGraphIntegrationService

    await EvidenceGraphIntegrationService().record_statement_source(
        db,
        user_id=statement.user_id,
        statement=statement,
        uploaded_document=document,
    )
    return document


async def _ensure_failed_document_lineage(
    db: AsyncSession,
    statement: StatementSummary,
    *,
    file_hash: str,
    storage_key: str,
    original_filename: str,
) -> None:
    """Persist an ODS ``UploadedDocument`` (status ``failed``) for a parse that never reached
    ``dual_write_layer2`` (which is the normal create path on success).

    Without this, a hard parse failure leaves no document row, so the uploaded raw file — the
    thing a human most needs to inspect for a failed parse — is unreachable from the statement
    (#982). The document type is unknown for a failed parse, so it defaults to ``bank_statement``;
    a later successful reparse reconciles the same ``(user_id, file_hash)`` row via dual-write.

    Re-checks user existence first (#1256, AC13.23.2): a background parse can race a
    ``DELETE /users/{id}``; if the owning user was deleted mid-parse, inserting
    ``uploaded_documents.user_id`` for a missing ``users.id`` raises a FK IntegrityError
    (which, before the rollback-ordering fix, masked the original parse error). When the
    user is gone we skip the lineage write gracefully instead.
    """
    user_exists = await db.scalar(select(User.id).where(User.id == statement.user_id).limit(1))
    if user_exists is None:
        logger.warning(
            "statement.parse.lineage_skipped_user_deleted",
            statement_id=str(statement.id),
            user_id=str(statement.user_id),
        )
        return

    existing = await _find_document_by_hash(db, statement.user_id, file_hash)
    if existing is not None:
        _mark_document_failed_unless_completed(existing)
        statement.uploaded_document_id = existing.id
        return

    document = UploadedDocument(
        user_id=statement.user_id,
        file_path=storage_key,
        file_hash=file_hash,
        original_filename=original_filename,
        document_type=DocumentType.BANK_STATEMENT,
        status=DocumentStatus.FAILED,
    )
    try:
        # Insert inside a savepoint so losing the unique-key race does not poison the outer
        # transaction (which still needs to commit the statement rejection).
        async with db.begin_nested():
            db.add(document)
            await db.flush()
    except IntegrityError:
        raced = await _find_document_by_hash(db, statement.user_id, file_hash)
        if raced is not None:
            _mark_document_failed_unless_completed(raced)
            statement.uploaded_document_id = raced.id
        return
    statement.uploaded_document_id = document.id


async def handle_parse_failure(
    statement: StatementSummary,
    db: AsyncSession,
    *,
    job: ParseJob | None = None,
    message: str | None,
    phase: str = "unknown",
    progress: int | None = None,
    model_to_use: str | None = None,
    error_type: str | None = None,
) -> None:
    """Handle parse failure by marking statement as REJECTED.

    This function handles error recovery when parsing fails:
    1. Attempts rollback if session is in error state
    2. Refreshes statement to get clean DB state
    3. Marks statement as REJECTED with error message

    Args:
        statement: The StatementSummary envelope (may have expired session)
        db: AsyncSession for database operations
        message: Error message to store in validation_error
        job: Parse identity captured before any failing operation. Its plain
            statement UUID is preferred over reading ``statement.id`` (#1256,
            AC13.23.3): on an already-failed session, touching an expired ORM
            attribute raises ``PendingRollbackError`` and masks the original
            error. We roll back FIRST, then only fall back to reading the ORM
            attribute once the session is clean.
    """
    request_id = job.request_id if job is not None and job.request_id else str(uuid4())
    statement_id = job.statement_id if job is not None else None
    # Resolve the statement id WITHOUT ever letting an expired/failed-session ORM
    # read mask the original error (#1256, AC13.23.3). Prefer the plain id the
    # caller captured before any failing operation; otherwise read ``statement.id``
    # defensively. A read that raises (e.g. PendingRollbackError on an already-failed
    # session) must NOT abort the handler — we still roll back and recover below.
    if statement_id is None:
        try:
            statement_id = statement.id
        except Exception as id_exc:
            logger.warning(
                "Could not read statement id before rollback; will retry after rollback",
                original_error=_redacted(message),
                id_error=str(id_exc),
            )
    try:
        await db.rollback()
    except Exception as rollback_exc:
        logger.warning(
            "Rollback failed during parse failure handling",
            statement_id=str(statement_id) if statement_id is not None else None,
            rollback_error=str(rollback_exc),
        )
    # If the id was unreadable before rollback (failed session), the session is now
    # clean, so a second read is safe.
    if statement_id is None:
        try:
            statement_id = statement.id
        except Exception as id_exc:
            logger.error(
                "Could not resolve statement id in parse failure handler",
                original_error=_redacted(message),
                id_error=str(id_exc),
            )
            return
    try:
        refreshed = await db.get(StatementSummary, statement_id)
        if refreshed is None:
            logger.error(
                "Statement not found after rollback",
                statement_id=str(statement_id),
                reason=_redacted(message),
            )
            return
        refreshed.status = BankStatementStatus.REJECTED
        refreshed.validation_error = _redacted(message)
        refreshed.confidence_score = 0
        refreshed.balance_validated = False
        if job is not None:
            await _ensure_failed_document_lineage(
                db,
                refreshed,
                file_hash=job.file_hash,
                storage_key=job.storage_key,
                original_filename=job.filename,
            )
        await db.commit()
        logger.warning(
            "statement.parse.failed",
            audit_event="statement.parse.failed",
            request_id=request_id,
            statement_id=str(refreshed.id),
            phase=phase,
            progress=progress,
            model_to_use=model_to_use,
            error_type=error_type,
            safe_error_message=_redacted(message, limit=300),
        )
        # AC-observability.10.4: business metric for the parse outcome (failure path).
        record_statement_parse_outcome(outcome="failure")
    except Exception as inner_exc:
        logger.exception(
            "Failed to mark statement as rejected",
            statement_id=str(statement_id),
            original_error=_redacted(message),
            inner_error=str(inner_exc),
        )


async def _execute_statement_ingestion(
    job: ParseJob,
    *,
    content: bytes,
    session_maker: async_sessionmaker[AsyncSession],
    extraction_service_factory: ExtractionServiceFactory,
    posting_dependencies: StatementPostingDependencies,
    brokerage_router: BrokerageRouter,
    trace_emitter_factory: TraceEmitterFactory,
    clock: Clock,
) -> StatementIngestionOutcome:
    """Background task to parse a bank statement document.

    This function runs asynchronously to:
    1. Generate presigned URL for storage (if possible)
    2. Parse document using AI models
    3. Update statement with parsed data
    4. Handle errors and mark statement appropriately

    Args:
        job: Immutable identity and routing context for this parse.
        content: Raw file content bytes
        session_maker: AsyncSession maker for background DB operations
    """
    statement_id = job.statement_id
    filename = job.filename
    institution = job.institution
    user_id = job.user_id
    account_id = job.account_id
    file_hash = job.file_hash
    storage_key = job.storage_key
    model = job.model
    request_id = job.request_id or str(uuid4())
    if job.request_id is None:
        job = replace(job, request_id=request_id)
    # Bind request_id to context for this background task
    structlog.contextvars.bind_contextvars(
        request_id=request_id, statement_id=str(statement_id), task="parse_statement"
    )

    file_type = filename.rsplit(".", 1)[-1].lower() if "." in filename else "pdf"
    model_to_use = model
    logger.info(
        "Starting background parsing",
        filename=filename,
        statement_id=str(statement_id),
        request_id=request_id,
        model_to_use=model_to_use,
        file_type=file_type,
    )
    start_time = clock()

    async with session_maker() as session:
        statement = await session.get(StatementSummary, statement_id)
        if not statement:
            logger.error(
                "Statement not found in DB for background parsing",
                statement_id=str(statement_id),
                request_id=request_id,
            )
            return StatementIngestionOutcome(
                statement_id=statement_id,
                status=StatementIngestionStatus.STATEMENT_NOT_FOUND,
            )

        current_phase = "parse_started"

        def checkpoint(phase: str) -> None:
            nonlocal current_phase
            current_phase = phase
            logger.info(
                "statement.parse.checkpoint",
                audit_event="statement.parse.checkpoint",
                request_id=request_id,
                statement_id=str(statement_id),
                phase=current_phase,
                model_to_use=model_to_use,
                file_type=file_type,
            )

        checkpoint("parse_started")

        storage = StorageService()
        file_url = None
        try:
            file_url = await run_in_threadpool(storage.generate_presigned_url, key=storage_key, public=True)
        except StorageError as exc:
            logger.warning(
                "Could not generate public presigned URL",
                error=str(exc),
                statement_id=str(statement_id),
            )

        checkpoint("storage_url_resolved")

        if file_type == "pdf" and not file_url:
            logger.info(
                "No public URL available for PDF; will use base64-encoded content",
                statement_id=str(statement_id),
            )

        service = extraction_service_factory()
        try:
            checkpoint("extraction_started")
            # file_path must be the STORAGE key, not the display filename: it
            # is persisted as UploadedDocument.file_path, which the retry /
            # reparse paths hand straight to storage.get_object. With the bare
            # filename every post-success reparse 404'd against storage
            # (caught by the #1520 real-storage pipeline test). The display
            # name travels separately as original_filename.
            extraction_result = await service.parse_document(
                DocumentSource.resolve(
                    path=Path(storage_key),
                    content=content,
                    url=file_url,
                    content_hash=file_hash,
                    filename=filename,
                ),
                institution=institution,
                user_id=user_id,
                file_type=file_type,
                account_id=account_id,
                force_model=model,
                db=session,
            )
            logger.info(
                "statement.parse.extraction_completed",
                audit_event="statement.parse.extraction_completed",
                request_id=request_id,
                statement_id=str(statement_id),
                model_to_use=model_to_use,
                will_use_force_model=bool(model_to_use),
                file_type=file_type,
            )
            checkpoint("extraction_completed")
        except ExtractionError as exc:
            await handle_parse_failure(
                statement,
                session,
                job=job,
                message=str(exc),
                phase=current_phase,
                progress=None,
                model_to_use=model_to_use,
                error_type=type(exc).__name__,
            )
            return StatementIngestionOutcome(
                statement_id=statement_id,
                status=StatementIngestionStatus.SOURCE_REJECTED,
            )
        except Exception as exc:
            logger.exception(
                "Background parsing failed unexpectedly",
                statement_id=str(statement_id),
                request_id=request_id,
                phase=current_phase,
                model_to_use=model_to_use,
                error_type=type(exc).__name__,
            )
            await session.rollback()
            raise RetryableStatementIngestionError(f"Statement extraction application failure: {exc}") from exc

        try:
            # `parse_document(db=session)` already persisted the DWD result via
            # `dual_write_layer2`: the ODS UploadedDocument, the Layer-2 AtomicTransaction
            # facts, and the confirmed envelope/status updated onto this pre-created
            # StatementSummary row (reused by `(user_id, file_hash)`), including
            # `uploaded_document_id`. Refresh so the in-memory row reflects that write.
            await session.flush()
            await session.refresh(statement)

            result_payload = (statement.extraction_metadata or {}).get("statement_extraction_result")
            if not isinstance(result_payload, dict):
                raise RuntimeError("statement extraction result was not persisted")
            from src.extraction.base.result import StatementExtractionResult

            persisted_result = StatementExtractionResult.from_payload(result_payload)
            if persisted_result != extraction_result:
                raise RuntimeError("persisted statement extraction result changed source facts")
            trace_occurred_at = statement.created_at or datetime.now(UTC)
            if trace_occurred_at.tzinfo is None:
                trace_occurred_at = trace_occurred_at.replace(tzinfo=UTC)
            trace_records = build_extraction_trace_records(
                extraction_result,
                user_id=user_id,
                execution_id=f"statement:{statement.id}:result:{extraction_result.result_id}",
                occurred_at=trace_occurred_at,
            )
            await trace_emitter_factory(session).emit_many(trace_records)
            await persist_statement_extraction_result(
                session,
                statement=statement,
                result=persisted_result,
                source_trace_record_id=trace_records[0].record_id,
            )

            checkpoint("statement_persisted")
            auto_posted_count = await try_auto_approve_high_confidence_statement(
                session,
                statement.id,
                user_id,
                dependencies=posting_dependencies,
            )
            # #1408: detect a brokerage statement and route it to Stage-1 review WITHOUT
            # importing positions. Positions are created only by the explicit, user-initiated
            # POST /statements/{id}/brokerage/import endpoint, so a pending-review brokerage
            # statement never inflates holdings/summary/net-worth before human review.
            await brokerage_router(
                summary=statement,
                db=session,
                user_id=user_id,
                filename=filename,
                institution=institution,
                payload=_extract_brokerage_payload_from_metadata(statement.extraction_metadata),
                request_id=request_id,
                model_to_use=model_to_use,
            )
            await session.commit()
            duration = clock() - start_time
            logger.info(
                "statement.parse.completed",
                audit_event="statement.parse.completed",
                request_id=request_id,
                statement_id=str(statement_id),
                phase="parse_completed",
                duration_ms=round(duration * 1000, 2),
                transactions_count=len(extraction_result.transactions),
                auto_posted_count=auto_posted_count,
            )
            # AC-observability.10.4: business metric for the parse outcome (success path).
            record_statement_parse_outcome(outcome="success")
            return StatementIngestionOutcome(
                statement_id=statement_id,
                status=StatementIngestionStatus.COMPLETED,
                transactions_count=len(extraction_result.transactions),
                auto_posted_count=auto_posted_count,
            )
        except Exception as exc:
            logger.exception(
                "Failed to finalize statement parsing",
                statement_id=str(statement_id),
                request_id=request_id,
                phase=current_phase,
                model_to_use=model_to_use,
                error_type=type(exc).__name__,
            )
            await session.rollback()
            raise RetryableStatementIngestionError(f"Statement finalization application failure: {exc}") from exc
