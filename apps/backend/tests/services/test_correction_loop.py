"""Correction feedback loop: corrections measurably lower the low-confidence proportion (EPIC-018 AC18.14, #931).

B3 (#919) is a thermometer; this is the furnace. Each human correction that
overrode an AI proposal is labeled signal; replayed as priors it grounds
recurring patterns so future instances are no longer low-confidence — measurably
driving the north-star proportion down.
"""

from decimal import Decimal
from uuid import uuid4

import pytest

from src.extraction.extension.correction_loop import (
    CorrectionLoopService,
    CorrectionRecord,
    build_corpus_from_corrections,
    replay_low_confidence_reduction,
)
from src.extraction.orm.correction import CorrectionLog


def _correction(*, description=None, original=None, corrected="Office Supplies") -> CorrectionLog:
    # In-memory only (never persisted) — a fixture for the pure derivation logic.
    return CorrectionLog(
        user_id=uuid4(),
        transaction_id=uuid4(),
        original_category=original,
        corrected_category=corrected,
        transaction_description=description,
    )


def test_AC18_14_1_corpus_is_derived_from_corrections_keyed_by_pattern():
    """AC-extraction.1814.1: AC18.14.1: the corpus is a provenance projection of CorrectionLog, keyed by the transaction pattern."""
    corrections = [
        _correction(description="  Starbucks  COFFEE ", original="Travel", corrected="Meals"),
        _correction(description=None, original="Misc", corrected="Software"),  # falls back to original_category key
        _correction(
            description="   ", original="Groceries", corrected="Food"
        ),  # whitespace desc -> falls back, not dropped
        _correction(description="   ", original=None, corrected="Ignored"),  # no usable pattern -> skipped
    ]

    corpus = build_corpus_from_corrections(corrections)

    assert [record.key for record in corpus] == ["starbucks coffee", "misc", "groceries"]
    assert corpus[0].corrected_category == "Meals"
    assert corpus[0].proposed_category == "Travel"


def test_AC18_14_2_replay_lowers_low_confidence_proportion_when_patterns_recur():
    """AC-extraction.1814.2: AC18.14.2: replaying the corpus as priors strictly lowers the held-out low-confidence proportion when patterns recur."""
    corpus = [
        CorrectionRecord(key="rent", corrected_category="Housing", proposed_category="Misc"),
        CorrectionRecord(key="salary", corrected_category="Income", proposed_category=None),
        CorrectionRecord(key="rent", corrected_category="Housing", proposed_category="Misc"),  # recurs in holdout
        CorrectionRecord(key="coffee", corrected_category="Meals", proposed_category="Travel"),  # novel
    ]

    result = replay_low_confidence_reduction(corpus, train_ratio=Decimal("0.5"))

    # Holdout = ["rent", "coffee"]; "rent" was learned from the train split -> grounded.
    assert result.holdout_size == 2
    assert result.grounded == 1
    assert result.proportion_before == Decimal("1")
    assert result.proportion_after == Decimal("0.5")
    assert result.reduced is True


def test_AC18_14_2_replay_does_not_invent_reduction_without_recurrence():
    """AC18.14.2: with no recurring patterns the corpus grounds nothing — no invented improvement."""
    corpus = [
        CorrectionRecord(key="a", corrected_category="A", proposed_category=None),
        CorrectionRecord(key="b", corrected_category="B", proposed_category=None),
        CorrectionRecord(key="c", corrected_category="C", proposed_category=None),
        CorrectionRecord(key="d", corrected_category="D", proposed_category=None),
    ]

    result = replay_low_confidence_reduction(corpus, train_ratio=Decimal("0.5"))

    assert result.grounded == 0
    assert result.proportion_after == result.proportion_before
    assert result.reduced is False


@pytest.mark.asyncio
async def test_AC18_14_3_service_builds_corpus_from_persisted_corrections(db, test_user):
    """AC-extraction.1814.3: AC18.14.3: the service derives the corpus from the persisted CorrectionLog store (no sidecar)."""
    from tests.factories import AtomicTransactionFactory, UploadedDocumentFactory

    document = await UploadedDocumentFactory.create_async(db, user_id=test_user.id)
    txn = await AtomicTransactionFactory.create_async(
        db, test_user.id, source_doc_id=document.id, description="Netflix"
    )
    db.add(
        CorrectionLog(
            user_id=test_user.id,
            transaction_id=txn.id,
            original_category="Utilities",
            corrected_category="Entertainment",
            transaction_description="Netflix",
        )
    )
    await db.commit()

    corpus = await CorrectionLoopService().build_corpus(db, test_user.id)

    assert len(corpus) == 1
    assert corpus[0].key == "netflix"
    assert corpus[0].corrected_category == "Entertainment"


@pytest.mark.asyncio
async def test_AC18_14_4_service_replay_measures_held_out_reduction(db, test_user):
    """AC-extraction.1814.4: AC18.14.4: the service replays the live corpus, surfacing the held-out reduction.

    This is the loop being *observed* end-to-end against persisted data: corrections
    whose pattern recurs ground the held-out split, so the measured low-confidence
    proportion strictly drops — the auditable evidence the furnace works.
    """
    from tests.factories import AtomicTransactionFactory, UploadedDocumentFactory

    document = await UploadedDocumentFactory.create_async(db, user_id=test_user.id)
    # Two recurring patterns (Netflix, Spotify) interleaved so a 0.5 split grounds
    # every held-out item from the train split.
    for description, original, corrected in [
        ("Netflix", "Utilities", "Entertainment"),
        ("Spotify", "Utilities", "Entertainment"),
        ("Netflix", "Utilities", "Entertainment"),
        ("Spotify", "Utilities", "Entertainment"),
    ]:
        txn = await AtomicTransactionFactory.create_async(
            db, test_user.id, source_doc_id=document.id, description=description
        )
        db.add(
            CorrectionLog(
                user_id=test_user.id,
                transaction_id=txn.id,
                original_category=original,
                corrected_category=corrected,
                transaction_description=description,
            )
        )
    await db.commit()

    result = await CorrectionLoopService().replay(db, test_user.id, train_ratio=Decimal("0.5"))

    assert result.holdout_size == 2
    assert result.grounded == 2
    assert result.reduced is True
    assert result.proportion_after < result.proportion_before
