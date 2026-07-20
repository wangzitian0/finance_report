"""Extraction-owned source identity and ordinary lifecycle commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.base.types import RetireStatementCommand
from src.extraction.orm.layer1 import DocumentStatus, DocumentType, UploadedDocument
from src.extraction.orm.statement_enums import BankStatementStatus
from src.extraction.orm.statement_summary import StatementSummary


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceIdentityCommand:
    """Typed values needed to resolve one immutable uploaded source."""

    user_id: UUID
    file_path: str
    file_hash: str
    original_filename: str
    document_type: DocumentType
    extraction_metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.user_id, UUID):
            raise TypeError("user_id must be a UUID")
        if not isinstance(self.document_type, DocumentType):
            raise TypeError("document_type must be a DocumentType")
        for name in ("file_path", "file_hash", "original_filename"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")


async def resolve_source_identity(
    db: AsyncSession,
    command: SourceIdentityCommand,
) -> tuple[UploadedDocument, bool]:
    """Insert a source under a savepoint or return the concurrent winner."""
    candidate = UploadedDocument(
        user_id=command.user_id,
        file_path=command.file_path,
        file_hash=command.file_hash,
        original_filename=command.original_filename,
        document_type=command.document_type,
        extraction_metadata=command.extraction_metadata,
    )
    try:
        async with db.begin_nested():
            db.add(candidate)
            await db.flush()
        return candidate, True
    except IntegrityError:
        winner = (
            await db.execute(
                select(UploadedDocument).where(
                    UploadedDocument.user_id == command.user_id,
                    UploadedDocument.file_hash == command.file_hash,
                )
            )
        ).scalar_one_or_none()
        if winner is None:
            raise RuntimeError("source identity conflict did not expose a canonical winner") from None
        return winner, False


async def retire_statement(
    db: AsyncSession,
    command: RetireStatementCommand,
) -> StatementSummary:
    """Retire product visibility while retaining source content and lineage."""
    statement = (
        await db.execute(
            select(StatementSummary)
            .where(
                StatementSummary.id == command.statement_id,
                StatementSummary.user_id == command.user_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if statement is None:
        raise ValueError("Statement not found or access denied")

    statement.status = BankStatementStatus.RETIRED
    if statement.uploaded_document_id is not None:
        document = await db.get(UploadedDocument, statement.uploaded_document_id)
        if document is not None and document.user_id == command.user_id:
            document.status = DocumentStatus.RETIRED
    await db.flush()
    return statement


__all__ = [
    "RetireStatementCommand",
    "SourceIdentityCommand",
    "resolve_source_identity",
    "retire_statement",
]
