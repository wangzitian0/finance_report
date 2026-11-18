from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import BankStatementStatus, DocumentType, ExtractedPositionFact, ExtractionMethod, SourceProvenance, Stage1Status, StatementEvidenceType, StatementExtractionResult, StatementSourceType, UploadedDocument
from src.extraction.extension.statement_parsing import route_brokerage_for_review_if_present
from src.extraction.orm.layer2 import AtomicPosition
from src.extraction.orm.statement_summary import StatementSummary

_ASSET = "GATED_TEST_STOCK"


def _payload(*, with_positions: bool = True) -> dict:
    positions = [{"symbol": _ASSET, "snapshot_date": "2026-05-18", "quantity": "10", "market_value": "1900.25", "currency": "SGD", "asset_type": "stock"}] if with_positions else []
    return {"institution": "Moomoo", "statement": {"period_end": "2026-05-18", "currency": "SGD"}, "positions": positions}


async def _make_brokerage_statement(db: AsyncSession, user_id, *, stage1: Stage1Status | None, with_positions: bool = True) -> StatementSummary:
    positions = (ExtractedPositionFact(fact_id="gated-test-stock-1", symbol=_ASSET, quantity=Decimal("10"), market_value=Decimal("1900.25"), currency="SGD", confidence=Decimal("0.60"), asset_type="stock"),) if with_positions else ()
    result = StatementExtractionResult.create(
        producer_version="extractor@brokerage-gate-test",
        source_content_digest="c" * 64,
        source_type=StatementSourceType.BROKERAGE,
        evidence_type=StatementEvidenceType.POSITION_SNAPSHOT,
        statement_currency="SGD",
        institution="Moomoo",
        account_last4="1234",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 18),
        balances=(),
        transactions=(),
        positions=positions,
        confidence=Decimal("0.60"),
        balance_validated=None,
        warnings=(),
        review_reasons=("position import requires explicit review",),
        provenance=SourceProvenance(intake_mode="pdf", method=ExtractionMethod.GOLDEN_FIXTURE, provider="fixture-provider", model="fixture-model-v1"),
    )
    stmt = StatementSummary(user_id=user_id, file_hash=uuid4().hex, institution="Moomoo", account_last4="1234", currency="SGD", period_start=date(2026, 5, 1), period_end=date(2026, 5, 18), status=BankStatementStatus.PARSED, stage1_status=stage1, confidence_score=60, extraction_metadata={"statement_extraction_result": result.to_payload()})
    db.add(stmt)
    await db.flush()
    doc = UploadedDocument(user_id=user_id, file_path="moomoo.pdf", file_hash=stmt.file_hash, original_filename="moomoo.pdf", document_type=DocumentType.BANK_STATEMENT)
    db.add(doc)
    await db.flush()
    stmt.uploaded_document_id = doc.id
    await db.commit()
    await db.refresh(stmt)
    return stmt


@pytest.mark.parametrize("with_positions", [True, False])
async def test_AC1_AC6_parse_routing_imports_no_positions_and_marks_pending_review(db: AsyncSession, test_user, with_positions):
    stmt = await _make_brokerage_statement(db, test_user.id, stage1=None, with_positions=with_positions)
    await route_brokerage_for_review_if_present(summary=stmt, db=db, user_id=test_user.id, filename="moomoo.pdf", institution="Moomoo", payload=_payload(with_positions=with_positions))
    count = await db.scalar(select(func.count()).select_from(AtomicPosition).where(AtomicPosition.user_id == test_user.id))
    await db.refresh(stmt)
    assert (count, stmt.stage1_status, True if with_positions else (stmt.validation_error is not None and "no positions detected" in stmt.validation_error)) == (0, Stage1Status.PENDING_REVIEW, True)


async def test_AC1_AC2_pending_review_absent_from_holdings_until_explicit_import(client: AsyncClient, db: AsyncSession, test_user):
    stmt = await _make_brokerage_statement(db, test_user.id, stage1=Stage1Status.PENDING_REVIEW)
    before = await client.get("/portfolio/holdings")
    imported = await client.post("/portfolio/brokerage-imports", json={"statement_id": str(stmt.id)})
    after = await client.get("/portfolio/holdings")
    assert (before.status_code, before.json()["items"], imported.status_code, after.status_code, _ASSET in {h.get("asset_identifier") or h.get("ticker") for h in after.json()["items"]}) == (200, [], 200, 200, True)
