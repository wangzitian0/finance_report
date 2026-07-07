"""#1408: brokerage positions must not be auto-imported at parse.

Synthetic data only. Brokerage positions used to be auto-imported into AtomicPosition
(L2) + ManagedPosition (L3) DURING parse, before any human review, so a still-
``pending_review`` brokerage statement immediately inflated the live portfolio
(``/portfolio/holdings``, ``/portfolio/summary``, ``/reports/net-worth/*``).

The fix does NOT import at parse: a detected brokerage payload is only routed to the
Stage-1 review queue (``pending_review``). Positions are created only by the explicit,
user-initiated ``POST /statements/{statement_id}/brokerage/import`` endpoint, which
recovers the payload from ``extraction_metadata``.

Brokerage statements canNOT go through ``/review/approve`` (the DB check
``ck_statement_summaries_approved_complete`` requires opening/closing balances brokerage
statements do not have), so the gate is "no auto-import at parse -> explicit import
endpoint", NOT "import on approval".
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.extension.statement_parsing import route_brokerage_for_review_if_present
from src.models.layer1 import DocumentType, UploadedDocument
from src.models.layer2 import AtomicPosition
from src.models.statement_enums import BankStatementStatus, Stage1Status
from src.models.statement_summary import StatementSummary

_ASSET = "GATED_TEST_STOCK"


def _payload(*, with_positions: bool = True) -> dict:
    positions = (
        [
            {
                "symbol": _ASSET,
                "snapshot_date": "2026-05-18",
                "quantity": "10",
                "market_value": "1900.25",
                "currency": "SGD",
                "asset_type": "stock",
            }
        ]
        if with_positions
        else []
    )
    return {
        "institution": "Moomoo",
        "statement": {"period_end": "2026-05-18", "currency": "SGD"},
        "positions": positions,
    }


async def _make_brokerage_statement(
    db: AsyncSession,
    user_id,
    *,
    status: BankStatementStatus,
    stage1: Stage1Status | None,
    with_positions: bool = True,
) -> StatementSummary:
    stmt = StatementSummary(
        user_id=user_id,
        file_hash=uuid4().hex,
        institution="Moomoo",
        account_last4="1234",
        currency="SGD",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 18),
        status=status,
        stage1_status=stage1,
        confidence_score=60,
        extraction_metadata=_payload(with_positions=with_positions),
    )
    db.add(stmt)
    await db.flush()
    doc = UploadedDocument(
        user_id=user_id,
        file_path="moomoo.pdf",
        file_hash=stmt.file_hash,
        original_filename="moomoo.pdf",
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(doc)
    await db.flush()
    stmt.uploaded_document_id = doc.id
    await db.commit()
    await db.refresh(stmt)
    return stmt


async def _position_count(db: AsyncSession, user_id) -> int:
    return await db.scalar(select(func.count()).select_from(AtomicPosition).where(AtomicPosition.user_id == user_id))


@pytest.mark.asyncio
async def test_AC1_parse_routing_imports_no_positions_and_marks_pending_review(db: AsyncSession, test_user):
    """AC1: parse routing of a brokerage payload imports no positions and marks pending_review."""
    stmt = await _make_brokerage_statement(db, test_user.id, status=BankStatementStatus.PARSED, stage1=None)

    await route_brokerage_for_review_if_present(
        summary=stmt,
        db=db,
        user_id=test_user.id,
        filename="moomoo.pdf",
        institution="Moomoo",
        payload=_payload(),
    )

    assert await _position_count(db, test_user.id) == 0, (
        "brokerage positions were imported at parse before any human review"
    )
    await db.refresh(stmt)
    assert stmt.stage1_status == Stage1Status.PENDING_REVIEW


@pytest.mark.asyncio
async def test_AC1_AC2_pending_review_absent_from_holdings_until_explicit_import(
    client: AsyncClient, db: AsyncSession, test_user
):
    """AC1 + AC2 end-to-end: pending-review brokerage is absent from holdings; the explicit
    import endpoint is the only path that surfaces the positions."""
    stmt = await _make_brokerage_statement(
        db, test_user.id, status=BankStatementStatus.PARSED, stage1=Stage1Status.PENDING_REVIEW
    )

    before = await client.get("/portfolio/holdings")
    assert before.status_code == 200
    assert before.json() == [], "pending-review brokerage positions must not appear in holdings"

    imported = await client.post(f"/statements/{stmt.id}/brokerage/import")
    assert imported.status_code == 200, imported.text

    after = await client.get("/portfolio/holdings")
    assert after.status_code == 200
    identifiers = {h.get("asset_identifier") or h.get("ticker") for h in after.json()}
    assert _ASSET in identifiers, "explicit brokerage import should surface the positions in holdings"


@pytest.mark.asyncio
async def test_AC6_zero_position_brokerage_payload_still_routes_to_pending_review(db: AsyncSession, test_user):
    """AC6: a brokerage payload with 0 positions still routes to pending_review (with a note)."""
    stmt = await _make_brokerage_statement(
        db, test_user.id, status=BankStatementStatus.PARSED, stage1=None, with_positions=False
    )

    await route_brokerage_for_review_if_present(
        summary=stmt,
        db=db,
        user_id=test_user.id,
        filename="moomoo.pdf",
        institution="Moomoo",
        payload=_payload(with_positions=False),
    )

    assert await _position_count(db, test_user.id) == 0
    await db.refresh(stmt)
    assert stmt.stage1_status == Stage1Status.PENDING_REVIEW
    assert stmt.validation_error is not None
    assert "no positions detected" in stmt.validation_error
