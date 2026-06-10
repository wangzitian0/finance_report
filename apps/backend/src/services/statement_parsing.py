"""Background task functions for statement parsing."""

import time
from inspect import Parameter, signature
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import structlog
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from src.config import settings
from src.logger import get_logger
from src.models import BankStatement, BankStatementStatus
from src.services import ExtractionError, ExtractionService, StorageError, StorageService
from src.services.brokerage_positions import BrokeragePositionImportService, looks_like_brokerage_payload
from src.services.statement_posting import try_auto_approve_high_confidence_statement
from src.services.statement_summary import sync_statement_summary

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)
_brokerage_import_service = BrokeragePositionImportService()
PARSE_PROGRESS_PHASES = {
    5: "parse_started",
    10: "storage_url_resolved",
    20: "extraction_started",
    70: "extraction_completed",
    80: "statement_metadata_persisted",
    90: "transactions_persisted",
    100: "statement_persisted",
}


def _safe_error_message(message: str | None) -> str | None:
    return message[:500] if message else message


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


async def import_brokerage_payload_if_present(
    *,
    statement: BankStatement,
    db: AsyncSession,
    user_id: UUID,
    filename: str,
    institution: str | None,
    payload: dict[str, Any] | None,
    request_id: str | None = None,
    model_to_use: str | None = None,
) -> None:
    """Import parsed brokerage positions after statement parsing succeeds."""
    if not looks_like_brokerage_payload(payload, filename=filename, institution=institution or statement.institution):
        return

    request_id = request_id or str(uuid4())
    broker = None
    if payload:
        broker = payload.get("institution")
        if not broker and isinstance(payload.get("statement"), dict):
            broker = payload["statement"].get("institution")
    broker = broker or institution or statement.institution
    parsed_positions = _count_brokerage_positions(payload)
    logger.info(
        "statement.brokerage_import.started",
        audit_event="statement.brokerage_import.started",
        request_id=request_id,
        statement_id=str(statement.id),
        phase="brokerage_import_started",
        progress=statement.parsing_progress,
        model_to_use=model_to_use,
        broker=broker,
        parsed_positions=parsed_positions,
    )

    try:
        result = await _brokerage_import_service.import_positions(
            db,
            user_id=user_id,
            payload=payload or {},
            filename=filename,
            source_document_id=str(statement.id),
        )
        if result.parsed_positions == 0:
            statement.validation_error = _append_validation_note(
                statement.validation_error,
                "Brokerage import skipped: no positions detected in parsed brokerage payload",
            )
        await db.commit()
        logger.info(
            "statement.brokerage_import.completed",
            audit_event="statement.brokerage_import.completed",
            request_id=request_id,
            statement_id=str(statement.id),
            phase="brokerage_import_completed",
            progress=statement.parsing_progress,
            model_to_use=model_to_use,
            broker=result.broker,
            parsed_positions=result.parsed_positions,
            created_atomic_positions=result.created_atomic_positions,
            existing_atomic_positions=result.existing_atomic_positions,
            reconcile_created=result.reconcile_created,
            reconcile_updated=result.reconcile_updated,
            reconcile_disposed=result.reconcile_disposed,
        )
    except Exception as exc:
        logger.exception(
            "statement.brokerage_import.failed",
            audit_event="statement.brokerage_import.failed",
            request_id=request_id,
            statement_id=str(statement.id),
            phase="brokerage_import_failed",
            progress=statement.parsing_progress,
            model_to_use=model_to_use,
            error_type=type(exc).__name__,
            safe_error_message=_safe_error_message(str(exc)),
        )
        await db.rollback()
        refreshed = await db.get(BankStatement, statement.id)
        if refreshed is None:
            return
        refreshed.validation_error = _append_validation_note(
            refreshed.validation_error,
            "Brokerage import failed: parsed statement was saved but positions were not imported",
        )
        await db.commit()


async def handle_parse_failure(
    statement: BankStatement,
    db: AsyncSession,
    *,
    message: str | None,
    phase: str = "unknown",
    progress: int | None = None,
    model_to_use: str | None = None,
    error_type: str | None = None,
    request_id: str | None = None,
) -> None:
    """Handle parse failure by marking statement as REJECTED.

    This function handles error recovery when parsing fails:
    1. Attempts rollback if session is in error state
    2. Refreshes statement to get clean DB state
    3. Marks statement as REJECTED with error message

    Args:
        statement: The BankStatement object (may have expired session)
        db: AsyncSession for database operations
        message: Error message to store in validation_error
    """
    request_id = request_id or str(uuid4())
    statement_id = statement.id
    try:
        await db.rollback()
    except Exception as rollback_exc:
        logger.warning(
            "Rollback failed during parse failure handling",
            statement_id=str(statement_id),
            rollback_error=str(rollback_exc),
        )
    try:
        refreshed = await db.get(BankStatement, statement_id)
        if refreshed is None:
            logger.error(
                "Statement not found after rollback",
                statement_id=str(statement_id),
                reason=message,
            )
            return
        refreshed.status = BankStatementStatus.REJECTED
        refreshed.validation_error = message[:500] if message else message
        refreshed.confidence_score = 0
        refreshed.balance_validated = False
        await db.commit()
        logger.error(
            "statement.parse.failed",
            audit_event="statement.parse.failed",
            request_id=request_id,
            statement_id=str(refreshed.id),
            phase=phase,
            progress=progress if progress is not None else refreshed.parsing_progress,
            model_to_use=model_to_use,
            error_type=error_type,
            safe_error_message=_safe_error_message(message),
        )
    except Exception as inner_exc:
        logger.exception(
            "Failed to mark statement as rejected",
            statement_id=str(statement_id),
            original_error=message,
            inner_error=str(inner_exc),
        )


def _filter_failure_handler_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    try:
        parameters = signature(handle_parse_failure).parameters
    except (TypeError, ValueError):
        return kwargs
    if any(parameter.kind == Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return kwargs
    return {key: value for key, value in kwargs.items() if key in parameters}


async def _handle_parse_failure(
    statement: BankStatement,
    db: AsyncSession,
    *,
    message: str | None,
    phase: str,
    progress: int | None,
    model_to_use: str | None,
    error_type: str | None,
    request_id: str,
) -> None:
    await handle_parse_failure(
        statement,
        db,
        **_filter_failure_handler_kwargs(
            {
                "message": message,
                "phase": phase,
                "progress": progress,
                "model_to_use": model_to_use,
                "error_type": error_type,
                "request_id": request_id,
            }
        ),
    )


async def parse_statement_background(
    *,
    statement_id: UUID,
    filename: str,
    institution: str | None,
    user_id: UUID,
    account_id: UUID | None,
    file_hash: str,
    storage_key: str,
    content: bytes,
    model: str | None,
    session_maker: async_sessionmaker[AsyncSession],
    request_id: str | None = None,
) -> None:
    """Background task to parse a bank statement document.

    This function runs asynchronously to:
    1. Generate presigned URL for storage (if possible)
    2. Parse document using AI models
    3. Update statement with parsed data
    4. Handle errors and mark statement appropriately

    Args:
        statement_id: UUID of the BankStatement to parse
        filename: Original filename of uploaded file
        institution: Bank institution name (or None for auto-detect)
        user_id: User ID who uploaded the statement
        account_id: Optional account ID to associate with statement
        file_hash: SHA256 hash of file content
        storage_key: Storage key for the uploaded file
        content: Raw file content bytes
        model: AI model to use for parsing (or None for default)
        session_maker: AsyncSession maker for background DB operations
        request_id: Optional request ID for tracing
    """
    request_id = request_id or str(uuid4())
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
    start_time = time.perf_counter()

    async with session_maker() as session:
        statement = await session.get(
            BankStatement,
            statement_id,
            options=[selectinload(BankStatement.transactions)],
        )
        if not statement:
            logger.error(
                "Statement not found in DB for background parsing",
                statement_id=str(statement_id),
                request_id=request_id,
            )
            return

        current_phase = "parse_started"
        current_progress = 0

        async def update_progress(progress: int) -> None:
            nonlocal current_phase, current_progress
            current_phase = PARSE_PROGRESS_PHASES[progress]
            current_progress = progress
            statement.parsing_progress = progress
            await session.commit()
            logger.info(
                "statement.parse.checkpoint",
                audit_event="statement.parse.checkpoint",
                request_id=request_id,
                statement_id=str(statement_id),
                phase=current_phase,
                progress=current_progress,
                model_to_use=model_to_use,
                file_type=file_type,
            )

        await update_progress(5)

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

        await update_progress(10)

        if file_type == "pdf" and not file_url:
            logger.info(
                "No public URL available for PDF; will use base64-encoded content",
                statement_id=str(statement_id),
            )

        service = ExtractionService()
        try:
            await update_progress(20)
            parsed_statement, transactions = await service.parse_document(
                file_path=Path(filename),
                institution=institution,
                user_id=user_id,
                file_type=file_type,
                account_id=account_id,
                file_content=content,
                file_hash=file_hash,
                file_url=file_url,
                original_filename=filename,
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
            await update_progress(70)
        except ExtractionError as exc:
            await _handle_parse_failure(
                statement,
                session,
                message=str(exc),
                phase=current_phase,
                progress=current_progress,
                model_to_use=model_to_use,
                error_type=type(exc).__name__,
                request_id=request_id,
            )
            return
        except Exception as exc:
            logger.exception(
                "Background parsing failed unexpectedly",
                statement_id=str(statement_id),
                request_id=request_id,
                phase=current_phase,
                progress=current_progress,
                model_to_use=model_to_use,
                error_type=type(exc).__name__,
            )
            await _handle_parse_failure(
                statement,
                session,
                message=f"Parsing failed: {exc}",
                phase=current_phase,
                progress=current_progress,
                model_to_use=model_to_use,
                error_type=type(exc).__name__,
                request_id=request_id,
            )
            return

        try:
            statement.institution = parsed_statement.institution
            statement.account_last4 = parsed_statement.account_last4
            statement.currency = parsed_statement.currency
            statement.period_start = parsed_statement.period_start
            statement.period_end = parsed_statement.period_end
            statement.opening_balance = parsed_statement.opening_balance
            statement.closing_balance = parsed_statement.closing_balance
            statement.extraction_metadata = parsed_statement.extraction_metadata
            await session.commit()

            await update_progress(80)

            for existing_tx in list(statement.transactions):
                await session.delete(existing_tx)
            await session.flush()

            if settings.enable_layer_0_write:
                for txn in transactions:
                    txn.statement = statement
                statement.transactions = list(transactions)

            await update_progress(90)

            from src.services.evidence_graph_integration import EvidenceGraphIntegrationService

            evidence_graph = EvidenceGraphIntegrationService()
            await evidence_graph.record_statement_parse(
                session,
                user_id=user_id,
                statement=statement,
                transactions=list(statement.transactions),
            )
            await evidence_graph.record_statement_layer2_lineage(
                session,
                user_id=user_id,
                statement=statement,
                transactions=list(statement.transactions),
            )

            statement.confidence_score = parsed_statement.confidence_score
            statement.balance_validated = parsed_statement.balance_validated
            statement.validation_error = parsed_statement.validation_error
            statement.status = parsed_statement.status

            await sync_statement_summary(session, statement)

            await update_progress(100)
            auto_posted_count = await try_auto_approve_high_confidence_statement(session, statement.id, user_id)
            await session.commit()
            await import_brokerage_payload_if_present(
                statement=statement,
                db=session,
                user_id=user_id,
                filename=filename,
                institution=institution,
                payload=getattr(parsed_statement, "_extracted_payload", None),
                request_id=request_id,
                model_to_use=model_to_use,
            )
            duration = time.perf_counter() - start_time
            logger.info(
                "statement.parse.completed",
                audit_event="statement.parse.completed",
                request_id=request_id,
                statement_id=str(statement_id),
                phase="parse_completed",
                progress=100,
                duration_ms=round(duration * 1000, 2),
                transactions_count=len(transactions),
                auto_posted_count=auto_posted_count,
            )
        except Exception as exc:
            logger.exception(
                "Failed to finalize statement parsing",
                statement_id=str(statement_id),
                request_id=request_id,
                phase=current_phase,
                progress=current_progress,
                model_to_use=model_to_use,
                error_type=type(exc).__name__,
            )
            await _handle_parse_failure(
                statement,
                session,
                message=f"Finalize failed: {exc}",
                phase=current_phase,
                progress=current_progress,
                model_to_use=model_to_use,
                error_type=type(exc).__name__,
                request_id=request_id,
            )
