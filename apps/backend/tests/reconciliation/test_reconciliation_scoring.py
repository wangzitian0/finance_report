from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.extraction import TransactionDirection
from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine, fit_journal_memo
from src.reconciliation import (
    DEFAULT_CONFIG,
    ReconciliationConfig,
    _find_many_to_one_candidates,
    _find_normal_candidates,
    _find_transfer_candidates,
    build_many_to_one_groups,
    derive_reconciliation_score_tier,
    extract_merchant_tokens,
    is_cross_period,
    normalize_text,
    score_amount,
    score_date,
    score_description,
    score_single,
    weighted_total,
)


def _txn(description: str, amount: str = "10.00", *, user_id=None, txn_date: date = date(2024, 1, 1), direction: str = "OUT", statement_id=None) -> AtomicTransaction:
    return AtomicTransaction(id=uuid4(), user_id=user_id or uuid4(), txn_date=txn_date, description=description, amount=Decimal(amount), direction=TransactionDirection(direction), currency="SGD", dedup_hash=uuid4().hex, source_documents=[{"doc_id": str(statement_id or uuid4()), "doc_type": "bank_statement"}])


def _entry(memo: str = "Entry", amount: Decimal = Decimal("100.00"), entry_date: date = date(2024, 1, 1), *, debit_type: AccountType = AccountType.EXPENSE, credit_type: AccountType = AccountType.ASSET, user_id=None) -> JournalEntry:
    uid = user_id or uuid4()
    entry = JournalEntry(id=uuid4(), user_id=uid, entry_date=entry_date, memo=memo, source_type=JournalEntrySourceType.MANUAL, status=JournalEntryStatus.POSTED)
    da, ca = Account(id=uuid4(), user_id=uid, name="D", type=debit_type, currency="SGD"), Account(id=uuid4(), user_id=uid, name="C", type=credit_type, currency="SGD")
    entry.lines = [JournalLine(journal_entry_id=entry.id, account_id=da.id, account=da, direction=Direction.DEBIT, amount=amount, currency="SGD"), JournalLine(journal_entry_id=entry.id, account_id=ca.id, account=ca, direction=Direction.CREDIT, amount=amount, currency="SGD")]
    return entry


@pytest.mark.no_db
@pytest.mark.parametrize(("score", "expected"), [(None, "LOW"), (59, "LOW"), (60, "MEDIUM"), (84, "MEDIUM"), (85, "HIGH"), (100, "HIGH")])
def test_ac4_9_4_derive_reconciliation_score_tier(score: int | None, expected: str) -> None:
    assert derive_reconciliation_score_tier(score) == expected


@pytest.mark.no_db
def test_pure_scoring_engine_and_candidate_finders() -> None:
    cfg = replace(DEFAULT_CONFIG, amount_percent=Decimal("0.02"), amount_absolute=Decimal("1.00"), date_days=7)
    for a, b, expected in (("100.00", "100.00", 100.0), ("100.00", "100.01", 100.0), ("100.00", "101.50", 90.0), ("100.00", "104.00", 70.0), ("100.00", "200.00", 0.0)):
        assert score_amount(Decimal(a), Decimal(b), cfg) == expected
    assert score_amount(Decimal("10.00"), Decimal("10.10"), DEFAULT_CONFIG) == 90.0 and score_amount(Decimal("10.00"), Decimal("10.11"), DEFAULT_CONFIG) < 90.0

    d1, apr_27, may_02 = date(2025, 4, 15), date(2025, 4, 27), date(2025, 5, 2)
    assert (score_date(d1, d1, cfg), score_date(d1, date(2025, 4, 17), cfg), score_date(d1, date(2025, 4, 21), cfg)) == (100.0, 90.0, 70.0)
    assert is_cross_period(apr_27, may_02, max_days=7) is True and score_date(apr_27, may_02, cfg) == 75.0
    assert normalize_text("  GRAB* TAXI / TRIP #123  ") == "grab taxi trip 123"
    tokens = extract_merchant_tokens("POS DEBIT 987654 NETFLIX COM SINGAPORE")
    assert {"netflix", "singapore"} <= set(tokens) and "pos" not in tokens and "debit" not in tokens
    assert (score_description(None, "Grab Taxi"), score_description("Grab Taxi", None), score_description("Grab Taxi Singapore", "Grab Taxi Singapore")) == (0.0, 0.0, 100.0) and score_description("Grab Taxi", "Grab Car") > 40.0

    w_cfg = ReconciliationConfig(weight_amount=Decimal("0.40"), weight_date=Decimal("0.20"), weight_description=Decimal("0.20"), weight_business=Decimal("0.15"), weight_history=Decimal("0.05"), auto_accept=85, pending_review=60, amount_percent=Decimal("5.0"), amount_absolute=Decimal("1.00"), date_days=3)
    assert weighted_total({"amount": 100.0, "date": 80.0, "description": 60.0, "business": 50.0, "history": 0.0}, w_cfg) == 76 and weighted_total({"amount": 0.0, "date": 0.0, "description": 0.0, "business": 0.0, "history": 0.0}, w_cfg) == 0

    @dataclass
    class MockTxn:
        description: str
        txn_date: date
        direction: str = "OUT"
        currency: str = "SGD"

    groups = build_many_to_one_groups([MockTxn("", d1), MockTxn("   ", d1), MockTxn("Regular", d1), MockTxn("Batch settlement", d1), MockTxn("Batch settlement", d1)])
    assert len(groups) == 1 and len(groups[0]) == 2

    t_out, t_in = _txn("Transfer to savings account", "500.00", direction="OUT"), _txn("Transfer from checking", "200.00", direction="IN")
    res_out = _find_transfer_candidates(pending_txns=[t_out, _txn("Coffee Shop", "5.00")], atomic_txns=[], pattern_scores={}, config=DEFAULT_CONFIG)
    res_in = _find_transfer_candidates(pending_txns=[t_in], atomic_txns=[], pattern_scores={}, config=DEFAULT_CONFIG)
    assert len(res_out) == 1 and res_out[0][0] is t_out and res_out[0][1].score == 100 and "transfer_out" in res_out[0][1].breakdown and res_out[0][2] is None
    assert len(res_in) == 1 and "transfer_in" in res_in[0][1].breakdown and _find_transfer_candidates(pending_txns=[_txn("Grocery Store")], atomic_txns=[], pattern_scores={}, config=DEFAULT_CONFIG) == []

    t_sal, e_sal = _txn("Salary Payment", "1000.00", direction="IN", txn_date=date(2024, 1, 15)), _entry("Salary Payment", Decimal("1000.00"), date(2024, 1, 15), debit_type=AccountType.ASSET, credit_type=AccountType.INCOME)
    norm = _find_normal_candidates(pending_txns=[t_sal], atomic_txns=[e_sal], pattern_scores={}, config=DEFAULT_CONFIG, base_currency="SGD")
    assert len(norm) == 1 and norm[0][0] is t_sal and str(e_sal.id) in norm[0][1].journal_entry_ids
    assert _find_normal_candidates(pending_txns=[_txn("Random", "999.00")], atomic_txns=[_entry("Other", Decimal("1.00"))], pattern_scores={}, config=DEFAULT_CONFIG, base_currency="SGD") == []
    assert _find_normal_candidates(pending_txns=[_txn("Test", "100.00")], atomic_txns=[], pattern_scores={}, config=DEFAULT_CONFIG, base_currency="SGD") == []
    split = _find_normal_candidates(pending_txns=[_txn("Split Payment", "100.00", txn_date=date(2024, 4, 5))], atomic_txns=[_entry("Split Payment", Decimal("50.00"), date(2024, 4, 5)) for _ in range(2)], pattern_scores={}, config=DEFAULT_CONFIG, base_currency="SGD")
    triple = _find_normal_candidates(pending_txns=[_txn("Vendor ABC combined", "300.00")], atomic_txns=[_entry(f"Vendor ABC part {i}", Decimal("100.00")) for i in range(3)], pattern_scores={"vendor": 90.0}, config=DEFAULT_CONFIG, base_currency="SGD")
    assert len(split) == 1 and split[0][1].breakdown.get("multi_entry") == 1 and len(split[0][1].journal_entry_ids) == 2
    assert len(triple) == 1 and len(triple[0][1].journal_entry_ids) == 3 and triple[0][1].breakdown["multi_entry"] == 2

    m2o_txns = [_txn("Batch settlement ACME", a, txn_date=date(2024, 4, 1), statement_id=uuid4()) for a in ("40.00", "60.00")]
    m2o = _find_many_to_one_candidates(pending_txns=m2o_txns, atomic_txns=[_entry("Batch settlement ACME", Decimal("100.00"), date(2024, 4, 1))], pattern_scores={}, config=DEFAULT_CONFIG, base_currency="SGD")
    assert len(m2o) == 1 and m2o[0][0] in m2o_txns and m2o[0][1].breakdown.get("many_to_one_bonus") == 10.0 and m2o[0][1].breakdown.get("group_total") == "100.00"
    assert _find_many_to_one_candidates(pending_txns=[_txn("Coffee Shop", "5.00") for _ in range(2)], atomic_txns=[_entry("Coffee", Decimal("10.00"))], pattern_scores={}, config=DEFAULT_CONFIG, base_currency="SGD") == []
    assert _find_many_to_one_candidates(pending_txns=m2o_txns, atomic_txns=[], pattern_scores={}, config=DEFAULT_CONFIG, base_currency="SGD") == []


async def test_AC4_9_1_and_2548_1_bank_side_cjk_and_truncated_memo_scoring(db: AsyncSession) -> None:
    uid = uuid4()
    bank, expense, clearing, payable = [Account(id=uuid4(), user_id=uid, name=n, type=t, currency="SGD") for n, t in (("Chk", AccountType.ASSET), ("Exp", AccountType.EXPENSE), ("Clr", AccountType.ASSET), ("Pay", AccountType.LIABILITY))]
    entry = JournalEntry(id=uuid4(), user_id=uid, entry_date=date(2026, 1, 5), memo="Vendor split", lines=[JournalLine(account=expense, direction=Direction.DEBIT, amount=Decimal("100.00")), JournalLine(account=clearing, direction=Direction.DEBIT, amount=Decimal("20.00")), JournalLine(account=bank, direction=Direction.CREDIT, amount=Decimal("100.00")), JournalLine(account=payable, direction=Direction.CREDIT, amount=Decimal("20.00"))])
    assert (await score_single(db, _txn("Vendor payment", "100.00", user_id=uid, txn_date=date(2026, 1, 5)), [entry], DEFAULT_CONFIG, user_id=uid, history_score=0)).breakdown["amount"] == 100.0

    assert normalize_text("微信支付-星巴克") == "微信支付 星巴克" and score_description("微信支付-星巴克", "微信支付-星巴克") == 100.0 and score_description("微信支付星巴克", "星巴克咖啡") > 0.0
    assert "星巴克" in extract_merchant_tokens("微信支付-星巴克") and "美团" in extract_merchant_tokens("微信支付美团")
    cjk = await score_single(db, _txn("微信支付-星巴克", "38.00", user_id=uid, txn_date=date(2026, 3, 1)), [_entry("微信支付-星巴克", Decimal("38.00"), date(2026, 3, 1), user_id=uid)], DEFAULT_CONFIG, user_id=uid, history_score=0.0)
    assert cjk.breakdown["description"] == 100.0 and cjk.score >= 85

    long_desc = "PAYNOW " + "A" * 593
    cut_memo = fit_journal_memo(long_desc)
    assert len(long_desc) == 600 and len(cut_memo) == 500
    long_entry = _entry(cut_memo, Decimal("120.00"), date(2026, 3, 2), user_id=uid)
    c_long = await score_single(db, _txn(long_desc, "120.00", user_id=uid, txn_date=date(2026, 3, 2)), [long_entry], DEFAULT_CONFIG, user_id=uid, history_score=0.0)
    c_short = await score_single(db, _txn(cut_memo, "120.00", user_id=uid, txn_date=date(2026, 3, 2)), [long_entry], DEFAULT_CONFIG, user_id=uid, history_score=0.0)
    assert c_long.breakdown["description"] == 100.0 and c_long.score == c_short.score >= 85
