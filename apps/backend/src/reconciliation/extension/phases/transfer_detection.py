"""Transfer-detection phase for reconciliation matching."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.extension.statement_summary import resolve_custody_account_id
from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import (
    JournalEntryStatus,
    ValidationError,
    create_transfer_in_entry,
    create_transfer_out_entry,
    detect_transfer_pattern,
)
from src.observability import get_logger
from src.reconciliation.base import ReconciliationRepository
from src.reconciliation.orm.reconciliation import ReconciliationMatch, ReconciliationStatus

logger = get_logger(__name__)


async def run_transfer_detection_phase(
    db: AsyncSession,
    *,
    transactions: list[AtomicTransaction],
    matched_txn_ids: set[UUID],
    repository: ReconciliationRepository,
    user_id: UUID,
    currency: str,
) -> list[ReconciliationMatch]:
    """Detect and materialize transfer matches before normal scoring."""
    created_matches: list[ReconciliationMatch] = []
    for txn in transactions:
        if txn.id in matched_txn_ids:
            continue

        if not detect_transfer_pattern(txn.description):
            continue

        try:
            existing_transfer_match = await repository.get_active_match(txn.id)
            if existing_transfer_match:
                logger.warning(
                    "Transfer already matched - skipping duplicate match creation",
                    txn_id=str(txn.id),
                    existing_match_id=str(existing_transfer_match.id),
                )
                matched_txn_ids.add(txn.id)
                continue

            source_account_id = await resolve_custody_account_id(db, txn)
            if source_account_id is None:
                logger.warning(
                    "Transfer detected but source statement has no linked account - skipping Processing entry",
                    txn_id=str(txn.id),
                )
                continue

            if txn.direction == "OUT":
                transfer_entry = await create_transfer_out_entry(
                    db=db,
                    user_id=user_id,
                    source_account_id=source_account_id,
                    amount=txn.amount,
                    txn_date=txn.txn_date,
                    description=txn.description,
                    currency=currency,
                )
                matched_txn_ids.add(txn.id)
                match = ReconciliationMatch(
                    atomic_txn_id=txn.id,
                    journal_entry_ids=[str(transfer_entry.id)],
                    match_score=100,
                    score_breakdown={"transfer_out": 100.0},
                    status=ReconciliationStatus.AUTO_ACCEPTED,
                )
                await repository.add_match(match)
                created_matches.append(match)
                if transfer_entry.status != JournalEntryStatus.VOID:
                    transfer_entry.status = JournalEntryStatus.RECONCILED
                logger.info(
                    "Transfer OUT detected and Processing entry created",
                    txn_id=str(txn.id),
                    entry_id=str(transfer_entry.id),
                    amount=str(txn.amount),
                )
            elif txn.direction == "IN":
                transfer_entry = await create_transfer_in_entry(
                    db=db,
                    user_id=user_id,
                    dest_account_id=source_account_id,
                    amount=txn.amount,
                    txn_date=txn.txn_date,
                    description=txn.description,
                    currency=currency,
                )
                matched_txn_ids.add(txn.id)
                match = ReconciliationMatch(
                    atomic_txn_id=txn.id,
                    journal_entry_ids=[str(transfer_entry.id)],
                    match_score=100,
                    score_breakdown={"transfer_in": 100.0},
                    status=ReconciliationStatus.AUTO_ACCEPTED,
                )
                await repository.add_match(match)
                created_matches.append(match)
                if transfer_entry.status != JournalEntryStatus.VOID:
                    transfer_entry.status = JournalEntryStatus.RECONCILED
                logger.info(
                    "Transfer IN detected and Processing entry created",
                    txn_id=str(txn.id),
                    entry_id=str(transfer_entry.id),
                    amount=str(txn.amount),
                )
        except ValidationError:
            raise
        except Exception as e:
            logger.error(
                "Failed to create Processing account entry for transfer",
                txn_id=str(txn.id),
                direction=txn.direction,
                error=str(e),
            )
    return created_matches
