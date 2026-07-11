"""Repro for #1391 — Stage-1 review presigned PDF URL uses the internal endpoint.

Synthetic data only. `get_statement_for_review` generates the review `pdf_url`
without `public=True`, so it uses the internal object-storage endpoint
(unreachable from a browser). The public client (S3_PUBLIC_ENDPOINT) exists and
is used by the extraction pipeline, but not by the review path.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_review_pdf_url_requests_public_endpoint(client: AsyncClient, db: AsyncSession, test_user, monkeypatch):
    from src.extraction import DocumentType, UploadedDocument
    from src.models.statement_enums import BankStatementStatus
    from src.models.statement_summary import StatementSummary

    file_hash = uuid4().hex
    statement = StatementSummary(
        user_id=test_user.id,
        file_hash=file_hash,
        institution="SynthBank",
        currency="SGD",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        opening_balance=Decimal("100.00"),
        closing_balance=Decimal("110.00"),
        status=BankStatementStatus.PARSED,
        confidence_score=90,
    )
    db.add(statement)
    await db.flush()
    document = UploadedDocument(
        user_id=test_user.id,
        file_path="synthetic-statement.pdf",
        file_hash=file_hash,
        original_filename="synthetic-statement.pdf",
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(document)
    await db.flush()
    statement.uploaded_document_id = document.id
    db.add(statement)
    await db.commit()

    calls: list[dict] = []

    class _RecordingStorage:
        def generate_presigned_url(self, *, key, expires_in=None, public=False):
            calls.append({"key": key, "public": public})
            return f"https://public.example.test/{key}"

    monkeypatch.setattr("src.routers.statements.StorageService", _RecordingStorage)

    resp = await client.get(f"/statements/{statement.id}/review")
    assert resp.status_code == 200, resp.text

    assert calls, "review did not request a presigned URL"
    assert any(c["public"] for c in calls), (
        "review pdf_url generated without public=True -> uses the internal "
        "object-storage endpoint, which a browser cannot reach"
    )
