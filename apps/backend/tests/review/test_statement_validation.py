from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.extraction import BankStatementStatus, Stage1Status, TransactionDirection
from src.extraction.extension import statement_posting as stmt_posting_mod
from src.extraction.extension import statement_validation as stmt_val_mod
from src.extraction.extension.statement_posting import auto_create_posted_entries_for_statement
from src.extraction.extension.statement_validation import (
    BALANCE_TOLERANCE,
    _has_unresolved_statement_conflicts,
    _raise_if_balance_chain_invalid,
    approve_statement_with_transactions,
    pending_stage1_review_filter,
    reject_statement,
    resolve_statement_transactions,
    validate_balance_chain,
)
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.statement_summary import StatementSummary
from tests.factories import AccountFactory, AtomicTransactionFactory, StatementSummaryFactory, UploadedDocumentFactory
from tests.statement_ingestion import posting_dependencies


@pytest.mark.parametrize(("balances", "expected"), [((Decimal("5000.00"), Decimal("3966.50")), False), ((Decimal("5000.00"), Decimal("5000.00")), True), ((None, None), True)])
def test_duplicate_guard_balance_after(balances, expected: bool) -> None:
    txns = [AtomicTransaction(id=uuid4(), user_id=uuid4(), txn_date=date(2025, 6, 25), amount=Decimal("1033.50"), direction=TransactionDirection.OUT, description="Buy NIO", currency="USD", dedup_hash=uuid4().hex + uuid4().hex, source_documents=[], balance_after=b) for b in balances]
    assert _has_unresolved_statement_conflicts(txns) is expected


def test_AC18_13_5_balance_chain_decision_routes_through_promotion_gate() -> None:
    _raise_if_balance_chain_invalid({"opening_match": True, "closing_match": True, "opening_delta": "0", "closing_delta": "0"})
    for open_m, close_m, od, cd, msg in ((False, True, "0.5", "0", "Opening balance mismatch"), (True, False, "0", "0.5", "Balance mismatch")):
        with pytest.raises(ValueError, match=msg):
            _raise_if_balance_chain_invalid({"opening_match": open_m, "closing_match": close_m, "opening_delta": od, "closing_delta": cd})


async def _stmt(db, uid, *, file_hash: str, account_id=None, **kw) -> StatementSummary:
    if account_id is None:
        existing = (await db.execute(select(AccountFactory._meta.model.id).where(AccountFactory._meta.model.user_id == uid, AccountFactory._meta.model.name == "Val Default").limit(1))).scalar_one_or_none()
        account_id = existing or (await AccountFactory.create_async(db, user_id=uid, name="Val Default", currency="USD")).id
    doc = await UploadedDocumentFactory.create_async(db, user_id=uid, file_hash=file_hash)
    kw.setdefault("period_start", date(2024, 1, 1))
    kw.setdefault("period_end", date(2024, 1, 31))
    kw.setdefault("status", BankStatementStatus.PARSED)
    return await StatementSummaryFactory.create_async(db, user_id=uid, uploaded_document_id=doc.id, account_id=account_id, file_hash=file_hash, currency="USD", **kw)


async def _txn(db, stmt: StatementSummary, amt: str | Decimal, *, txn_date: date = date(2024, 1, 15)) -> AtomicTransaction:
    return await AtomicTransactionFactory.create_async(db, user_id=stmt.user_id, source_doc_id=stmt.uploaded_document_id, txn_date=txn_date, description="Deposit", amount=Decimal(str(amt)), direction=TransactionDirection.IN, currency="USD")


@pytest.mark.parametrize(
    ("opening", "closing", "manual_opening", "period_start", "txn_amount", "expected_open", "expected_calc", "expected_match"),
    [
        (Decimal("1000.00"), Decimal("1100.00"), None, date(2024, 1, 1), Decimal("100.00"), "1000.00", "1100.00", True),
        (Decimal("1000.00"), Decimal("1100.0009"), None, date(2024, 1, 1), Decimal("100.00"), "1000.00", "1100.00", True),
        (Decimal("1000.00"), Decimal("1100.001"), None, date(2024, 1, 1), Decimal("100.00"), "1000.00", "1100.00", True),
        (Decimal("1000.00"), Decimal("1100.01"), None, date(2024, 1, 1), Decimal("100.00"), "1000.00", "1100.00", False),
        (Decimal("0.00"), Decimal("150.00"), Decimal("100.00"), date(2024, 1, 1), Decimal("50.00"), "100.00", "150.00", True),
        (None, Decimal("25.00"), None, None, Decimal("25.00"), "0", "25.00", True),
    ],
)
async def test_validate_balance_chain_cases(db, test_user, opening, closing, manual_opening, period_start, txn_amount, expected_open, expected_calc, expected_match):
    stmt = await _stmt(db, test_user.id, file_hash=f"h_{uuid4().hex[:8]}", opening_balance=opening, closing_balance=closing, manual_opening_balance=manual_opening, period_start=period_start)
    await _txn(db, stmt, txn_amount)
    res = await validate_balance_chain(db, stmt.id)
    assert (res["opening_match"], res["closing_match"], res["opening_balance"], res["calculated_closing"]) == (True, expected_match, expected_open, expected_calc)
    if expected_match and opening is not None and manual_opening is None:
        assert Decimal(res["closing_delta"]) <= BALANCE_TOLERANCE


async def test_validate_balance_chain_reuse_isolation_and_approve_reject(db, test_user, monkeypatch):
    uid = test_user.id
    with pytest.raises(ValueError, match="Statement not found"):
        await validate_balance_chain(db, uuid4())

    stmt = await _stmt(db, uid, file_hash="hash123", opening_balance=Decimal("1000.00"), closing_balance=Decimal("1100.00"))
    await _txn(db, stmt, "100.00")
    txns = await resolve_statement_transactions(db, stmt)
    calls = {"resolve": 0, "get": 0, "post": 0}
    orig_resolve, orig_get = stmt_val_mod.resolve_statement_transactions, db.get

    async def spy_resolve(*a, **kw):
        calls["resolve"] += 1
        return await orig_resolve(*a, **kw)

    async def spy_get(*a, **kw):
        calls["get"] += 1
        return await orig_get(*a, **kw)

    async def spy_post(*_a, **_kw):
        calls["post"] += 1
        return txns

    monkeypatch.setattr(stmt_val_mod, "resolve_statement_transactions", spy_resolve)
    monkeypatch.setattr(db, "get", spy_get)
    assert (await validate_balance_chain(db, stmt.id, statement=stmt, transactions=txns))["closing_match"] is True and (calls["resolve"], calls["get"]) == (0, 0)

    monkeypatch.setattr(db, "get", orig_get)
    approved, ret_txns = await approve_statement_with_transactions(db, stmt.id, uid)
    assert (approved.stage1_status, approved.status, len(ret_txns), calls["resolve"]) == (Stage1Status.APPROVED, BankStatementStatus.APPROVED, 1, 1) and approved.balance_validation_result["closing_match"] is True

    monkeypatch.setattr(stmt_posting_mod, "resolve_statement_transactions", spy_post)
    await auto_create_posted_entries_for_statement(db, approved, uid, dependencies=posting_dependencies(), transactions=ret_txns)
    assert calls["post"] == 0

    with pytest.raises(ValueError, match="Statement not found or access denied"):
        await approve_statement_with_transactions(db, stmt.id, uuid4())
    stmt_rej = await _stmt(db, uid, file_hash="hash_rej", opening_balance=Decimal("1000.00"), closing_balance=Decimal("1100.00"))
    rejected = await reject_statement(db, stmt_rej.id, uid)
    assert (rejected.stage1_status, rejected.status, rejected.validation_error) == (Stage1Status.REJECTED, BankStatementStatus.REJECTED, None)
    assert (await reject_statement(db, stmt_rej.id, uid, reason="Bad")).validation_error == "Bad"

    bad = await _stmt(db, uid, file_hash="hash222", opening_balance=Decimal("1000.00"), closing_balance=Decimal("2000.00"))
    await _txn(db, bad, "10.00")
    with pytest.raises(ValueError, match="Balance mismatch"):
        await approve_statement_with_transactions(db, bad.id, uid)

    main_acc = (await AccountFactory.create_async(db, user_id=uid, name="Main", currency="USD")).id
    other_acc = (await AccountFactory.create_async(db, user_id=uid, name="Other", currency="USD")).id
    await _stmt(db, uid, file_hash="prev_other", account_id=other_acc, opening_balance=Decimal("10.00"), closing_balance=Decimal("2000.00"), status=BankStatementStatus.APPROVED)
    await _stmt(db, uid, file_hash="prev_main", account_id=main_acc, opening_balance=Decimal("1000.00"), closing_balance=Decimal("1200.00"), status=BankStatementStatus.APPROVED, stage1_status=Stage1Status.APPROVED)
    curr = await _stmt(db, uid, file_hash="curr_main", account_id=main_acc, opening_balance=Decimal("999.00"), closing_balance=Decimal("1149.00"), period_start=date(2024, 2, 1), period_end=date(2024, 2, 29))
    await _txn(db, curr, "150.00", txn_date=date(2024, 2, 15))
    iso = await validate_balance_chain(db, curr.id)
    assert (iso["opening_balance"], iso["previous_closing_balance"], iso["cross_period_delta"], iso["cross_period_match"], iso["balance_valid"]) == ("999.00", "1200.00", "-201.00", False, True)

    open_bad = await _stmt(db, uid, file_hash="open_curr", account_id=main_acc, opening_balance=Decimal("120.00"), closing_balance=Decimal("150.00"), period_start=date(2024, 3, 1), period_end=date(2024, 3, 31))
    await _txn(db, open_bad, "50.00", txn_date=date(2024, 3, 15))
    with pytest.raises(ValueError, match="Balance mismatch"):
        await approve_statement_with_transactions(db, open_bad.id, uid)


async def test_pending_stage1_review_filter_and_non_consecutive_period(db, test_user):
    uid = test_user.id
    s_med = await _stmt(db, uid, file_hash="h_pend", period_start=None, period_end=None, confidence_score=70)
    s_rev = await _stmt(db, uid, file_hash="h_rev", period_start=None, period_end=None, stage1_status=Stage1Status.PENDING_REVIEW, confidence_score=90)
    s_leg = await _stmt(db, uid, file_hash="h_high", period_start=None, period_end=None, confidence_score=90)
    s_app = await _stmt(db, uid, file_hash="h_app", opening_balance=Decimal("0.00"), closing_balance=Decimal("0.00"), status=BankStatementStatus.APPROVED, stage1_status=Stage1Status.APPROVED)
    s_papp = await _stmt(db, uid, file_hash="h_papp", period_start=None, period_end=None, stage1_status=Stage1Status.APPROVED)
    ids = set((await db.execute(select(StatementSummary.id).where(StatementSummary.user_id == uid, StatementSummary.status == BankStatementStatus.PARSED, pending_stage1_review_filter()))).scalars().all())
    assert ids == {s_med.id, s_rev.id, s_leg.id} and s_app.id not in ids and s_papp.id not in ids

    acc = (await AccountFactory.create_async(db, user_id=uid, name="DBS Checking", currency="USD")).id
    await _stmt(db, uid, file_hash="h_jan_2025", account_id=acc, opening_balance=Decimal("10000.00"), closing_balance=Decimal("12000.00"), period_start=date(2025, 1, 1), period_end=date(2025, 1, 31), status=BankStatementStatus.APPROVED, stage1_status=Stage1Status.APPROVED)
    mar = await _stmt(db, uid, file_hash="h_mar_2025", account_id=acc, opening_balance=Decimal("15000.00"), closing_balance=Decimal("18000.00"), period_start=date(2025, 3, 1), period_end=date(2025, 3, 31))
    await _txn(db, mar, "3000.00", txn_date=date(2025, 3, 15))
    res = await validate_balance_chain(db, mar.id)
    assert (res["opening_balance"], res["calculated_closing"], res["opening_delta"], res["closing_delta"], res["balance_valid"]) == ("15000.00", "18000.00", "0.00", "0.00", True)
    assert (res["previous_closing_balance"], res["previous_period_end"], res["cross_period_delta"], res["cross_period_match"], res["has_date_gap"]) == ("12000.00", "2025-01-31", "3000.00", False, True)
    approved, _ = await approve_statement_with_transactions(db, mar.id, uid)
    assert (approved.status, approved.stage1_status, approved.balance_validation_result["balance_valid"]) == (BankStatementStatus.APPROVED, Stage1Status.APPROVED, True)
