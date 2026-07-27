"""Acceptance proofs for #1969's canonical economic-disposition command."""

from __future__ import annotations

import asyncio
import inspect
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.audit import JournalEntrySourceType
from src.extraction.orm.layer2 import AtomicTransaction, TransactionDirection
from src.identity import User
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    TransferPair,
)
from src.reconciliation import entry_bank_side_amount, entry_total_amount
from src.reconciliation.extension.matching import execute_matching
from src.reconciliation.extension.repository import SqlReconciliationRepository
from src.reconciliation.extension.transfer_pairs import (
    InvalidTransferPairError,
    list_unpaired_transfer_dispositions,
    persist_transfer_pairs,
)
from src.reconciliation.orm.reconciliation import (
    DispositionKind,
    ReconciliationMatch,
    ReconciliationMatchJournalEntry,
    ReconciliationStatus,
    ReconciliationTransferPair,
    ReconciliationTransferPairLeg,
)


def _atomic(user_id: UUID, *, description: str = "payment", currency: str = "SGD") -> AtomicTransaction:
    return AtomicTransaction(
        user_id=user_id,
        txn_date=date(2026, 7, 20),
        amount=Decimal("100.00"),
        direction=TransactionDirection.OUT,
        description=description,
        currency=currency,
        dedup_hash=uuid4().hex + uuid4().hex,
        source_documents=[],
    )


def _match(txn_id: UUID, *, kind: DispositionKind = DispositionKind.JOURNAL_MATCH) -> ReconciliationMatch:
    return ReconciliationMatch(
        atomic_txn_id=txn_id,
        journal_entry_ids=[],
        match_score=90,
        score_breakdown={},
        status=ReconciliationStatus.PENDING_REVIEW,
        disposition_kind=kind,
    )


@pytest.mark.asyncio
async def test_AC_reconciliation_economic_disposition_1_normal_candidate_precedes_transfer(
    db: AsyncSession,
    test_user,
) -> None:
    """AC-reconciliation.economic-disposition.1: journal evidence wins."""
    txn = _atomic(test_user.id, description="internal transfer rent")
    cash = Account(user_id=test_user.id, name="Cash", code="1001", type=AccountType.ASSET, currency="SGD")
    expense = Account(
        user_id=test_user.id,
        name="Rent",
        code="5001",
        type=AccountType.EXPENSE,
        currency="SGD",
    )
    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=txn.txn_date,
        memo=txn.description,
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    entry.lines = [
        JournalLine(account=expense, direction=Direction.DEBIT, amount=txn.amount, currency="SGD"),
        JournalLine(account=cash, direction=Direction.CREDIT, amount=txn.amount, currency="SGD"),
    ]
    db.add_all([txn, entry])
    await db.flush()

    matches = await execute_matching(db, user_id=test_user.id, currency="SGD")

    assert len(matches) == 1
    assert matches[0].disposition_kind == DispositionKind.JOURNAL_MATCH
    assert matches[0].journal_entry_ids == [str(entry.id)]
    processing_lines = await db.scalar(
        select(func.count())
        .select_from(JournalLine)
        .join(Account, Account.id == JournalLine.account_id)
        .where(Account.user_id == test_user.id, Account.code == "1199")
    )
    assert processing_lines == 0


@pytest.mark.asyncio
async def test_AC_reconciliation_economic_disposition_2_database_rejects_duplicate_active_heads(
    db: AsyncSession,
    test_user,
) -> None:
    """AC-reconciliation.economic-disposition.2: the database is the final lock."""
    txn = _atomic(test_user.id)
    db.add(txn)
    await db.flush()
    db.add_all([_match(txn.id), _match(txn.id)])
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


@pytest.mark.asyncio
async def test_AC_reconciliation_economic_disposition_3_two_sessions_converge(
    db: AsyncSession,
    db_engine,
    test_user,
) -> None:
    """AC-reconciliation.economic-disposition.3: independent workers reuse one winner."""
    txn = _atomic(test_user.id)
    db.add(txn)
    await db.commit()
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    start = asyncio.Event()
    ready = 0
    ready_lock = asyncio.Lock()
    effects: list[UUID] = []

    async def worker() -> tuple[UUID, bool]:
        nonlocal ready
        async with maker() as session:
            async with ready_lock:
                ready += 1
                if ready == 2:
                    start.set()
            await start.wait()
            repository = SqlReconciliationRepository(session)
            winner = await repository.claim_transaction(txn.id)
            created = winner is None
            if winner is None:
                winner = _match(txn.id)
                await repository.add_match(winner)
                await session.flush()
                effects.append(winner.id)
            await session.commit()
            return winner.id, created

    first, second = await asyncio.wait_for(asyncio.gather(worker(), worker()), timeout=10)
    assert first[0] == second[0]
    assert sorted((first[1], second[1])) == [False, True]
    assert effects == [first[0]] or effects == [second[0]]


def _journal(user_id: UUID, memo: str) -> JournalEntry:
    return JournalEntry(
        user_id=user_id,
        entry_date=date(2026, 7, 20),
        memo=memo,
        source_type=JournalEntrySourceType.SYSTEM,
        status=JournalEntryStatus.DRAFT,
    )


@pytest.mark.asyncio
async def test_AC_reconciliation_economic_disposition_4_transfer_pair_round_trip(
    db: AsyncSession,
    test_user,
) -> None:
    """AC-reconciliation.economic-disposition.4: pair state survives a round trip."""
    out_txn = _atomic(test_user.id, description="transfer out")
    in_txn = _atomic(test_user.id, description="transfer in")
    in_txn.direction = TransactionDirection.IN
    extra_txn = _atomic(test_user.id, description="unpaired transfer")
    out_entry = _journal(test_user.id, "transfer out")
    in_entry = _journal(test_user.id, "transfer in")
    db.add_all([out_txn, in_txn, extra_txn, out_entry, in_entry])
    await db.flush()
    out_match = _match(out_txn.id, kind=DispositionKind.TRANSFER_LEG)
    in_match = _match(in_txn.id, kind=DispositionKind.TRANSFER_LEG)
    extra_match = _match(extra_txn.id, kind=DispositionKind.TRANSFER_LEG)
    out_match.journal_entry_ids = [str(out_entry.id)]
    in_match.journal_entry_ids = [str(in_entry.id)]
    db.add_all([out_match, in_match, extra_match])
    await db.flush()
    db.add_all(
        [
            ReconciliationMatchJournalEntry(match_id=out_match.id, journal_entry_id=out_entry.id),
            ReconciliationMatchJournalEntry(match_id=in_match.id, journal_entry_id=in_entry.id),
        ]
    )
    await db.flush()
    candidate = TransferPair(
        out_entry=out_entry,
        in_entry=in_entry,
        confidence=96,
        score_breakdown={"amount": 100.0},
    )

    in_txn.direction = TransactionDirection.OUT
    await db.flush()
    with pytest.raises(InvalidTransferPairError):
        await persist_transfer_pairs(db, [candidate])
    in_txn.direction = TransactionDirection.IN
    in_txn.currency = "USD"
    await db.flush()
    with pytest.raises(InvalidTransferPairError):
        await persist_transfer_pairs(db, [candidate])
    in_txn.currency = "SGD"
    out_txn.currency = "sgd"
    await db.flush()

    invalid_currency = "XYZ"
    in_txn.currency = invalid_currency
    await db.flush()
    with pytest.raises(InvalidTransferPairError, match="valid ISO-4217"):
        await persist_transfer_pairs(db, [candidate])
    in_txn.currency = "SGD"

    other_user = User(email=f"pair-{uuid4()}@example.com", hashed_password="hashed")
    db.add(other_user)
    await db.flush()
    foreign_txn = _atomic(other_user.id, description="foreign transfer")
    foreign_txn.direction = TransactionDirection.IN
    foreign_entry = _journal(other_user.id, "foreign transfer")
    db.add_all([foreign_txn, foreign_entry])
    await db.flush()
    foreign_match = _match(foreign_txn.id, kind=DispositionKind.TRANSFER_LEG)
    foreign_match.journal_entry_ids = [str(foreign_entry.id)]
    db.add(foreign_match)
    await db.flush()
    db.add(ReconciliationMatchJournalEntry(match_id=foreign_match.id, journal_entry_id=foreign_entry.id))
    await db.flush()
    cross_tenant = TransferPair(
        out_entry=out_entry,
        in_entry=foreign_entry,
        confidence=96,
        score_breakdown={"amount": 100.0},
    )
    with pytest.raises(InvalidTransferPairError):
        await persist_transfer_pairs(db, [cross_tenant])

    assert len(await persist_transfer_pairs(db, [candidate])) == 1
    assert await persist_transfer_pairs(db, [candidate]) == []
    reversed_candidate = TransferPair(
        out_entry=in_entry,
        in_entry=out_entry,
        confidence=95,
        score_breakdown={"amount": 100.0},
    )
    with pytest.raises(InvalidTransferPairError):
        await persist_transfer_pairs(db, [reversed_candidate])
    assert await db.scalar(select(func.count()).select_from(ReconciliationTransferPair)) == 1
    assert await db.scalar(select(func.count()).select_from(ReconciliationTransferPairLeg)) == 2
    assert ReconciliationTransferPair.__table__.c.score_breakdown.nullable is False
    unpaired = await list_unpaired_transfer_dispositions(db, user_id=test_user.id)
    assert [item.id for item in unpaired] == [extra_match.id]


def test_AC_reconciliation_economic_disposition_5_currency_is_explicit() -> None:
    """AC-reconciliation.economic-disposition.5: mixed currency is never summed nominally."""
    user_id = uuid4()
    sgd = Account(user_id=user_id, name="SGD cash", code="1001", type=AccountType.ASSET, currency="SGD")
    usd = Account(user_id=user_id, name="USD cash", code="1002", type=AccountType.ASSET, currency="USD")
    entry = _journal(user_id, "mixed currency")
    entry.lines = [
        JournalLine(account=sgd, direction=Direction.CREDIT, amount=Decimal("100.00"), currency="SGD"),
        JournalLine(account=usd, direction=Direction.CREDIT, amount=Decimal("900.00"), currency="USD"),
        JournalLine(account=sgd, direction=Direction.DEBIT, amount=Decimal("100.00"), currency="SGD"),
        JournalLine(account=usd, direction=Direction.DEBIT, amount=Decimal("900.00"), currency="USD"),
    ]

    assert entry_bank_side_amount(entry, "OUT", currency="SGD") == Decimal("100.00")
    assert entry_total_amount(entry, currency="USD") == Decimal("900.00")
    with pytest.raises(TypeError):
        entry_total_amount(entry)  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_AC_reconciliation_economic_disposition_6_retry_and_phase_permutation_are_idempotent(
    db: AsyncSession,
    db_engine,
    test_user,
) -> None:
    """AC-reconciliation.economic-disposition.6: rollback/retry preserves cardinality."""
    txn = _atomic(test_user.id)
    db.add(txn)
    await db.commit()
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    async with maker() as failed:
        repository = SqlReconciliationRepository(failed)
        assert await repository.claim_transaction(txn.id) is None
        await repository.add_match(_match(txn.id))
        await failed.flush()
        await failed.rollback()

    async with maker() as retry:
        repository = SqlReconciliationRepository(retry)
        assert await repository.claim_transaction(txn.id) is None
        await repository.add_match(_match(txn.id))
        await retry.commit()

    for phase_order in (
        (DispositionKind.JOURNAL_MATCH, DispositionKind.TRANSFER_LEG),
        (DispositionKind.TRANSFER_LEG, DispositionKind.JOURNAL_MATCH),
    ):
        async with maker() as repeated:
            observed_winners = []
            for _candidate_kind in phase_order:
                winner = await SqlReconciliationRepository(repeated).claim_transaction(txn.id)
                assert winner is not None
                observed_winners.append((winner.id, winner.disposition_kind))
            assert observed_winners == [
                (winner.id, DispositionKind.JOURNAL_MATCH),
                (winner.id, DispositionKind.JOURNAL_MATCH),
            ]
            await repeated.commit()

    async with maker() as verification:
        count = await verification.scalar(
            select(func.count()).select_from(ReconciliationMatch).where(ReconciliationMatch.atomic_txn_id == txn.id)
        )
        assert count == 1


def test_AC_reconciliation_economic_disposition_7_processing_uses_typed_ledger_boundary() -> None:
    """AC-reconciliation.economic-disposition.7: no reconciliation-owned posting path."""
    from src.reconciliation.extension.phases import transfer_detection

    source = inspect.getsource(transfer_detection)
    assert "repository.claim_transaction(txn.id)" in source
    assert source.index("repository.claim_transaction(txn.id)") < source.index("create_transfer_out_entry(")
    assert "JournalEntry(" not in source
    assert "JournalLine(" not in source
    assert "from src.ledger import (" in source
    path = Path(inspect.getsourcefile(transfer_detection) or "")
    assert path.name == "transfer_detection.py"
