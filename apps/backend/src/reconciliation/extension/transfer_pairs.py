"""Persistence for reconciliation-owned transfer-pair decisions."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import Currency, InvalidCurrencyError
from src.extraction.orm.layer2 import AtomicTransaction, TransactionDirection
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
    """A candidate violates the reconciliation transfer-pair aggregate."""


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
                AtomicTransaction.user_id,
                AtomicTransaction.direction,
                AtomicTransaction.currency,
            )
            .join(
                ReconciliationMatch,
                ReconciliationMatch.id == ReconciliationMatchJournalEntry.match_id,
            )
            .join(
                AtomicTransaction,
                AtomicTransaction.id == ReconciliationMatch.atomic_txn_id,
            )
            .where(
                ReconciliationMatchJournalEntry.journal_entry_id.in_(entry_ids),
                ReconciliationMatch.disposition_kind == DispositionKind.TRANSFER_LEG,
                ReconciliationMatch.status != ReconciliationStatus.SUPERSEDED,
                ReconciliationMatch.superseded_by_id.is_(None),
            )
        )
    ).all()
    disposition_by_entry = {
        entry_id: (disposition, txn_user_id, direction, currency)
        for entry_id, disposition, txn_user_id, direction, currency in rows
    }
    persisted: list[ReconciliationTransferPair] = []
    for pair in pairs:
        out_leg = disposition_by_entry.get(pair.out_entry.id)
        in_leg = disposition_by_entry.get(pair.in_entry.id)
        if out_leg is None or in_leg is None:
            continue
        out_disposition, out_user_id, out_direction, out_currency = out_leg
        in_disposition, in_user_id, in_direction, in_currency = in_leg
        try:
            out_currency_code = Currency.of(out_currency).code
            in_currency_code = Currency.of(in_currency).code
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


__all__ = ["InvalidTransferPairError", "list_unpaired_transfer_dispositions", "persist_transfer_pairs"]
