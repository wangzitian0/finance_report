"""Test helpers that exercise the production statement composition boundary."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.composition import compose_statement_ingestion_use_case, compose_statement_posting_dependencies
from src.extraction import (
    DocumentSource,
    ParseJob,
    StatementExtractionResult,
    StatementIngestionOutcome,
    StatementPostingDependencies,
    StatementSummary,
)
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_validation import resolve_statement_transactions
from src.extraction.orm.layer2 import AtomicTransaction


async def execute_statement_ingestion(
    job: ParseJob,
    *,
    content: bytes,
    session_maker: async_sessionmaker[AsyncSession],
) -> StatementIngestionOutcome:
    """Execute through the same explicit composition used by API and Prefect."""
    return await compose_statement_ingestion_use_case(session_maker=session_maker).execute(
        job,
        content=content,
    )


def posting_dependencies() -> StatementPostingDependencies:
    """Return the production-shaped dependency bundle for posting tests."""
    return compose_statement_posting_dependencies()


async def parse_and_load_statement_projection(
    service: ExtractionService,
    *,
    db: AsyncSession,
    user_id,
    source: DocumentSource,
    institution: str | None,
    file_type: str = "pdf",
    account_id=None,
    force_model: str | None = None,
) -> tuple[StatementExtractionResult, StatementSummary, list[AtomicTransaction]]:
    """Parse to the canonical result, then read its persisted ODS/DWD projection."""
    result = await service.parse_document(
        source,
        institution=institution,
        user_id=user_id,
        file_type=file_type,
        account_id=account_id,
        force_model=force_model,
        db=db,
    )
    statement = (
        await db.execute(
            select(StatementSummary)
            .where(StatementSummary.user_id == user_id)
            .where(StatementSummary.file_hash == result.source_content_digest)
        )
    ).scalar_one()
    transactions = await resolve_statement_transactions(db, statement)
    return result, statement, transactions
