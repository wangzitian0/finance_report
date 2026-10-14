"""EPIC-018 AC18.17.2 (#1546): the backfill/re-extract entry point is live."""

from __future__ import annotations

from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from src.extraction.extension.transaction_classification import CategoryProposal, TransactionCategory
from src.extraction.orm.layer3 import TransactionClassification
from tests.factories import AtomicTransactionFactory


@pytest.fixture
def enabled_flag(monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings, "enable_ai_classification", True)


@pytest.fixture
def stub_proposer(monkeypatch):
    async def proposer(transactions, policy):
        return [CategoryProposal(category=TransactionCategory.SALARY.value, confidence=95) for _ in transactions]

    monkeypatch.setattr("src.extraction.extension.transaction_classification.propose_categories", proposer)
    return proposer


@pytest.mark.asyncio
@pytest.mark.usefixtures("review_path")
async def test_AC18_17_2_backfill_endpoint_classifies_then_is_idempotent(
    client: AsyncClient, db, test_user, enabled_flag, stub_proposer
):
    """AC-extraction.1817.2: AC18.17.2: POST /classifications/backfill classifies the caller's
    not-yet-classified transactions once; a second call is an idempotent no-op."""
    for i in range(2):
        await AtomicTransactionFactory.create_async(
            db, user_id=test_user.id, description=f"Salary {i}", txn_date=date(2026, 5, 10)
        )
    await db.commit()

    first = await client.post("/classifications/backfill")
    assert first.status_code == 200, first.text
    assert first.json()["classified"] == 2

    second = await client.post("/classifications/backfill")
    assert second.status_code == 200
    assert second.json()["classified"] == 0  # idempotent

    rows = (await db.execute(select(TransactionClassification))).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_AC18_17_2_backfill_endpoint_is_flag_gated(
    client: AsyncClient, db, test_user, stub_proposer, monkeypatch
):
    from src.config import settings

    monkeypatch.setattr(settings, "enable_ai_classification", False)
    await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="Salary")
    await db.commit()

    resp = await client.post("/classifications/backfill")
    assert resp.status_code == 200
    assert resp.json()["classified"] == 0


@pytest.mark.asyncio
@pytest.mark.usefixtures("review_path")
async def test_AC18_17_2_tail_txns_are_reattempted_without_duplication(
    client: AsyncClient, db, test_user, enabled_flag, monkeypatch
):
    """AC18.17.2 (CR #1572): a tail transaction (low confidence => no row) stays a
    candidate and is re-attempted on the next run BY DESIGN (re-extract semantics),
    while never duplicating or rewriting anything."""

    async def low_conf_proposer(transactions, policy):
        return [CategoryProposal(category=TransactionCategory.SALARY.value, confidence=10) for _ in transactions]

    monkeypatch.setattr("src.extraction.extension.transaction_classification.propose_categories", low_conf_proposer)
    await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="??? mystery")
    await db.commit()

    first = await client.post("/classifications/backfill")
    assert first.json() == {"classified": 0, "candidates": 1}  # tail: no row written
    second = await client.post("/classifications/backfill")
    assert second.json() == {"classified": 0, "candidates": 1}  # re-attempted, still no dup

    rows = (await db.execute(select(TransactionClassification))).scalars().all()
    assert rows == []


def _answers(monkeypatch, category: str | None, confidence: int = 70) -> None:
    async def proposer(transactions, policy):
        if category is None:
            return [None for _ in transactions]
        return [CategoryProposal(category=category, confidence=confidence) for _ in transactions]

    monkeypatch.setattr("src.extraction.extension.transaction_classification.propose_categories", proposer)


@pytest.mark.asyncio
async def test_AC_extraction_auto_accept_11_backfill_counts_the_rows_it_wrote_and_does_not_retry_them(
    client: AsyncClient, db, test_user, enabled_flag, monkeypatch
):
    """AC-extraction.auto-accept.11: with the setting on, a low score gets a row on the general account.

    The row counts in `classified`, and the next run has no candidate left. A transfer draft counts too.
    """
    from src.ledger import Account

    low = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="Mystery payment")
    await db.commit()
    _answers(monkeypatch, "DINING", 10)

    first = await client.post("/classifications/backfill")
    second = await client.post("/classifications/backfill")

    assert first.json() == {"classified": 1, "candidates": 1}
    assert second.json() == {"classified": 0, "candidates": 0}
    row = (await db.execute(select(TransactionClassification))).scalar_one()
    assert row.atomic_txn_id == low.id
    assert (await db.get(Account, row.account_id)).name == "General Expense (SGD)"

    transfer = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="Wallet top up")
    await db.commit()
    _answers(monkeypatch, "TRANSFER", 70)

    third = await client.post("/classifications/backfill")

    assert third.json() == {"classified": 1, "candidates": 1}
    draft = (
        await db.execute(
            select(TransactionClassification).where(TransactionClassification.atomic_txn_id == transfer.id)
        )
    ).scalar_one()
    assert draft.tags["category"] == "TRANSFER"


@pytest.mark.asyncio
async def test_AC_extraction_auto_accept_11_backfill_retries_a_row_without_an_answer(
    client: AsyncClient, db, test_user, enabled_flag, monkeypatch
):
    """AC-extraction.auto-accept.11: an outage writes no row, so the next run tries the row again."""
    await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="Mystery payment")
    await db.commit()
    _answers(monkeypatch, None)

    first = await client.post("/classifications/backfill")
    second = await client.post("/classifications/backfill")
    _answers(monkeypatch, "DINING", 90)
    third = await client.post("/classifications/backfill")

    assert first.json() == {"classified": 0, "candidates": 1}
    assert second.json() == {"classified": 0, "candidates": 1}
    assert third.json() == {"classified": 1, "candidates": 1}
    assert len((await db.execute(select(TransactionClassification))).scalars().all()) == 1
