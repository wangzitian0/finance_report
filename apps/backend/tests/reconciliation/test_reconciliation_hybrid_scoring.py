"""EPIC-018 Phase 3: hybrid + feature-flagged AI-reconciliation scoring.

AC-reconciliation.1803.1 / AC-reconciliation.1803.2 (formerly AC18.3.2/
AC18.3.3), exercised end-to-end through ``score_single``.

Kept in a separate file from ``test_ai_reconciliation.py`` (which exercises
the lower-level AI-provider streaming call directly, now owned by the
``llm`` package) and mocks at the ``ai_semantic_score`` call boundary
instead: this package (``reconciliation``) is declared ``CODE-ONLY``, and
``common/meta/extension/authority_classifier.py`` classifies a test FILE as
an LLM test — file-level, not per-function — if it contains any of a
handful of literal provider-call markers anywhere in the file (see
``LLM_TEST_MARKERS`` in that module). A file mixing these two deterministic
gating/formula tests with a literal low-level provider-call mock would
misclassify this package's detected authority band and trip
``tools/check_authority_reconcile.py``'s CODE-ONLY-vs-detected-LLM check,
even though what's actually under test here (the 60-84 band gate, the
0.7/0.3 blend, the feature flag) is ordinary deterministic code — the AI
scorer is a black box these tests treat as an opaque, mocked dependency.
"""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import Direction, JournalEntry, JournalLine
from src.reconciliation import DEFAULT_CONFIG, score_single, weighted_total


def _hybrid_band_txn_and_entry() -> tuple[AtomicTransaction, JournalEntry]:
    """Build a transaction/entry pair whose pre-AI weighted total lands in [60, 84].

    With ``DEFAULT_CONFIG`` weights (amount=0.40, date=0.25, description=0.20,
    business=0.10, history=0.05) and ``history_score_override=0.0``:
    - amount: exact match (100.00 == 100.00) -> ``score_amount`` = 100.0
    - date: same day -> ``score_date`` = 100.0
    - description: entry memo is empty -> ``score_description`` short-circuits to 0.0
    - business: no account on the journal line -> ``score_business_logic`` falls
      through to its neutral 40.0 branch for an "IN" transaction
    - history: overridden to 0.0 (skips the DB-backed ``score_pattern`` call)

    total = 100*0.40 + 100*0.25 + 0*0.20 + 40*0.10 + 0*0.05 = 40+25+0+4+0 = 69
    """
    txn = AtomicTransaction(
        description="ZQXW MERCHANT PURCHASE",
        amount=Decimal("100.00"),
        txn_date=date(2024, 1, 1),
        direction="IN",
        currency="SGD",
    )
    entry = JournalEntry(
        memo="",
        entry_date=date(2024, 1, 1),
        lines=[JournalLine(amount=Decimal("100.00"), direction=Direction.DEBIT)],
    )
    return txn, entry


async def test_score_single_applies_hybrid_ai_scoring(db) -> None:
    """AC-reconciliation.1803.1: with ENABLE_AI_RECONCILIATION on and a pre-AI
    weighted total in the 60-84 review band, score_single blends
    70% algorithmic + 30% AI semantic score (also proves EPIC-018 AC18.3.2).
    """
    txn, entry = _hybrid_band_txn_and_entry()
    config = replace(DEFAULT_CONFIG, enable_ai_reconciliation=True)

    pre_ai_total = weighted_total(
        {"amount": 100.0, "date": 100.0, "description": 0.0, "business": 40.0, "history": 0.0},
        DEFAULT_CONFIG,
    )
    assert pre_ai_total == 69
    assert 60 <= pre_ai_total <= 84, "fixture must land in the hybrid review band"

    mock_ai_score = AsyncMock(return_value=90)

    with patch("src.reconciliation.extension.matching.ai_semantic_score", mock_ai_score):
        candidate = await score_single(db, txn, [entry], config, uuid4(), history_score=0.0)

    expected_score = int(round(Decimal("0.7") * pre_ai_total + Decimal("0.3") * 90, 0))
    assert expected_score == 75
    assert candidate.score == expected_score
    assert candidate.breakdown["hybrid_applied"] == 1.0
    assert candidate.breakdown["ai_semantic"] == 90.0
    mock_ai_score.assert_awaited_once()


async def test_score_single_flag_off_skips_ai_scoring(db) -> None:
    """AC-reconciliation.1803.2: with ENABLE_AI_RECONCILIATION off, the hybrid
    branch never runs — even when the pre-AI weighted total is in the 60-84
    band that would otherwise trigger it — and the AI scorer is never called
    (also proves EPIC-018 AC18.3.3).
    """
    txn, entry = _hybrid_band_txn_and_entry()

    mock_ai_score = AsyncMock(return_value=90)

    with patch("src.reconciliation.extension.matching.ai_semantic_score", mock_ai_score):
        candidate = await score_single(db, txn, [entry], DEFAULT_CONFIG, uuid4(), history_score=0.0)
        mock_ai_score.assert_not_called()

    assert candidate.score == 69
    assert "hybrid_applied" not in candidate.breakdown
    assert "ai_semantic" not in candidate.breakdown


async def test_AC_reconciliation_1803_3_execute_matching_uses_per_user_ai_reconciliation_override(
    db, test_user, monkeypatch
) -> None:
    """AC-reconciliation.1803.3: execute_matching honors the per-user enable_ai_reconciliation override in both directions (#2417)."""
    from dataclasses import replace

    from src.audit import Money
    from src.config import settings
    from src.extraction.orm.layer2 import TransactionDirection
    from src.ledger import Account, AccountType, Entry, post_entry
    from src.reconciliation import execute_matching

    bank = Account(user_id=test_user.id, name="Checking", type=AccountType.ASSET, currency="SGD")
    expense = Account(user_id=test_user.id, name="General Expense", type=AccountType.EXPENSE, currency="SGD")
    db.add_all([bank, expense])
    await db.flush()

    txn_1 = AtomicTransaction(
        user_id=test_user.id,
        txn_date=date(2024, 6, 10),
        description="ZQXW MERCHANT PURCHASE",
        amount=Decimal("100.00"),
        direction=TransactionDirection.IN,
        currency="SGD",
        dedup_hash="hybrid-override-txn-1",
        source_documents=[{"doc_id": str(uuid4())}],
    )
    db.add(txn_1)
    await db.flush()

    await post_entry(
        db,
        user_id=test_user.id,
        entry_date=date(2024, 6, 10),
        memo="Unrelated memo",
        entry=Entry.transfer(
            debit=bank.id,
            credit=expense.id,
            money=Money(Decimal("100.00"), "SGD"),
        ),
        base_currency="SGD",
        operation="hybrid-override-fixture-1",
    )
    await db.commit()

    # Direction 1: base config OFF, user override ON -> AI scorer runs on txn_1.
    monkeypatch.setattr(settings, "enable_ai_reconciliation", False)
    test_user.ai_settings = {"enable_ai_reconciliation": True}
    await db.commit()

    mock_ai_on = AsyncMock(return_value=95)
    with (
        patch(
            "src.reconciliation.extension.matching.load_reconciliation_config",
            return_value=replace(DEFAULT_CONFIG, enable_ai_reconciliation=False),
        ),
        patch("src.reconciliation.extension.matching.ai_semantic_score", mock_ai_on),
        patch("src.reconciliation.extension.phases.transfer_detection.detect_transfer_pattern", return_value=False),
        patch("src.reconciliation.extension.matching.score_pattern", new_callable=AsyncMock, return_value=0.0),
    ):
        matches_on = await execute_matching(db, user_id=test_user.id, currency="SGD")

    assert len(matches_on) == 1
    assert matches_on[0].atomic_txn_id == txn_1.id
    assert matches_on[0].match_score == 78
    assert matches_on[0].score_breakdown.get("hybrid_applied") == 1.0
    assert matches_on[0].score_breakdown.get("ai_semantic") == 95.0
    mock_ai_on.assert_awaited_once()

    # Direction 2: seed a fresh pending transaction; base config ON, user override OFF -> AI scorer is skipped.
    txn_2 = AtomicTransaction(
        user_id=test_user.id,
        txn_date=date(2024, 6, 20),
        description="ZQXW MERCHANT PURCHASE",
        amount=Decimal("200.00"),
        direction=TransactionDirection.IN,
        currency="SGD",
        dedup_hash="hybrid-override-txn-2",
        source_documents=[{"doc_id": str(uuid4())}],
    )
    db.add(txn_2)
    await db.flush()

    await post_entry(
        db,
        user_id=test_user.id,
        entry_date=date(2024, 6, 20),
        memo="Unrelated memo",
        entry=Entry.transfer(
            debit=bank.id,
            credit=expense.id,
            money=Money(Decimal("200.00"), "SGD"),
        ),
        base_currency="SGD",
        operation="hybrid-override-fixture-2",
    )
    monkeypatch.setattr(settings, "enable_ai_reconciliation", True)
    test_user.ai_settings = {"enable_ai_reconciliation": False}
    await db.commit()

    mock_ai_off = AsyncMock(return_value=95)
    with (
        patch(
            "src.reconciliation.extension.matching.load_reconciliation_config",
            return_value=replace(DEFAULT_CONFIG, enable_ai_reconciliation=True),
        ),
        patch("src.reconciliation.extension.matching.ai_semantic_score", mock_ai_off),
        patch("src.reconciliation.extension.phases.transfer_detection.detect_transfer_pattern", return_value=False),
        patch("src.reconciliation.extension.matching.score_pattern", new_callable=AsyncMock, return_value=0.0),
    ):
        matches_off = await execute_matching(db, user_id=test_user.id, currency="SGD")

    assert len(matches_off) == 1
    assert matches_off[0].atomic_txn_id == txn_2.id
    assert matches_off[0].match_score == 71
    assert "hybrid_applied" not in matches_off[0].score_breakdown
    assert "ai_semantic" not in matches_off[0].score_breakdown
    mock_ai_off.assert_not_called()
