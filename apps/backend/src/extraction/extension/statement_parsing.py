"""Background task functions for statement parsing."""

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import structlog
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.audit import TraceEmitter
from src.extraction.base.result import StatementExtractionResult
from src.extraction.base.run_vocabulary import ERROR_MESSAGE_MAX_LENGTH, RunActorKind, RunKind, RunTrigger
from src.extraction.base.source_vocabulary import BankStatementStatus, DocumentStatus, DocumentType, Stage1Status
from src.extraction.base.types import (
    DocumentSource,
    ParseJob,
    RetryableStatementIngestionError,
    RunHints,
    StatementIngestionConfigurationError,
    StatementIngestionOutcome,
    StatementIngestionStatus,
)
from src.extraction.base.validation import HIGH_CONFIDENCE_AUTO_APPROVE_THRESHOLD
from src.extraction.extension.brokerage_positions import looks_like_brokerage_payload
from src.extraction.extension.brokerage_statement_payload import _extract_brokerage_payload_from_metadata
from src.extraction.extension.extraction_trace import build_extraction_trace_records
from src.extraction.extension.reviewed_statement_envelope import persist_statement_extraction_result
from src.extraction.extension.service import ExtractionError, ExtractionService
from src.extraction.extension.statement_parsing_supervisor import parsing_heartbeat
from src.extraction.extension.statement_posting import (
    ECONOMIC_REVIEW_NOTICE,
    StatementPostingDependencies,
    try_auto_approve_high_confidence_statement,
)
from src.extraction.extension.statement_preclassification import (
    StatementClassificationPhase,
    classify_parsed_statement,
)
from src.extraction.extension.statement_runs import StaleRun, claim_run, create_run, fail_run, finish_run
from src.extraction.extension.statement_workflow import approve_statement_workflow
from src.extraction.extension.transaction_identity import TransactionIdentityReviewRequired
from src.extraction.orm.layer1 import UploadedDocument
from src.extraction.orm.statement_summary import StatementSummary
from src.identity import User
from src.observability import get_logger, record_statement_parse_outcome, safe_error_message
from src.runtime import StorageError, StorageService

logger = get_logger(__name__)

ContentLoader = Callable[[str], Awaitable[bytes]]
ExtractionServiceFactory = Callable[[], ExtractionService]
BrokerageRouter = Callable[..., Awaitable[None]]
Clock = Callable[[], float]
TraceEmitterFactory = Callable[[AsyncSession], TraceEmitter]
Sleep = Callable[[float], Awaitable[None]]

MAX_PARSE_ATTEMPTS = 3
PARSE_RETRY_DELAY_SECONDS = 30


@dataclass(frozen=True, slots=True, kw_only=True)
class StatementIngestionUseCase:
    """Single application boundary for one statement ingestion attempt."""

    session_maker: async_sessionmaker[AsyncSession]
    content_loader: ContentLoader
    extraction_service_factory: ExtractionServiceFactory
    posting_dependencies: StatementPostingDependencies
    brokerage_router: BrokerageRouter
    trace_emitter_factory: TraceEmitterFactory
    clock: Clock
    sleep: Sleep = asyncio.sleep

    def __post_init__(self) -> None:
        for name in (
            "session_maker",
            "content_loader",
            "extraction_service_factory",
            "posting_dependencies",
            "brokerage_router",
            "trace_emitter_factory",
            "clock",
            "sleep",
        ):
            if getattr(self, name) is None:
                raise StatementIngestionConfigurationError(f"Missing statement ingestion dependency: {name}")

    async def execute(self, job: ParseJob, *, content: bytes | None = None) -> StatementIngestionOutcome:
        """Run the job. A retryable error starts a new system run, at most `MAX_PARSE_ATTEMPTS` runs in all."""
        attempt = 1
        while True:
            try:
                outcome = await self._attempt(job, content)
                break
            except RetryableStatementIngestionError as error:
                next_job = await self._end_failed_attempt(job, error, attempt=attempt)
                if next_job is None:
                    raise
                await self.sleep(PARSE_RETRY_DELAY_SECONDS)
                job, attempt = next_job, attempt + 1
        if outcome.status is StatementIngestionStatus.COMPLETED:
            del content
            phase = await classify_parsed_statement(
                self.session_maker, statement_id=job.statement_id, user_id=job.user_id
            )
            if phase is StatementClassificationPhase.CLASSIFIED:
                recovered = await _try_recover_auto_approve_after_classification(
                    self.session_maker,
                    statement_id=job.statement_id,
                    user_id=job.user_id,
                    posting_dependencies=self.posting_dependencies,
                )
                if recovered > 0:
                    outcome = replace(outcome, auto_posted_count=outcome.auto_posted_count + recovered)
        return outcome

    async def _attempt(self, job: ParseJob, content: bytes | None) -> StatementIngestionOutcome:
        return await _execute_statement_ingestion(
            job=job,
            content=content,
            content_loader=self.content_loader,
            session_maker=self.session_maker,
            extraction_service_factory=self.extraction_service_factory,
            posting_dependencies=self.posting_dependencies,
            brokerage_router=self.brokerage_router,
            trace_emitter_factory=self.trace_emitter_factory,
            clock=self.clock,
        )

    async def _end_failed_attempt(
        self, job: ParseJob, error: RetryableStatementIngestionError, *, attempt: int
    ) -> ParseJob | None:
        """Fail the run of the attempt. Return the job of the next attempt, or None when the loop stops.

        The loop stops after `MAX_PARSE_ATTEMPTS` attempts, or when the reaper already failed the run.
        The statement stays parsing: the supervisor rejects a parsing statement that has no active run.
        """
        async with self.session_maker() as session:
            try:
                failed = await fail_run(
                    session,
                    job.run_id,
                    error_code=_run_error_code(type(error).__name__),
                    error_message=_run_error_message(str(error)),
                )
            except StaleRun:
                await session.rollback()
                logger.warning("statement.run.retry_stale", run_id=str(job.run_id), statement_id=str(job.statement_id))
                return None
            if attempt >= MAX_PARSE_ATTEMPTS:
                await session.commit()
                return None
            successor = await create_run(
                session,
                statement_id=job.statement_id,
                user_id=job.user_id,
                kind=RunKind.EXTRACT,
                actor_kind=RunActorKind.SYSTEM,
                trigger=RunTrigger.AUTO_RETRY,
                # The retry repeats the request of the failed run: same hints and same model.
                hints=RunHints.model_validate(failed.hints),
                model=failed.model,
                parent_run_id=failed.id,
            )
            await session.commit()
            logger.info(
                "statement.run.retry_scheduled",
                run_id=str(failed.id),
                next_run_id=str(successor.id),
                attempt=attempt,
                delay_seconds=PARSE_RETRY_DELAY_SECONDS,
            )
            return replace(job, run_id=successor.id)


async def _try_recover_auto_approve_after_classification(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    statement_id: UUID,
    user_id: UUID,
    posting_dependencies: StatementPostingDependencies,
) -> int:
    try:
        async with session_maker() as session:
            stmt = await session.get(StatementSummary, statement_id)
            if (
                stmt is None
                or stmt.user_id != user_id
                or stmt.status is not BankStatementStatus.PARSED
                or stmt.balance_validated is not True
                or stmt.confidence_score is None
                or stmt.confidence_score < HIGH_CONFIDENCE_AUTO_APPROVE_THRESHOLD
                or stmt.account_id is None
                or not (stmt.validation_error or "").startswith(ECONOMIC_REVIEW_NOTICE)
            ):
                return 0
            return (await approve_statement_workflow(session, statement_id, user_id, dependencies=posting_dependencies)).created_count
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "statement.auto_approve_recovery.failed",
            statement_id=str(statement_id),
            error_type=type(exc).__name__,
            safe_error_message=safe_error_message(str(exc)),
        )
        return 0


def build_statement_ingestion_use_case(
    *,
    session_maker: async_sessionmaker[AsyncSession],
    content_loader: ContentLoader,
    posting_dependencies: StatementPostingDependencies,
    trace_emitter_factory: TraceEmitterFactory,
) -> StatementIngestionUseCase:
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
    return safe_error_message(message, limit=limit) if message else None


def _run_error_message(message: str | None) -> str:
    return (_redacted(message) or "")[:ERROR_MESSAGE_MAX_LENGTH]


def _run_error_code(error_type: str | None) -> str:
    """Turn an error class name such as `ExtractionError` into the run code `extraction_error`."""
    code = re.sub(r"[^a-z0-9_]", "", re.sub(r"(?<!^)(?=[A-Z])", "_", error_type or "").lower()).lstrip("0123456789_")
    return code[:64] or "parse_failed"


def _count_brokerage_positions(payload: dict[str, Any] | None) -> int | None:
    if not payload:
        return None
    if isinstance(positions := payload.get("positions"), list):
        return len(positions)
    if isinstance(stmt := payload.get("statement"), dict) and isinstance(
        holdings := (stmt.get("holdings") or stmt.get("positions")), list
    ):
        return len(holdings)
    return None


def _append_validation_note(existing: str | None, note: str) -> str:
    return (f"{existing}; {note}" if existing else note)[:500]


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
    """Route detected brokerage statement to Stage-1 review without importing positions (#1408)."""
    if not looks_like_brokerage_payload(payload, filename=filename, institution=institution or summary.institution):
        return

    request_id = request_id or str(uuid4())
    broker = (
        (payload.get("institution") or (payload.get("statement") or {}).get("institution") if isinstance(payload, dict) else None)
        or institution
        or summary.institution
    )
    parsed_positions = _count_brokerage_positions(payload)
    txns = payload.get("transactions") if isinstance(payload, dict) else None
    if parsed_positions == 0 and isinstance(txns, list) and len(txns) > 0:
        return

    log_ctx = {
        "request_id": request_id,
        "statement_id": str(summary.id),
        "user_id": str(user_id),
        "model_to_use": model_to_use,
    }
    logger.info(
        "statement.brokerage_review_routing.started",
        audit_event="statement.brokerage_review_routing.started",
        phase="brokerage_review_routing_started",
        broker=broker,
        parsed_positions=parsed_positions,
        **log_ctx,
    )
    try:
        if parsed_positions == 0:
            summary.validation_error = _append_validation_note(
                summary.validation_error,
                "Brokerage import skipped: no positions detected in parsed brokerage payload",
            )
        if summary.status == BankStatementStatus.PARSED and summary.stage1_status != Stage1Status.APPROVED:
            summary.stage1_status = Stage1Status.PENDING_REVIEW
        await db.flush()
        logger.info(
            "statement.brokerage_review_routing.completed",
            audit_event="statement.brokerage_review_routing.completed",
            phase="brokerage_review_routing_completed",
            broker=broker,
            parsed_positions=parsed_positions,
            **log_ctx,
        )
    except Exception as exc:
        logger.exception(
            "statement.brokerage_review_routing.failed",
            audit_event="statement.brokerage_review_routing.failed",
            phase="brokerage_review_routing_failed",
            error_type=type(exc).__name__,
            safe_error_message=safe_error_message(str(exc)),
            **log_ctx,
        )
        raise


def _mark_document_failed_unless_completed(document: UploadedDocument) -> None:
    if document.status != DocumentStatus.COMPLETED:
        document.status = DocumentStatus.FAILED


async def _find_document_by_hash(db: AsyncSession, user_id: UUID, file_hash: str) -> UploadedDocument | None:
    return (
        await db.execute(
            select(UploadedDocument).where(UploadedDocument.user_id == user_id, UploadedDocument.file_hash == file_hash)
        )
    ).scalar_one_or_none()


async def _get_or_insert_document(
    db: AsyncSession,
    *,
    user_id: UUID,
    file_hash: str,
    storage_key: str,
    original_filename: str,
    status: DocumentStatus,
) -> tuple[UploadedDocument | None, bool]:
    existing = await _find_document_by_hash(db, user_id, file_hash)
    if existing is not None:
        return existing, False
    doc = UploadedDocument(
        user_id=user_id,
        file_path=storage_key,
        file_hash=file_hash,
        original_filename=original_filename,
        document_type=DocumentType.BANK_STATEMENT,
        status=status,
    )
    try:
        async with db.begin_nested():
            db.add(doc)
            await db.flush()
        return doc, True
    except IntegrityError:
        return await _find_document_by_hash(db, user_id, file_hash), False


async def register_statement_source(
    db: AsyncSession,
    *,
    statement: StatementSummary,
    storage_key: str,
    original_filename: str,
) -> UploadedDocument:
    """Bind an accepted upload to its source artifact before dispatch."""
    document, _ = await _get_or_insert_document(
        db,
        user_id=statement.user_id,
        file_hash=statement.file_hash,
        storage_key=storage_key,
        original_filename=original_filename,
        status=DocumentStatus.UPLOADED,
    )
    if document is None:
        raise RuntimeError("Failed to register uploaded document")
    statement.uploaded_document_id = document.id

    from src.extraction.extension.evidence_graph_integration import EvidenceGraphIntegrationService

    await EvidenceGraphIntegrationService().record_statement_source(
        db, user_id=statement.user_id, statement=statement, uploaded_document=document
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
    if await db.scalar(select(User.id).where(User.id == statement.user_id).limit(1)) is None:
        logger.warning(
            "statement.parse.lineage_skipped_user_deleted",
            statement_id=str(statement.id),
            user_id=str(statement.user_id),
        )
        return
    doc, created = await _get_or_insert_document(
        db,
        user_id=statement.user_id,
        file_hash=file_hash,
        storage_key=storage_key,
        original_filename=original_filename,
        status=DocumentStatus.FAILED,
    )
    if doc is not None:
        if not created:
            _mark_document_failed_unless_completed(doc)
        statement.uploaded_document_id = doc.id


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
    """Roll back failed parse session, fail the run of the job, and persist REJECTED or PENDING_REVIEW state.

    A run that is no longer active, for example one that the reaper failed, changes nothing.
    """
    request_id = job.request_id if job is not None and job.request_id else str(uuid4())
    statement_id = job.statement_id if job is not None else None
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
        # Lock the statement before the run. The reaper and the finalize take the locks in this order too.
        refreshed = await db.get(StatementSummary, statement_id, with_for_update={"key_share": True})
        if refreshed is None:
            logger.error("Statement not found after rollback", statement_id=str(statement_id), reason=_redacted(message))
            return
        if job is not None:
            try:
                await fail_run(
                    db,
                    job.run_id,
                    error_code=_run_error_code(error_type),
                    error_message=_run_error_message(message),
                )
            except StaleRun:
                await db.rollback()
                logger.warning("statement.run.fail_stale", run_id=str(job.run_id), statement_id=str(statement_id))
                return
        review_required = error_type == TransactionIdentityReviewRequired.__name__
        refreshed.status = BankStatementStatus.PARSED if review_required else BankStatementStatus.REJECTED
        refreshed.stage1_status = Stage1Status.PENDING_REVIEW if review_required else Stage1Status.REJECTED
        refreshed.validation_error = _redacted(message)
        refreshed.confidence_score = 0
        refreshed.balance_validated = False
        if job is not None:
            await _ensure_failed_document_lineage(
                db, refreshed, file_hash=job.file_hash, storage_key=job.storage_key, original_filename=job.filename
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
    content: bytes | None,
    content_loader: ContentLoader,
    session_maker: async_sessionmaker[AsyncSession],
    extraction_service_factory: ExtractionServiceFactory,
    posting_dependencies: StatementPostingDependencies,
    brokerage_router: BrokerageRouter,
    trace_emitter_factory: TraceEmitterFactory,
    clock: Clock,
) -> StatementIngestionOutcome:
    statement_id = job.statement_id
    request_id = job.request_id or str(uuid4())
    if job.request_id is None:
        job = replace(job, request_id=request_id)
    structlog.contextvars.bind_contextvars(request_id=request_id, statement_id=str(statement_id), task="parse_statement")

    file_type = job.filename.rsplit(".", 1)[-1].lower() if "." in job.filename else "pdf"
    logger.info(
        "Starting background parsing",
        filename=job.filename,
        statement_id=str(statement_id),
        request_id=request_id,
        model_to_use=job.model,
        file_type=file_type,
    )
    start_time = clock()

    async with session_maker() as session:
        statement = await session.get(StatementSummary, statement_id)
        if not statement:
            logger.error("Statement not found in DB for background parsing", statement_id=str(statement_id), request_id=request_id)
            return StatementIngestionOutcome(statement_id=statement_id, status=StatementIngestionStatus.STATEMENT_NOT_FOUND)

        try:
            claimed = await claim_run(session, job.run_id)
            stored_hints = claimed.hints
            await session.commit()
        except StaleRun:
            await session.rollback()
            logger.warning(
                "statement.run.claim_stale", run_id=str(job.run_id), statement_id=str(statement_id), request_id=request_id
            )
            return StatementIngestionOutcome(statement_id=statement_id, status=StatementIngestionStatus.RUN_STALE)

        hints: RunHints | None = None
        try:
            hints = RunHints.model_validate(stored_hints)
        except ValidationError:
            # The error text echoes the hint text. Only set a flag here: an error in the failure handling would
            # chain this exception into its traceback, and a log would carry the hint text.
            hints = None
        if hints is None:
            await handle_parse_failure(
                statement,
                session,
                job=job,
                message="The stored hints of the run are not valid.",
                phase="hints_validated",
                model_to_use=job.model,
                error_type="InvalidHints",
            )
            return StatementIngestionOutcome(statement_id=statement_id, status=StatementIngestionStatus.SOURCE_REJECTED)

        # The claim comes first: a worker that does not own the run loads nothing and fails nothing.
        if content is None:
            try:
                content = await content_loader(job.storage_key)
            except Exception as exc:
                raise RetryableStatementIngestionError(f"Statement content load failed: {exc}") from exc

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
                model_to_use=job.model,
                file_type=file_type,
            )

        checkpoint("parse_started")
        file_url = None
        try:
            file_url = await run_in_threadpool(StorageService().generate_presigned_url, key=job.storage_key, public=True)
        except StorageError as exc:
            logger.warning("Could not generate public presigned URL", error=str(exc), statement_id=str(statement_id))

        checkpoint("storage_url_resolved")
        if file_type == "pdf" and not file_url:
            logger.info("No public URL available for PDF; will use base64-encoded content", statement_id=str(statement_id))

        try:
            checkpoint("extraction_started")
            async with parsing_heartbeat(job.run_id, session_maker):
                extraction_result = await extraction_service_factory().parse_document(
                    DocumentSource.resolve(
                        path=Path(job.storage_key),
                        content=content,
                        url=file_url,
                        content_hash=job.file_hash,
                        filename=job.filename,
                    ),
                    institution=job.institution,
                    user_id=job.user_id,
                    file_type=file_type,
                    account_id=job.account_id,
                    force_model=job.model,
                    db=session,
                    hints=hints,
                )
            logger.info(
                "statement.parse.extraction_completed",
                audit_event="statement.parse.extraction_completed",
                request_id=request_id,
                statement_id=str(statement_id),
                model_to_use=job.model,
                will_use_force_model=bool(job.model),
                file_type=file_type,
            )
            checkpoint("extraction_completed")
        except StaleRun:
            await session.rollback()
            logger.warning(
                "statement.run.heartbeat_lost_cancelled",
                run_id=str(job.run_id),
                statement_id=str(statement_id),
                request_id=request_id,
            )
            return StatementIngestionOutcome(statement_id=statement_id, status=StatementIngestionStatus.RUN_STALE)
        except ExtractionError as exc:
            await handle_parse_failure(
                statement,
                session,
                job=job,
                message=str(exc),
                phase=current_phase,
                progress=None,
                model_to_use=job.model,
                error_type=type(exc).__name__,
            )
            return StatementIngestionOutcome(statement_id=statement_id, status=StatementIngestionStatus.SOURCE_REJECTED)
        except Exception as exc:
            logger.exception(
                "Background parsing failed unexpectedly",
                statement_id=str(statement_id),
                request_id=request_id,
                phase=current_phase,
                model_to_use=job.model,
                error_type=type(exc).__name__,
            )
            await session.rollback()
            raise RetryableStatementIngestionError(f"Statement extraction application failure: {exc}") from exc

        try:
            await session.flush()
            await session.refresh(statement)

            result_payload = (statement.extraction_metadata or {}).get("statement_extraction_result")
            if not isinstance(result_payload, dict):
                raise RuntimeError("statement extraction result was not persisted")
            persisted_result = StatementExtractionResult.from_payload(result_payload)
            if persisted_result != extraction_result:
                raise RuntimeError("persisted statement extraction result changed source facts")

            occurred_at = statement.created_at or datetime.now(UTC)
            if occurred_at.tzinfo is None:
                occurred_at = occurred_at.replace(tzinfo=UTC)
            trace_records = build_extraction_trace_records(
                extraction_result,
                user_id=job.user_id,
                execution_id=f"statement:{statement.id}:result:{extraction_result.result_id}",
                occurred_at=occurred_at,
            )
            await trace_emitter_factory(session).emit_many(trace_records)
            await persist_statement_extraction_result(
                session, statement=statement, result=persisted_result, source_trace_record_id=trace_records[0].record_id
            )

            await finish_run(session, job.run_id, extraction_result_id=statement.current_extraction_result_id)
            checkpoint("statement_persisted")
            auto_posted_count = await try_auto_approve_high_confidence_statement(
                session, statement.id, job.user_id, dependencies=posting_dependencies
            )
            await brokerage_router(
                summary=statement,
                db=session,
                user_id=job.user_id,
                filename=job.filename,
                institution=job.institution,
                payload=_extract_brokerage_payload_from_metadata(statement.extraction_metadata),
                request_id=request_id,
                model_to_use=job.model,
            )
            await session.commit()
            logger.info(
                "statement.parse.completed",
                audit_event="statement.parse.completed",
                request_id=request_id,
                statement_id=str(statement_id),
                phase="parse_completed",
                duration_ms=round((clock() - start_time) * 1000, 2),
                transactions_count=len(extraction_result.transactions),
                auto_posted_count=auto_posted_count,
            )
            record_statement_parse_outcome(
                outcome="rejected" if statement.status is BankStatementStatus.REJECTED else "success"
            )
            return StatementIngestionOutcome(
                statement_id=statement_id,
                status=StatementIngestionStatus.COMPLETED,
                transactions_count=len(extraction_result.transactions),
                auto_posted_count=auto_posted_count,
            )
        except StaleRun:
            await session.rollback()
            logger.warning(
                "statement.run.finish_stale", run_id=str(job.run_id), statement_id=str(statement_id), request_id=request_id
            )
            return StatementIngestionOutcome(statement_id=statement_id, status=StatementIngestionStatus.RUN_STALE)
        except Exception as exc:
            logger.exception(
                "Failed to finalize statement parsing",
                statement_id=str(statement_id),
                request_id=request_id,
                phase=current_phase,
                model_to_use=job.model,
                error_type=type(exc).__name__,
            )
            await session.rollback()
            raise RetryableStatementIngestionError(f"Statement finalization application failure: {exc}") from exc
