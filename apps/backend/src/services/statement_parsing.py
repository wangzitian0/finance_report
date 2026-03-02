"""Background task functions for statement parsing."""

import time
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import structlog
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from src.config import settings
from src.logger import get_logger
from src.models import BankStatement, BankStatementStatus
from src.services import ExtractionError, ExtractionService, StorageError, StorageService

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


async def handle_parse_failure(
    statement: BankStatement,
    db: AsyncSession,
    *,
    message: str | None,
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
        logger.error("Statement parsing failed", statement_id=str(refreshed.id), reason=message)
    except Exception as inner_exc:
        logger.exception(
            "Failed to mark statement as rejected",
            statement_id=str(statement_id),
            original_error=message,
            inner_error=str(inner_exc),
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
    # Bind request_id to context for this background task
    structlog.contextvars.bind_contextvars(
        request_id=request_id, statement_id=str(statement_id), task="parse_statement"
    )

    logger.info("Starting background parsing", filename=filename)
    start_time = time.perf_counter()

    async with session_maker() as session:
        statement = await session.get(
            BankStatement,
            statement_id,
            options=[selectinload(BankStatement.transactions)],
        )
        if not statement:
            logger.error("Statement not found in DB for background parsing")
            return

        async def update_progress(progress: int) -> None:
            statement.parsing_progress = progress
            await session.commit()

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

        file_type = filename.rsplit(".", 1)[-1].lower() if "." in filename else "pdf"
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
                "Background task enqueued for statement parsing",
                statement_id=str(statement_id),
                model_to_use=model,
                will_use_force_model=bool(model),
                file_type=file_type,
            )
            await update_progress(70)
        except ExtractionError as exc:
            await handle_parse_failure(statement, session, message=str(exc))
            return
        except Exception as exc:
            logger.exception("Background parsing failed unexpectedly")
            await handle_parse_failure(statement, session, message=f"Parsing failed: {exc}")
            return

        try:
            statement.institution = parsed_statement.institution
            statement.account_last4 = parsed_statement.account_last4
            statement.currency = parsed_statement.currency
            statement.period_start = parsed_statement.period_start
            statement.period_end = parsed_statement.period_end
            statement.opening_balance = parsed_statement.opening_balance
            statement.closing_balance = parsed_statement.closing_balance
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

            statement.confidence_score = parsed_statement.confidence_score
            statement.balance_validated = parsed_statement.balance_validated
            statement.validation_error = parsed_statement.validation_error
            statement.status = parsed_statement.status

            await update_progress(100)
            duration = time.perf_counter() - start_time
            logger.info(
                "Background parsing completed",
                duration_ms=round(duration * 1000, 2),
                transactions_count=len(transactions),
            )
        except Exception as exc:
            logger.exception("Failed to finalize statement parsing")
            await handle_parse_failure(statement, session, message=f"Finalize failed: {exc}")
