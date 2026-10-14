from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from src.routers import corrections
from tests.factories import AtomicTransactionFactory, UploadedDocumentFactory


async def test_post_create_correction_and_stats(client: AsyncClient, db, test_user):
    """AC-reconciliation.recovered-coverage.1: AC4.7.1: POST /corrections persists a correction and /corrections/stats reflects it."""
    document = await UploadedDocumentFactory.create_async(db, user_id=test_user.id)
    txn = await AtomicTransactionFactory.create_async(
        db,
        test_user.id,
        source_doc_id=document.id,
        description="Test purchase",
    )
    await db.commit()

    response = await client.post(
        "/corrections",
        json={
            "transaction_id": str(txn.id),
            "corrected_category": "Office Supplies",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["transaction_id"] == str(txn.id)
    assert body["corrected_category"] == "Office Supplies"

    stats = await client.get("/corrections/stats")
    assert stats.status_code == 200
    sbody = stats.json()
    assert sbody["total_corrections"] >= 1
    assert isinstance(sbody["top_corrections"], list)


def test_AC18_2_5_top_corrections_is_typed_pydantic_model():
    """AC-extraction.1802.5: AC18.2.5: top_corrections is typed as a TopCorrection Pydantic model.

    The stats response schema must declare ``top_corrections`` as a list of
    ``TopCorrection`` models (count: int, original_category: str | None,
    corrected_category: str), not an untyped ``list[dict]``.
    """
    # The model exists and carries the exact keys the service emits.
    item = corrections.TopCorrection(
        count=3,
        original_category=None,
        corrected_category="Transport",
    )
    assert item.count == 3
    assert item.original_category is None
    assert item.corrected_category == "Transport"

    # The response schema field is typed as list[TopCorrection], not list[dict].
    field = corrections.CorrectionStatsResponse.model_fields["top_corrections"]
    assert field.annotation == list[corrections.TopCorrection]

    # Raw service-shaped dicts coerce into the typed model.
    response = corrections.CorrectionStatsResponse(
        total_corrections=3,
        top_corrections=[
            {"count": 3, "original_category": None, "corrected_category": "Transport"},
        ],
        correction_rate_by_category={"None": 100.0},
    )
    assert isinstance(response.top_corrections[0], corrections.TopCorrection)
    assert response.top_corrections[0].corrected_category == "Transport"


async def test_create_correction_returns_404_when_transaction_is_missing(monkeypatch):
    """AC18.2.2: Corrections API maps missing transactions to 404 responses."""

    async def fail_record_correction(*_args, **_kwargs):
        raise ValueError("transaction not found")

    class CommitShouldNotRun:
        async def commit(self):
            raise AssertionError("commit should not run after correction lookup fails")

    monkeypatch.setattr(corrections, "record_correction", fail_record_correction)

    with pytest.raises(HTTPException) as exc_info:
        await corrections.create_correction(
            body=corrections.CorrectionRequest(
                transaction_id=uuid4(),
                corrected_category="Office Supplies",
            ),
            db=CommitShouldNotRun(),
            user_id=uuid4(),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "transaction not found"


async def test_post_correction_applies_classification_and_unblocks_stage1_approval(
    client: AsyncClient, db, test_user, monkeypatch
):
    """POST /corrections persists a canonical TransactionCategory onto TransactionClassification and unblocks Stage-1 approval."""
    from datetime import date
    from decimal import Decimal

    from src.config import settings
    from tests.api._statement_router_fixtures import (
        add_txn,
        build_statement,
        create_statement_account,
    )

    monkeypatch.setattr(settings, "enable_ai_classification", False)
    bank = await create_statement_account(db, test_user.id, "DBS Modal Review")
    statement = build_statement(test_user.id, "hash_modal_review_2432", 88)
    statement.account_id = bank.id
    statement.opening_balance = Decimal("100.00")
    statement.closing_balance = Decimal("80.00")
    db.add(statement)
    await db.flush()
    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 4),
        description="Opaque merchant",
        amount=Decimal("20.00"),
        direction="OUT",
    )
    await db.commit()

    blocked = await client.post(
        f"/statements/{statement.id}/review/approve",
        json={"create_account_if_missing": False, "auto_fill_default_categories": False},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"].startswith("Economic review required:")

    bad_dir = await client.post(
        "/corrections",
        json={"transaction_id": str(txn.id), "corrected_category": "SALARY"},
    )
    assert bad_dir.status_code == 400
    assert "does not fit" in bad_dir.json()["detail"]

    corr = await client.post(
        "/corrections",
        json={"transaction_id": str(txn.id), "corrected_category": "DINING"},
    )
    assert corr.status_code == 201
    assert corr.json()["corrected_category"] == "DINING"

    review = await client.get(f"/statements/{statement.id}/review")
    assert review.status_code == 200
    r_txn = review.json()["transactions"][0]
    assert r_txn["proposed_category"] == "DINING"
    assert r_txn["confidence_score"] == 100
    assert r_txn["confidence_tier"] == "HIGH"

    approved = await client.post(
        f"/statements/{statement.id}/review/approve",
        json={"create_account_if_missing": False, "auto_fill_default_categories": False},
    )
    assert approved.status_code == 200
    assert approved.json()["journal_entries_created"] == 1


async def test_post_correction_transfer_draft_is_posted_on_stage1_approval(
    client: AsyncClient, db, test_user, monkeypatch
):
    """POST /corrections with TRANSFER creates a user-confirmed draft that posts a Processing leg on approval."""
    from datetime import date
    from decimal import Decimal

    from src.config import settings
    from tests.api._statement_router_fixtures import (
        add_txn,
        build_statement,
        create_statement_account,
    )

    monkeypatch.setattr(settings, "enable_ai_classification", False)
    bank = await create_statement_account(db, test_user.id, "DBS Transfer Review")
    statement = build_statement(test_user.id, "hash_modal_transfer_2432", 88)
    statement.account_id = bank.id
    statement.opening_balance = Decimal("100.00")
    statement.closing_balance = Decimal("80.00")
    db.add(statement)
    await db.flush()
    txn = await add_txn(
        db,
        statement,
        txn_date=date(2025, 1, 5),
        description="Unlabeled movement",
        amount=Decimal("20.00"),
        direction="OUT",
    )
    await db.commit()

    corr = await client.post(
        "/corrections",
        json={"transaction_id": str(txn.id), "corrected_category": "TRANSFER"},
    )
    assert corr.status_code == 201

    approved = await client.post(
        f"/statements/{statement.id}/review/approve",
        json={"create_account_if_missing": False, "auto_fill_default_categories": False},
    )
    assert approved.status_code == 200
    assert approved.json()["journal_entries_created"] == 1
