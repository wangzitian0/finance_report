from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import Base
from src.extraction import TransactionDirection
from src.extraction.orm.bank_custody_binding import BankCustodyBinding
from src.extraction.orm.layer2 import AtomicPosition, AtomicTransaction
from src.extraction.orm.statement_summary import StatementSummary
from src.identity import User
from src.ledger import JournalLine
from src.pricing import ManualValuationComponentType, ManualValuationLiquidityClass
from src.pricing.orm.manual_valuation import ManualValuationSnapshot
from src.runtime.extension.snapshot_anonymizer import (
    Action,
    UnclassifiedColumnError,
    _pseudonym,
    anonymize,
    classify_columns,
    scan_for_residuals,
)
from tests.factories import AccountFactory
from tests.ledger._ledger_helpers import create_valid_posted_entry

pytestmark = pytest.mark.asyncio
SECRET, FACTOR = "test-anonymizer-secret", 3


def test_AC_runtime_snapshot_anonymizer_1_every_live_column_is_classified() -> None:
    plan = classify_columns(Base.metadata)
    expected = {
        "journal_lines.amount": Action.SCALE,
        "journal_lines.fx_rate": Action.KEEP,
        "users.email": Action.PSEUDONYM,
        "users.hashed_password": Action.REDACT_SECRET,
        "atomic_transactions.source_documents": Action.REDACT_JSON,
        "opening_position_records.amount": Action.SCALE,
        "opening_position_records.fx_rate": Action.KEEP,
        "opening_position_records.currency": Action.KEEP,
        "opening_position_records.content_digest": Action.PSEUDONYM,
        "atomic_transaction_identities.currency": Action.KEEP,
        "atomic_transaction_identities.custody_scope": Action.PSEUDONYM,
        "atomic_transaction_identities.identity_hash": Action.PSEUDONYM,
        "atomic_transaction_identities.legacy_hash": Action.PSEUDONYM,
        "bank_custody_bindings.currency": Action.KEEP,
        "bank_custody_bindings.institution": Action.PSEUDONYM,
        "bank_custody_bindings.account_last4": Action.PSEUDONYM,
        "outbox.last_error": Action.PSEUDONYM,
    }
    assert {k: plan[k] for k in expected} == expected and len(plan) == sum(
        len(t.columns) for t in Base.metadata.sorted_tables
    )
    scratch = sa.MetaData()
    sa.Table("brand_new_table", scratch, sa.Column("free_text", sa.String(100)))
    with pytest.raises(UnclassifiedColumnError, match="brand_new_table.free_text"):
        classify_columns(scratch)


async def _seed(db: AsyncSession, uid) -> tuple:
    entry = await create_valid_posted_entry(db, uid, memo="Salary from Acme Corp", amount=Decimal("2500.00"))
    acc = await AccountFactory.create_async(db, user_id=uid)
    bnd = BankCustodyBinding(
        user_id=uid, institution="Generated Private Bank", account_last4="9876", currency="SGD", account_id=acc.id
    )
    txn = AtomicTransaction(
        user_id=uid,
        txn_date=date(2026, 5, 2),
        amount=Decimal("2500.00"),
        currency="SGD",
        direction=TransactionDirection.IN,
        description="ACME CORP PAYROLL MAY",
        source_documents={"documents": [{"doc_id": "real-doc-1", "broker": "DBS Bank"}]},
        dedup_hash="real-dedup-hash-001",
    )
    pos = AtomicPosition(
        user_id=uid,
        snapshot_date=date(2026, 5, 31),
        asset_identifier="AAPL",
        broker="Moomoo Real Broker",
        quantity=Decimal("10"),
        market_value=Decimal("1800.00"),
        currency="SGD",
        dedup_hash="real-dedup-hash-002",
        source_documents={},
    )
    val = ManualValuationSnapshot(
        user_id=uid,
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
        as_of_date=date(2026, 5, 1),
        value=Decimal("1200000.00"),
        currency="SGD",
        source="Sunny Vale Condo",
        notes="Bought from John Tan in 2020",
    )
    db.add_all([txn, pos, val, bnd])
    await db.flush()
    return entry.id, pos.id, txn.id, val.id, bnd.id, acc.id


async def test_AC_runtime_snapshot_anonymizer_2_to_4_all_invariants(db: AsyncSession, test_user) -> None:
    uid = test_user.id
    conn = await db.connection()
    with pytest.raises(ValueError, match="scale_factor"):
        await conn.run_sync(lambda c: anonymize(c, Base.metadata, secret=SECRET, scale_factor=1))
    originals = {f"{n:04d}" for n in range(10000)}
    assert {_pseudonym(SECRET, v, "digits4") for v in originals} == originals and all(
        _pseudonym(SECRET, v, "digits4") != v for v in originals
    )
    for bad in ("123", "12345", "12X4", "１２３４"):
        with pytest.raises(ValueError, match="four ASCII digits"):
            _pseudonym(SECRET, bad, "digits4")

    eid, pid, tid, vid, bid, cid = await _seed(db, uid)
    pair_ids = []
    for suffix in ("0022", "0050"):
        acc = await AccountFactory.create_async(db, user_id=uid)
        b = BankCustodyBinding(
            user_id=uid, institution="Generated Collision Bank", account_last4=suffix, currency="SGD", account_id=acc.id
        )
        s = StatementSummary(
            user_id=uid,
            file_hash=f"generated-collision-{suffix}",
            institution=b.institution,
            account_last4=suffix,
            currency="SGD",
            account_id=acc.id,
        )
        db.add_all([b, s])
        await db.flush()
        pair_ids.append((b.id, s.id))
    s9876 = StatementSummary(
        user_id=uid,
        file_hash="real-statement-hash-9876",
        institution="Generated Private Bank",
        account_last4="9876",
        currency="SGD",
        account_id=(await AccountFactory.create_async(db, user_id=uid)).id,
    )
    db.add(s9876)
    for cents, memo in ((Decimal("33.33"), "coffee"), (Decimal("1234.57"), "rent x")):
        await create_valid_posted_entry(db, uid, memo=f"entry {memo}", amount=cents)
    await db.flush()
    s9876_id = s9876.id

    conn = await db.connection()
    report = await conn.run_sync(lambda c: anonymize(c, Base.metadata, secret=SECRET, scale_factor=FACTOR))
    assert report.scale_factor == FACTOR
    db.expire_all()

    lines = (await db.execute(sa.select(JournalLine).where(JournalLine.journal_entry_id == eid))).scalars().all()
    assert sorted(line.amount for line in lines) == [Decimal("7500.00"), Decimal("7500.00")]
    totals = dict(
        (
            await db.execute(
                sa.text(
                    "SELECT direction, SUM(amount) FROM journal_lines jl JOIN journal_entries je ON jl.journal_entry_id = je.id WHERE je.user_id = :uid GROUP BY direction"
                ).bindparams(uid=uid)
            )
        ).all()
    )
    assert totals.get("DEBIT") == totals.get("CREDIT") is not None

    pos, txn, val, bnd = (
        await db.get(AtomicPosition, pid),
        await db.get(AtomicTransaction, tid),
        await db.get(ManualValuationSnapshot, vid),
        await db.get(BankCustodyBinding, bid),
    )
    assert (pos.market_value, pos.quantity, bnd.currency, bnd.account_id, txn.source_documents) == (
        Decimal("5400.00"),
        Decimal("10"),
        "SGD",
        cid,
        {"anonymized": True},
    )
    assert (
        bnd.institution != "Generated Private Bank"
        and bnd.account_last4 != "9876"
        and len(bnd.account_last4) == 4
        and bnd.account_last4.isdigit()
    )
    assert (
        txn.description != "ACME CORP PAYROLL MAY"
        and val.source != "Sunny Vale Condo"
        and "John Tan" not in (val.notes or "")
    )
    u = (await db.execute(sa.text("SELECT email, hashed_password FROM users WHERE id = :id").bindparams(id=uid))).one()
    assert (
        u.email.endswith("@anonymized.invalid")
        and u.hashed_password == "!anonymized"
        and _pseudonym(SECRET, "Moomoo Real Broker", "generic") == _pseudonym(SECRET, "Moomoo Real Broker", "generic")
    )

    suffixes = []
    for pbid, psid in pair_ids:
        pb, ps = await db.get(BankCustodyBinding, pbid), await db.get(StatementSummary, psid)
        assert (pb.account_last4, pb.institution, pb.account_id) == (ps.account_last4, ps.institution, ps.account_id)
        suffixes.append(pb.account_last4)
    assert len(set(suffixes)) == 2 and not (set(suffixes) & {"0022", "0050"}) and "9876" in report.original_values

    assert await conn.run_sync(lambda c: scan_for_residuals(c, Base.metadata, report.original_values)) == []
    await db.execute(sa.update(User).where(User.id == uid).values(email="anon-987600001111@snapshot.local"))
    await db.execute(
        sa.update(StatementSummary)
        .where(StatementSummary.id == s9876_id)
        .values(file_hash="9876abcdef0123456789abcdef0123456789abcdef0123456789abcdef012345")
    )
    await db.flush()
    assert await conn.run_sync(lambda c: scan_for_residuals(c, Base.metadata, report.original_values)) == []

    await db.execute(sa.update(BankCustodyBinding).where(BankCustodyBinding.id == bid).values(account_last4="9876"))
    await db.execute(
        sa.update(AtomicTransaction)
        .where(AtomicTransaction.id == tid)
        .values(description="wire from ACME CORP PAYROLL MAY Card 9876")
    )
    await db.flush()
    assert sorted(await conn.run_sync(lambda c: scan_for_residuals(c, Base.metadata, report.original_values))) == [
        "atomic_transactions.description",
        "bank_custody_bindings.account_last4",
    ]
