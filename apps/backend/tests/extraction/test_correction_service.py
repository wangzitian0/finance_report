from __future__ import annotations

from uuid import uuid4

import pytest

from src.extraction import SuggestionCorrectionError
from src.extraction.extension import correction_service
from src.extraction.extension.correction_service import get_few_shot_examples, record_correction
from tests.factories import AccountFactory, AtomicTransactionFactory, UserFactory


async def test_record_correction_stores_and_guards(db, test_user):
    txn1 = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="Grab taxi")
    txn2 = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="Unknown merchant")
    other_user = await UserFactory.create_async(db)
    other_account = await AccountFactory.create_async(db, user_id=other_user.id, name="Other User Account")
    await db.commit()

    c1 = await record_correction(db, user_id=test_user.id, transaction_id=txn1.id, corrected_category="Transport")
    c2 = await record_correction(db, user_id=test_user.id, transaction_id=txn2.id, corrected_category="Entertainment")
    await db.commit()
    assert (
        c1.original_category,
        c1.corrected_category,
        c1.transaction_description,
        c1.user_id,
        c2.original_category,
        c2.corrected_category,
    ) == (None, "Transport", "Grab taxi", test_user.id, None, "Entertainment")

    with pytest.raises(ValueError, match="not found"):
        await record_correction(db, user_id=test_user.id, transaction_id=uuid4(), corrected_category="Transport")
    with pytest.raises(ValueError, match="Account .* not found"):
        await record_correction(
            db,
            user_id=test_user.id,
            transaction_id=txn1.id,
            corrected_category="Transport",
            corrected_account_id=other_account.id,
        )
    with pytest.raises(SuggestionCorrectionError):
        await record_correction(db, user_id=test_user.id, transaction_id=txn1.id, corrected_category="Food & Dining")


async def test_few_shot_examples_reads_live_db_without_process_cache(db, test_user):
    assert not hasattr(correction_service, "_correction_cache")
    assert not hasattr(correction_service, "invalidate_correction_cache")
    assert not hasattr(correction_service, "clear_all_correction_cache")
    assert await get_few_shot_examples(db, user_id=test_user.id) == []
    txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="Coffee at Starbucks")
    await db.flush()
    await record_correction(db, user_id=test_user.id, transaction_id=txn.id, corrected_category="Dining")
    await db.commit()
    examples = await get_few_shot_examples(db, user_id=test_user.id)
    assert len(examples) == 1 and (
        examples[0]["description"],
        examples[0]["original_category"],
        examples[0]["corrected_category"],
    ) == ("Coffee at Starbucks", "Other", "Dining")

    categories = [
        "DINING",
        "GROCERIES",
        "TRANSPORT",
        "HOUSING",
        "UTILITIES",
        "SHOPPING",
        "HEALTHCARE",
        "ENTERTAINMENT",
        "TRAVEL",
        "EDUCATION",
        "INSURANCE",
        "FEES",
    ]
    for i in range(12):
        t = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description=f"Txn {i}")
        await record_correction(
            db, user_id=test_user.id, transaction_id=t.id, corrected_category=categories[i % len(categories)]
        )
    await db.commit()
    latest = await get_few_shot_examples(db, user_id=test_user.id)
    assert len(latest) == 10 and await get_few_shot_examples(db, user_id=test_user.id) == latest
