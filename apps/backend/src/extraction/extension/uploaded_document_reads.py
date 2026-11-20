"""Read-only ``UploadedDocument`` lookups for infra-layer consumers (#1675 D3).

``platform``/``runtime`` (L1 infra) need a handful of ``UploadedDocument``
(L3 domain) facts — a display filename, whether a storage key is still
referenced — but must not import the ORM class directly (an infra-imports-
domain layering violation, caught when ``layer1.py`` first moved into this
package). These functions are the published seam: infra calls them instead
of querying ``UploadedDocument`` itself.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.orm.layer1 import UploadedDocument
from src.extraction.orm.statement_summary import StatementSummary


async def resolve_uploaded_document(
    db: AsyncSession, statement: StatementSummary, user_id: UUID
) -> UploadedDocument | None:
    """Resolve the user-owned uploaded document backing a statement."""
    if statement.uploaded_document_id is not None:
        doc = await db.get(UploadedDocument, statement.uploaded_document_id)
        if doc is not None and doc.user_id == user_id:
            return doc
    return (
        await db.execute(
            select(UploadedDocument).where(
                UploadedDocument.user_id == user_id, UploadedDocument.file_hash == statement.file_hash
            )
        )
    ).scalar_one_or_none()


async def get_uploaded_document_filenames(db: AsyncSession, document_ids: Iterable[UUID]) -> dict[UUID, str]:
    """Bulk ``document_id -> original_filename`` for the given ids (missing ids are omitted).

    Replaces a per-caller join against ``UploadedDocument`` with one extra query.
    """
    ids = list(document_ids)
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(UploadedDocument.id, UploadedDocument.original_filename).where(UploadedDocument.id.in_(ids))
        )
    ).all()
    return {doc_id: filename for doc_id, filename in rows}


KNOWN_STORAGE_PATHS_CHUNK_SIZE = 500


async def get_known_storage_paths(db: AsyncSession, candidate_paths: Iterable[str]) -> set[str]:
    """Which of the given storage keys have a corresponding ``UploadedDocument`` row."""
    paths = list(candidate_paths)
    if not paths:
        return set()
    known: set[str] = set()
    for start in range(0, len(paths), KNOWN_STORAGE_PATHS_CHUNK_SIZE):
        batch = paths[start : start + KNOWN_STORAGE_PATHS_CHUNK_SIZE]
        result = await db.execute(select(UploadedDocument.file_path).where(UploadedDocument.file_path.in_(batch)))
        known.update(row[0] for row in result.all())
    return known
