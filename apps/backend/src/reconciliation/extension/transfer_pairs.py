"""Persistence for reconciliation-owned transfer-pair decisions."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import Currency, InvalidCurrencyError
from src.extraction import TransactionDirection
from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import TransferPair
from src.reconciliation.orm.reconciliation import (
    DispositionKind,
    ReconciliationMatch,
    ReconciliationMatchJournalEntry,
    ReconciliationStatus,
    ReconciliationTransferPair,
    ReconciliationTransferPairLeg,
    TransferPairDecision,
    TransferPairLegRole,
    TransferPairReviewState,
)


class InvalidTransferPairError(ValueError):
    """Candidate violates the reconciliation transfer-pair aggregate."""


def _current_transfer_leg_clauses():
    return (
        ReconciliationMatch.disposition_kind == DispositionKind.TRANSFER_LEG,
        ReconciliationMatch.status != ReconciliationStatus.SUPERSEDED,
        ReconciliationMatch.superseded_by_id.is_(None),
    )


async def persist_transfer_pairs(
    db: AsyncSession,
    pairs: Sequence[TransferPair],
    *,
    decision: TransferPairDecision = TransferPairDecision.AUTO_PAIRED,
) -> list[ReconciliationTransferPair]:
    """Persist discovered ledger pairs against their current dispositions."""
    if not pairs:
        return []

    entry_ids = {eid for p in pairs for eid in (p.out_entry.id, p.in_entry.id)}
    rows = (
        await db.execute(
            select(
                ReconciliationMatchJournalEntry.journal_entry_id,
                ReconciliationMatch,
                AtomicTransaction.user_id,
                AtomicTransaction.direction,
                AtomicTransaction.currency,
            )
            .join(ReconciliationMatch, ReconciliationMatch.id == ReconciliationMatchJournalEntry.match_id)
            .join(AtomicTransaction, AtomicTransaction.id == ReconciliationMatch.atomic_txn_id)
            .where(ReconciliationMatchJournalEntry.journal_entry_id.in_(entry_ids), *_current_transfer_leg_clauses())
        )
    ).all()
    by_entry = {eid: (disp, uid, d, ccy) for eid, disp, uid, d, ccy in rows}
    persisted: list[ReconciliationTransferPair] = []

    for pair in pairs:
        out_leg, in_leg = by_entry.get(pair.out_entry.id), by_entry.get(pair.in_entry.id)
        if out_leg is None or in_leg is None:
            continue
        out_disp, out_user_id, out_direction, out_ccy = out_leg
        in_disp, in_user_id, in_direction, in_ccy = in_leg
        try:
            out_currency_code, in_currency_code = Currency.of(out_ccy).code, Currency.of(in_ccy).code
        except InvalidCurrencyError as exc:
            raise InvalidTransferPairError("Transfer pair legs require valid ISO-4217 currencies") from exc
        if (
            pair.out_entry.id == pair.in_entry.id
            or pair.out_entry.user_id != out_user_id
            or pair.in_entry.user_id != in_user_id
            or out_user_id != in_user_id
            or out_direction != TransactionDirection.OUT
            or in_direction != TransactionDirection.IN
            or out_currency_code != in_currency_code
        ):
            raise InvalidTransferPairError(
                "Transfer pair legs must be distinct, tenant-consistent, opposite-direction, and same-currency"
            )
        pair_id = uuid4()
        now = datetime.now(UTC)
        persisted_pair = ReconciliationTransferPair(
            id=pair_id,
            decision=decision,
            review_state=TransferPairReviewState.PAIRED,
            confidence=pair.confidence,
            score_breakdown=pair.score_breakdown,
            version=1,
            created_at=now,
            updated_at=now,
        )
        try:
            async with db.begin_nested():
                db.add_all(
                    [
                        persisted_pair,
                        ReconciliationTransferPairLeg(
                            pair_id=pair_id, role=TransferPairLegRole.OUT, disposition_id=out_disp.id
                        ),
                        ReconciliationTransferPairLeg(
                            pair_id=pair_id, role=TransferPairLegRole.IN, disposition_id=in_disp.id
                        ),
                    ]
                )
                await db.flush()
        except IntegrityError:
            continue
        persisted.append(persisted_pair)
    return persisted


def _current_pair_ids() -> Select[tuple[UUID]]:
    return (
        select(ReconciliationTransferPairLeg.pair_id)
        .join(ReconciliationMatch, ReconciliationMatch.id == ReconciliationTransferPairLeg.disposition_id)
        .where(
            ReconciliationMatch.status != ReconciliationStatus.SUPERSEDED,
            ReconciliationMatch.superseded_by_id.is_(None),
        )
        .group_by(ReconciliationTransferPairLeg.pair_id)
        .having(func.count() == 2)
    )


async def paired_transfer_entry_ids(db: AsyncSession, *, user_id: UUID) -> set[UUID]:
    result = await db.execute(
        select(ReconciliationMatchJournalEntry.journal_entry_id)
        .join(ReconciliationMatch, ReconciliationMatch.id == ReconciliationMatchJournalEntry.match_id)
        .join(AtomicTransaction, AtomicTransaction.id == ReconciliationMatch.atomic_txn_id)
        .join(ReconciliationTransferPairLeg, ReconciliationTransferPairLeg.disposition_id == ReconciliationMatch.id)
        .join(ReconciliationTransferPair, ReconciliationTransferPair.id == ReconciliationTransferPairLeg.pair_id)
        .where(
            AtomicTransaction.user_id == user_id,
            *_current_transfer_leg_clauses(),
            ReconciliationTransferPair.review_state == TransferPairReviewState.PAIRED,
            ReconciliationTransferPair.id.in_(_current_pair_ids()),
        )
    )
    return set(result.scalars().all())


async def list_unpaired_transfer_dispositions(db: AsyncSession, *, user_id: UUID) -> list[ReconciliationMatch]:
    paired_ids = select(ReconciliationTransferPairLeg.disposition_id).where(
        ReconciliationTransferPairLeg.pair_id.in_(_current_pair_ids())
    )
    result = await db.execute(
        select(ReconciliationMatch)
        .join(AtomicTransaction, AtomicTransaction.id == ReconciliationMatch.atomic_txn_id)
        .where(
            AtomicTransaction.user_id == user_id,
            *_current_transfer_leg_clauses(),
            ReconciliationMatch.id.notin_(paired_ids),
        )
        .order_by(ReconciliationMatch.created_at, ReconciliationMatch.id)
    )
    return list(result.scalars().all())


__all__ = [
    "InvalidTransferPairError",
    "list_unpaired_transfer_dispositions",
    "paired_transfer_entry_ids",
    "persist_transfer_pairs",
]
