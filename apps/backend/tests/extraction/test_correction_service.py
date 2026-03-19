"""EPIC-018 Phase 2: Tests for CorrectionService and feedback learning loop."""

import time
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.prompts.statement import get_parsing_prompt
from src.services.correction_service import (
    _correction_cache,
    clear_all_correction_cache,
    get_correction_stats,
    get_few_shot_examples,
    invalidate_correction_cache,
    record_correction,
)
from tests.factories import (
    BankStatementFactory,
    BankStatementTransactionFactory,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear correction cache before each test."""
    clear_all_correction_cache()
    yield
    clear_all_correction_cache()


@pytest.mark.asyncio
async def test_record_correction_stores_original_category(db, test_user):
    """AC18.2.1: CorrectionLog records original_category from transaction."""
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)
    txn = await BankStatementTransactionFactory.create_async(
        db,
        statement_id=stmt.id,
        description="Grab taxi",
        suggested_category="Shopping",
    )
    await db.commit()

    correction = await record_correction(
        db,
        user_id=test_user.id,
        transaction_id=txn.id,
        corrected_category="Transport",
    )
    await db.commit()

    assert correction.original_category == "Shopping"
    assert correction.corrected_category == "Transport"
    assert correction.transaction_description == "Grab taxi"
    assert correction.user_id == test_user.id


@pytest.mark.asyncio
async def test_record_correction_handles_null_original(db, test_user):
    """Original category can be None when AI didn't suggest anything."""
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)
    txn = await BankStatementTransactionFactory.create_async(
        db,
        statement_id=stmt.id,
        description="Unknown merchant",
        suggested_category=None,
    )
    await db.commit()

    correction = await record_correction(
        db,
        user_id=test_user.id,
        transaction_id=txn.id,
        corrected_category="Entertainment",
    )
    await db.commit()

    assert correction.original_category is None
    assert correction.corrected_category == "Entertainment"


@pytest.mark.asyncio
async def test_record_correction_not_found_raises(db, test_user):
    """Recording correction for non-existent transaction raises ValueError."""
    with pytest.raises(ValueError, match="not found"):
        await record_correction(
            db,
            user_id=test_user.id,
            transaction_id=uuid4(),
            corrected_category="Transport",
        )


@pytest.mark.asyncio
async def test_get_correction_stats_empty(db, test_user):
    """Stats return zero totals when no corrections exist."""
    stats = await get_correction_stats(db, user_id=test_user.id)
    assert stats["total_corrections"] == 0
    assert stats["top_corrections"] == []
    assert stats["accuracy_by_category"] == {}


@pytest.mark.asyncio
async def test_get_correction_stats_aggregates(db, test_user):
    """AC18.2.2: Stats aggregates corrections correctly."""
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)

    for i in range(3):
        txn = await BankStatementTransactionFactory.create_async(
            db,
            statement_id=stmt.id,
            description=f"Taxi ride {i}",
            suggested_category="Shopping",
        )
        await db.flush()
        await record_correction(
            db,
            user_id=test_user.id,
            transaction_id=txn.id,
            corrected_category="Transport",
        )
    await db.commit()

    stats = await get_correction_stats(db, user_id=test_user.id)
    assert stats["total_corrections"] == 3
    assert len(stats["top_corrections"]) >= 1
    assert stats["top_corrections"][0]["count"] == 3
    assert stats["top_corrections"][0]["original_category"] == "Shopping"
    assert stats["top_corrections"][0]["corrected_category"] == "Transport"


@pytest.mark.asyncio
async def test_few_shot_examples_returns_corrections(db, test_user):
    """AC18.2.3: Few-shot examples are generated from corrections."""
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)
    txn = await BankStatementTransactionFactory.create_async(
        db,
        statement_id=stmt.id,
        description="Coffee at Starbucks",
        suggested_category="Shopping",
    )
    await db.flush()
    await record_correction(
        db,
        user_id=test_user.id,
        transaction_id=txn.id,
        corrected_category="Food & Dining",
    )
    await db.commit()

    examples = await get_few_shot_examples(db, user_id=test_user.id)
    assert len(examples) == 1
    assert examples[0]["description"] == "Coffee at Starbucks"
    assert examples[0]["original_category"] == "Shopping"
    assert examples[0]["corrected_category"] == "Food & Dining"


@pytest.mark.asyncio
async def test_few_shot_examples_empty_returns_empty(db, test_user):
    """Empty correction log produces empty few-shot examples list."""
    examples = await get_few_shot_examples(db, user_id=test_user.id)
    assert examples == []


@pytest.mark.asyncio
async def test_few_shot_cache_invalidates(db, test_user):
    """AC18.2.4: Cache invalidates after recording a correction."""
    stmt = await BankStatementFactory.create_async(db, user_id=test_user.id)

    # Prime the cache (empty)
    examples = await get_few_shot_examples(db, user_id=test_user.id)
    assert examples == []

    # Record a correction (should invalidate cache)
    txn = await BankStatementTransactionFactory.create_async(
        db,
        statement_id=stmt.id,
        description="Uber ride",
        suggested_category="Other",
    )
    await db.flush()
    await record_correction(
        db,
        user_id=test_user.id,
        transaction_id=txn.id,
        corrected_category="Transport",
    )
    await db.commit()

    # Should return new examples (cache invalidated by record_correction)
    examples = await get_few_shot_examples(db, user_id=test_user.id)
    assert len(examples) == 1


def test_prompt_injection_with_corrections():
    """AC18.2.3: Few-shot examples are injected into extraction prompt."""
    correction_examples = [
        {
            "description": "GRAB CAR",
            "original_category": "Shopping",
            "corrected_category": "Transport",
        },
        {
            "description": "STARBUCKS",
            "original_category": "Other",
            "corrected_category": "Food & Dining",
        },
    ]

    prompt = get_parsing_prompt(correction_examples=correction_examples)
    assert "Learn from these past categorization corrections" in prompt
    assert '"GRAB CAR"' in prompt
    assert '"Transport"' in prompt
    assert '"STARBUCKS"' in prompt
    assert '"Food & Dining"' in prompt


def test_prompt_without_corrections():
    """Standard prompt produced when no corrections exist."""
    prompt = get_parsing_prompt()
    assert "Learn from these past categorization corrections" not in prompt
    assert "suggested_category" in prompt  # Base prompt still has the field

    prompt2 = get_parsing_prompt(correction_examples=[])
    assert "Learn from these past categorization corrections" not in prompt2
