from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import BankStatementStatus, TransactionDirection
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account, AccountType, create_transfer_in_entry, create_transfer_out_entry
from src.reconciliation import CheckResolutionAction, ConsistencyCheckNotFoundError, InvalidCheckActionError, paired_transfer_entry_ids
from src.reconciliation.extension.consistency_checks import (
    detect_anomalies_batch,
    detect_duplicates,
    detect_transfer_pairs,
    has_unresolved_checks,
    list_checks,
    resolve_check,
    run_all_consistency_checks,
)
from src.reconciliation.orm.consistency_check import CheckStatus, CheckType, ConsistencyCheck
from src.reconciliation.orm.reconciliation import (
    DispositionKind,
    ReconciliationMatch,
    ReconciliationMatchJournalEntry,
    ReconciliationStatus,
    ReconciliationTransferPair,
    TransferPairDecision,
)
from tests.factories import AccountFactory, AtomicTransactionFactory, StatementSummaryFactory, UploadedDocumentFactory


async def _stmt(db, uid, tag: str) -> StatementSummary:
    acc = await AccountFactory.create_async(db, user_id=uid, currency="USD")
    doc = await UploadedDocumentFactory.create_async(db, user_id=uid, file_hash=tag)
    return await StatementSummaryFactory.create_async(db, user_id=uid, uploaded_document_id=doc.id, file_hash=tag, account_id=acc.id, currency="USD", period_start=date(2024, 1, 1), period_end=date(2024, 1, 31), status=BankStatementStatus.APPROVED)


async def _txn(db, uid, amt: str, direction: TransactionDirection, d: date, desc: str, *, doc_id=None, ccy: str = "USD"):
    return await AtomicTransactionFactory.create_async(db, user_id=uid, source_doc_id=doc_id, txn_date=d, description=desc, amount=Decimal(amt), direction=direction, currency=ccy)


async def _check(db, uid, *, check_type=CheckType.DUPLICATE, status=CheckStatus.PENDING, txns=None, details=None, severity: str = "medium", run_id: str | None = None) -> ConsistencyCheck:
    c = ConsistencyCheck(id=uuid4(), user_id=uid, run_id=run_id, check_type=check_type, status=status, related_txn_ids=txns or ["txn1"], details=details or {}, severity=severity)
    db.add(c)
    await db.flush()
    return c


async def test_duplicates_transfers_and_anomalies(db, test_user):
    uid = test_user.id
    stmt = await _stmt(db, uid, f"main_{uuid4().hex}")
    assert await run_all_consistency_checks(db, uid, stmt.id) == []

    for _ in range(2):
        await _txn(db, uid, "5.50", TransactionDirection.OUT, date(2024, 1, 15), "Starbucks")
    dups = await detect_duplicates(db, uid, stmt.id)
    assert len(dups) == 1 and dups[0].check_type == CheckType.DUPLICATE and len(dups[0].related_txn_ids) == 2
    assert await detect_duplicates(db, uid, stmt.id) == [] and await detect_duplicates(db, uid) == []

    anchor, other = await _stmt(db, uid, "hash_anchor"), await _stmt(db, uid, "hash_other")
    for d in (date(2024, 1, 10), date(2024, 1, 15)):
        await _txn(db, uid, "25.00", TransactionDirection.OUT, d, "Grocery", doc_id=anchor.uploaded_document_id)
    assert await detect_duplicates(db, uid, anchor.id) == []
    for _ in range(2):
        await _txn(db, uid, "20.00", TransactionDirection.OUT, date(2024, 1, 8), "Outside", doc_id=other.uploaded_document_id)
    assert len(await detect_duplicates(db, uid)) == 1

    t_out = await _txn(db, uid, "100.00", TransactionDirection.OUT, date(2024, 1, 15), "Transfer to Bank B")
    t_in = await _txn(db, uid, "100.00", TransactionDirection.IN, date(2024, 1, 16), "Transfer from Bank A")
    xp = await detect_transfer_pairs(db, uid)
    assert len(xp) == 1 and xp[0].check_type == CheckType.TRANSFER_PAIR and xp[0].details.get("currency") == "USD" and set(xp[0].related_txn_ids) == {str(t_out.id), str(t_in.id)}
    assert await detect_transfer_pairs(db, uid, t_out.id) == []

    await _txn(db, uid, "100.00", TransactionDirection.OUT, date(2024, 1, 15), "X USD", ccy="USD")
    await _txn(db, uid, "100.00", TransactionDirection.IN, date(2024, 1, 16), "X EUR", ccy="EUR")
    assert await detect_transfer_pairs(db, uid) == []
    for d in (date(2024, 3, 1), date(2024, 3, 2)):
        await _txn(db, uid, "100.00", TransactionDirection.OUT, d, "Transfer out")
        await _txn(db, uid, "100.00", TransactionDirection.IN, d, "Transfer in")
    assert len(await detect_transfer_pairs(db, uid)) == 2

    for i in range(10):
        await _txn(db, uid, "10.00", TransactionDirection.OUT, date(2024, 1, i + 1), "Regular")
    await _txn(db, uid, "1000.00", TransactionDirection.OUT, date(2024, 1, 15), "Giant Buy")
    assert CheckType.ANOMALY in [c.check_type for c in await detect_anomalies_batch(db, uid, stmt.id)]

    rec_txn = await _txn(db, uid, "33.00", TransactionDirection.OUT, date(2024, 4, 1), "Recurring Charge")
    await _check(db, uid, check_type=CheckType.ANOMALY, txns=[str(rec_txn.id)], details={"anomaly_type": "REPEATED_DESCRIPTION"})
    with patch("src.reconciliation.extension.consistency_checks.detect_anomalies", new=AsyncMock(return_value=[SimpleNamespace(anomaly_type="REPEATED_DESCRIPTION", message="x", severity="low")])):
        assert await detect_anomalies_batch(db, uid, stmt.id) == []

    run_checks = await run_all_consistency_checks(db, uid, stmt.id, run_id="run-tagged")
    assert all(c.run_id == "run-tagged" for c in run_checks)


@pytest.mark.parametrize(("action", "expected_status", "note"), [("approve", CheckStatus.APPROVED, "All good"), ("flag", CheckStatus.FLAGGED, "Suspicious"), ("reject", CheckStatus.REJECTED, None)])
async def test_resolve_check_actions(db, test_user, action, expected_status, note):
    uid = test_user.id
    chk = await _check(db, uid)
    assert await has_unresolved_checks(db, uid) is True
    resolved = await resolve_check(db, chk.id, action, uid, note)
    assert (resolved.status, resolved.resolution_note) == (expected_status, note) and resolved.resolved_at is not None and await has_unresolved_checks(db, uid) is False


async def test_resolve_errors_and_list_filters(db, test_user):
    uid = test_user.id
    assert (await list_checks(db, uid, status=CheckStatus.PENDING))[0] == []
    await _check(db, uid, check_type=CheckType.ANOMALY, severity="low", txns=["low"])
    assert await has_unresolved_checks(db, uid) is False
    c_dup = await _check(db, uid, severity="high", run_id="run-1", txns=["1"])
    assert await has_unresolved_checks(db, uid, run_id="run-1") is True and await has_unresolved_checks(db, uid, run_id="run-beta") is False
    c_anom = await _check(db, uid, check_type=CheckType.ANOMALY, severity="medium", run_id=None, txns=["2"])
    assert await has_unresolved_checks(db, uid, run_id="run-active") is True
    await _check(db, uid, check_type=CheckType.ANOMALY, status=CheckStatus.APPROVED, run_id="run-2", txns=["3"])

    for bad_id, act, actor, exc, msg in ((c_dup.id, "bad", uid, InvalidCheckActionError, "Invalid action"), (uuid4(), "approve", uid, ConsistencyCheckNotFoundError, "Check not found"), (c_dup.id, "approve", uuid4(), ConsistencyCheckNotFoundError, "Check not found")):
        with pytest.raises(exc, match=msg):
            await resolve_check(db, bad_id, act, actor)

    assert {c.id for c in (await list_checks(db, uid, status=CheckStatus.PENDING))[0]} == {c_dup.id, c_anom.id}
    assert [c.id for c in (await list_checks(db, uid, status=CheckStatus.PENDING, check_type=CheckType.DUPLICATE))[0]] == [c_dup.id]
    assert [c.id for c in (await list_checks(db, uid, status=CheckStatus.PENDING, severity="high"))[0]] == [c_dup.id]
    by_run, total = await list_checks(db, uid, status=CheckStatus.PENDING, run_id="run-1")
    assert total == 2 and {c.id for c in by_run} == {c_dup.id, c_anom.id}


@pytest.mark.parametrize(("limit", "expected_status"), [(10000, 422), (0, 422), (500, 200)])
async def test_AC_consistency_checks_10_list_endpoint_limit_bounds(client, limit: int, expected_status: int):
    resp = await client.get("/reconciliation/consistency-checks", params={"limit": limit})
    assert resp.status_code == expected_status and (expected_status != 200 or {"items", "total"} <= set(resp.json()))


@pytest.mark.parametrize(
    ("action", "desc_out", "desc_in", "expected_confidence"),
    [
        (CheckResolutionAction.APPROVE, "Transfer to B", "Transfer from A", 75),
        (CheckResolutionAction.APPROVE, "TRANSFER TO SAVINGS ACCOUNT", "TRANSFER FROM CURRENT ACCOUNT", 74),
        (CheckResolutionAction.APPROVE, "IBG TRANSFER TO B REF TRF20260310001", "IBG TRANSFER FROM A REF TRF20260310001", 80),
        (CheckResolutionAction.REJECT, "Transfer to B", "Transfer from A", None),
    ],
)
async def test_issue2388_review_band_transfer_pair_decision(client, db: AsyncSession, test_user, action, desc_out: str, desc_in: str, expected_confidence: int | None) -> None:
    uid = test_user.id
    bank_a = Account(user_id=uid, name=f"A-{uuid4().hex[:6]}", code=f"A{uuid4().hex[:4]}", type=AccountType.ASSET, currency="SGD")
    bank_b = Account(user_id=uid, name=f"B-{uuid4().hex[:6]}", code=f"B{uuid4().hex[:4]}", type=AccountType.ASSET, currency="SGD")
    db.add_all([bank_a, bank_b])
    await db.flush()
    out_entry = await create_transfer_out_entry(db, user_id=uid, source_account_id=bank_a.id, amount=Decimal("500.00"), txn_date=date(2026, 3, 10), description=desc_out, currency="SGD")
    in_entry = await create_transfer_in_entry(db, user_id=uid, dest_account_id=bank_b.id, amount=Decimal("500.00"), txn_date=date(2026, 3, 11), description=desc_in, currency="SGD")
    out_txn = await _txn(db, uid, "500.00", TransactionDirection.OUT, date(2026, 3, 10), desc_out, ccy="SGD")
    in_txn = await _txn(db, uid, "500.00", TransactionDirection.IN, date(2026, 3, 11), desc_in, ccy="SGD")
    out_m = ReconciliationMatch(atomic_txn_id=out_txn.id, journal_entry_ids=[str(out_entry.id)], match_score=90, score_breakdown={}, status=ReconciliationStatus.AUTO_ACCEPTED, disposition_kind=DispositionKind.TRANSFER_LEG)
    in_m = ReconciliationMatch(atomic_txn_id=in_txn.id, journal_entry_ids=[str(in_entry.id)], match_score=90, score_breakdown={}, status=ReconciliationStatus.AUTO_ACCEPTED, disposition_kind=DispositionKind.TRANSFER_LEG)
    db.add_all([out_m, in_m])
    await db.flush()
    db.add_all([ReconciliationMatchJournalEntry(match_id=out_m.id, journal_entry_id=out_entry.id), ReconciliationMatchJournalEntry(match_id=in_m.id, journal_entry_id=in_entry.id)])
    chk = await _check(db, uid, check_type=CheckType.TRANSFER_PAIR, txns=sorted([str(out_txn.id), str(in_txn.id)]))
    await db.commit()

    assert await paired_transfer_entry_ids(db, user_id=uid) == set()
    resolved = await resolve_check(db, chk.id, action, uid)
    await db.commit()
    resp = await client.get("/reconciliation/transfers/pending")
    if action is CheckResolutionAction.APPROVE:
        pair = (await db.execute(select(ReconciliationTransferPair).where(ReconciliationTransferPair.confidence == expected_confidence))).scalars().first()
        assert resolved.status == CheckStatus.APPROVED and pair.decision == TransferPairDecision.REVIEWER_PAIRED
        assert await paired_transfer_entry_ids(db, user_id=uid) == {out_entry.id, in_entry.id} and await detect_transfer_pairs(db, uid) == []
        assert resp.status_code == 200 and (resp.json()["total"], resp.json()["items"]) == (0, [])
    else:
        assert resolved.status == CheckStatus.REJECTED and await paired_transfer_entry_ids(db, user_id=uid) == set() and resp.status_code == 200 and resp.json()["total"] == 2


async def test_AC_reconciliation_2548_5_consistency_checks_guard_same_account_refund_and_adjacent_day_spend(db: AsyncSession, test_user) -> None:
    uid = test_user.id
    stmt_a, stmt_b = await _stmt(db, uid, f"a_{uuid4().hex}"), await _stmt(db, uid, f"b_{uuid4().hex}")
    await _txn(db, uid, "88.00", TransactionDirection.OUT, date(2026, 6, 1), "Merchant purchase", doc_id=stmt_a.uploaded_document_id)
    await _txn(db, uid, "88.00", TransactionDirection.IN, date(2026, 6, 2), "Merchant refund", doc_id=stmt_a.uploaded_document_id)
    assert await detect_transfer_pairs(db, uid, stmt_a.id) == []
    for d in (date(2026, 6, 10), date(2026, 6, 11)):
        await _txn(db, uid, "6.50", TransactionDirection.OUT, d, "MRT Transit", doc_id=stmt_a.uploaded_document_id)
    for doc_id in (stmt_a.uploaded_document_id, stmt_b.uploaded_document_id):
        await _txn(db, uid, "12.00", TransactionDirection.OUT, date(2026, 6, 12), "Cafe Lunch", doc_id=doc_id)
    assert await detect_duplicates(db, uid, stmt_a.id) == []
