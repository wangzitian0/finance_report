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


async def get_known_storage_paths(db: AsyncSession, candidate_paths: Iterable[str]) -> set[str]:
    """Which of the given storage keys have a corresponding ``UploadedDocument`` row."""
    paths = list(candidate_paths)
    if not paths:
        return set()
    result = await db.execute(select(UploadedDocument.file_path).where(UploadedDocument.file_path.in_(paths)))
    return {row[0] for row in result.all()}
