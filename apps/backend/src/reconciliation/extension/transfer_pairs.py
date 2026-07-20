"""Persistence for reconciliation-owned transfer-pair decisions."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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


async def persist_transfer_pairs(
    db: AsyncSession,
    pairs: Sequence[TransferPair],
) -> list[ReconciliationTransferPair]:
    """Persist discovered ledger pairs against their current dispositions."""
    if not pairs:
        return []

    entry_ids = {entry_id for pair in pairs for entry_id in (pair.out_entry.id, pair.in_entry.id)}
    rows = (
        await db.execute(
            select(
                ReconciliationMatchJournalEntry.journal_entry_id,
                ReconciliationMatch,
            )
            .join(
                ReconciliationMatch,
                ReconciliationMatch.id == ReconciliationMatchJournalEntry.match_id,
            )
            .where(
                ReconciliationMatchJournalEntry.journal_entry_id.in_(entry_ids),
                ReconciliationMatch.disposition_kind == DispositionKind.TRANSFER_LEG,
                ReconciliationMatch.status != ReconciliationStatus.SUPERSEDED,
                ReconciliationMatch.superseded_by_id.is_(None),
            )
        )
    ).all()
    disposition_by_entry = {entry_id: disposition for entry_id, disposition in rows}
    persisted: list[ReconciliationTransferPair] = []
    for pair in pairs:
        out_disposition = disposition_by_entry.get(pair.out_entry.id)
        in_disposition = disposition_by_entry.get(pair.in_entry.id)
        if out_disposition is None or in_disposition is None:
            continue
        pair_id = uuid4()
        persisted_pair = ReconciliationTransferPair(
            id=pair_id,
            decision=TransferPairDecision.AUTO_PAIRED,
            review_state=TransferPairReviewState.PAIRED,
            confidence=pair.confidence,
            score_breakdown=pair.score_breakdown,
            version=1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        try:
            async with db.begin_nested():
                db.add_all(
                    [
                        persisted_pair,
                        ReconciliationTransferPairLeg(
                            pair_id=pair_id,
                            role=TransferPairLegRole.OUT,
                            disposition_id=out_disposition.id,
                        ),
                        ReconciliationTransferPairLeg(
                            pair_id=pair_id,
                            role=TransferPairLegRole.IN,
                            disposition_id=in_disposition.id,
                        ),
                    ]
                )
                await db.flush()
        except IntegrityError:
            # Another worker already paired at least one leg. The savepoint
            # removes this candidate pair without poisoning the outer command.
            continue
        persisted.append(persisted_pair)
    return persisted


async def list_unpaired_transfer_dispositions(
    db: AsyncSession,
    *,
    user_id: UUID,
) -> list[ReconciliationMatch]:
    """Return current transfer dispositions absent from either pair side."""
    paired_ids = select(ReconciliationTransferPairLeg.disposition_id)
    result = await db.execute(
        select(ReconciliationMatch)
        .join(
            AtomicTransaction,
            AtomicTransaction.id == ReconciliationMatch.atomic_txn_id,
        )
        .where(
            AtomicTransaction.user_id == user_id,
            ReconciliationMatch.disposition_kind == DispositionKind.TRANSFER_LEG,
            ReconciliationMatch.status != ReconciliationStatus.SUPERSEDED,
            ReconciliationMatch.superseded_by_id.is_(None),
            ReconciliationMatch.id.notin_(paired_ids),
        )
        .order_by(ReconciliationMatch.created_at, ReconciliationMatch.id)
    )
    return list(result.scalars().all())


__all__ = ["list_unpaired_transfer_dispositions", "persist_transfer_pairs"]
