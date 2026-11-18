from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from src.extraction import BankStatementStatus
from src.extraction.extension.correction_loop import (
    CorrectionLoopService,
    CorrectionRecord,
    build_corpus_from_corrections,
    replay_low_confidence_reduction,
)
from src.extraction.orm.correction import CorrectionLog
from tests.factories import AtomicTransactionFactory, StatementSummaryFactory, UploadedDocumentFactory


def _correction(*, description=None, original=None, corrected="Office Supplies"):
    return CorrectionLog(user_id=uuid4(), transaction_id=uuid4(), original_category=original, corrected_category=corrected, transaction_description=description)


def test_AC18_14_1_2_corpus_and_replay_low_confidence_reduction():
    corpus = build_corpus_from_corrections([
        _correction(description="  Starbucks  COFFEE ", original="Travel", corrected="Meals"),
        _correction(description=None, original="Misc", corrected="Software"),
        _correction(description="   ", original="Groceries", corrected="Food"),
        _correction(description="   ", original=None, corrected="Ignored"),
    ])
    assert ([r.key for r in corpus], corpus[0].corrected_category, corpus[0].proposed_category) == (["starbucks coffee", "misc", "groceries"], "Meals", "Travel")

    reduced = replay_low_confidence_reduction(
        [
            CorrectionRecord(key="rent", corrected_category="Housing", proposed_category="Misc"),
            CorrectionRecord(key="salary", corrected_category="Income", proposed_category=None),
            CorrectionRecord(key="rent", corrected_category="Housing", proposed_category="Misc"),
            CorrectionRecord(key="coffee", corrected_category="Meals", proposed_category="Travel"),
        ],
        train_ratio=Decimal("0.5"),
    )
    unchanged = replay_low_confidence_reduction([CorrectionRecord(key=k, corrected_category=k.upper(), proposed_category=None) for k in ("a", "b", "c", "d")], train_ratio=Decimal("0.5"))
    assert (
        reduced.holdout_size, reduced.grounded, reduced.proportion_before, reduced.proportion_after, reduced.reduced,
        unchanged.grounded, unchanged.proportion_after == unchanged.proportion_before, unchanged.reduced,
    ) == (2, 1, Decimal("1"), Decimal("0.5"), True, 0, True, False)


async def test_AC18_14_3_4_service_builds_corpus_and_replays(client, db, test_user):
    empty_resp = await client.get("/statements/correction-loop/replay")
    assert (empty_resp.status_code, empty_resp.json()["holdout_size"], empty_resp.json()["reduced"], empty_resp.json()["low_confidence_proportion"]) == (200, 0, False, "0")
    document = await UploadedDocumentFactory.create_async(db, user_id=test_user.id)
    txn = await AtomicTransactionFactory.create_async(db, test_user.id, source_doc_id=document.id, description="Netflix")
    db.add(CorrectionLog(user_id=test_user.id, transaction_id=txn.id, original_category="Utilities", corrected_category="Entertainment", transaction_description="Netflix"))
    await db.commit()
    corpus = await CorrectionLoopService().build_corpus(db, test_user.id)
    assert (len(corpus), corpus[0].key, corpus[0].corrected_category) == (1, "netflix", "Entertainment")

    for desc in ("Spotify", "Netflix", "Spotify"):
        t = await AtomicTransactionFactory.create_async(db, test_user.id, source_doc_id=document.id, description=desc)
        db.add(CorrectionLog(user_id=test_user.id, transaction_id=t.id, original_category="Utilities", corrected_category="Entertainment", transaction_description=desc))
    for status, conf, bal in [(BankStatementStatus.PARSED, 90, True), (BankStatementStatus.PARSED, 75, True), (BankStatementStatus.PARSED, 45, False), (BankStatementStatus.RETIRED, 10, False)]:
        await StatementSummaryFactory.create_async(db, test_user.id, status=status, confidence_score=conf, balance_validated=bal)
    await db.commit()
    result = await CorrectionLoopService().replay(db, test_user.id, train_ratio=Decimal("0.5"))
    resp = await client.get("/statements/correction-loop/replay")
    assert (
        result.holdout_size, result.grounded, result.reduced, result.proportion_after < result.proportion_before,
        result.high_confidence_count, result.medium_confidence_count, result.low_confidence_count, result.low_confidence_proportion,
        resp.status_code, resp.json()["holdout_size"], resp.json()["reduced"],
    ) == (2, 2, True, True, 1, 1, 1, Decimal("0.33333"), 200, 2, True)
