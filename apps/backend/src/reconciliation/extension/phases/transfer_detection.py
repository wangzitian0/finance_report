"""Transfer-detection phase for reconciliation matching."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.config_app import get_effective_base_currency
from src.extraction.extension.statement_summary import resolve_custody_account_id
from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import (
    JournalEntryStatus,
    ProcessingCurrencyConflictError,
    TransferAccountCurrencyMismatchError,
    create_transfer_in_entry,
    create_transfer_out_entry,
    detect_transfer_pattern,
)
from src.observability import get_logger
from src.reconciliation.base import ReconciliationRepository
from src.reconciliation.orm.reconciliation import DispositionKind, ReconciliationMatch, ReconciliationStatus

logger = get_logger(__name__)


async def run_transfer_detection_phase(
    db: AsyncSession,
    *,
    transactions: list[AtomicTransaction],
    matched_txn_ids: set[UUID],
    repository: ReconciliationRepository,
    user_id: UUID,
) -> list[ReconciliationMatch]:
    """Materialize transfer fallback only after normal candidates are exhausted."""
    created_matches: list[ReconciliationMatch] = []
    base_currency: str | None = None
    for txn in transactions:
        if txn.id in matched_txn_ids or not detect_transfer_pattern(txn.description):
            continue
        if base_currency is None:
            base_currency = (await get_effective_base_currency(db, user_id=user_id)).upper()
        if (txn.currency or "").upper() != base_currency:
            logger.info(
                "Transfer detected in another currency - skipping Processing entry",
                txn_id=str(txn.id),
                txn_currency=txn.currency,
                base_currency=base_currency,
            )
            continue

        try:
            existing = await repository.claim_transaction(txn.id)
            if existing:
                logger.warning(
                    "Transfer already matched - skipping duplicate match creation",
                    txn_id=str(txn.id),
                    existing_match_id=str(existing.id),
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

            if txn.direction in ("OUT", "IN"):
                match = await post_transfer_leg(
                    db,
                    repository=repository,
                    user_id=user_id,
                    txn=txn,
                    custody_account_id=source_account_id,
                    status=ReconciliationStatus.AUTO_ACCEPTED,
                    match_score=100,
                )
                matched_txn_ids.add(txn.id)
                created_matches.append(match)
        except ProcessingCurrencyConflictError:
            raise
        except TransferAccountCurrencyMismatchError as exc:
            logger.info(
                "Transfer candidate requires an FX-aware posting path",
                txn_id=str(txn.id),
                direction=txn.direction,
                error=str(exc),
            )
        except Exception as exc:
            logger.exception(
                "Transfer detection failed; propagating to transaction owner",
                txn_id=str(txn.id),
                direction=txn.direction,
                error=str(exc),
            )
            raise
    if created_matches:
        logger.info("Transfer detection phase finished", created_matches_count=len(created_matches), user_id=str(user_id))
    return created_matches


async def post_transfer_leg(
    db: AsyncSession,
    *,
    repository: ReconciliationRepository,
    user_id: UUID,
    txn: AtomicTransaction,
    custody_account_id: UUID,
    status: ReconciliationStatus,
    match_score: int,
    extra_breakdown: dict[str, float | str] | None = None,
) -> ReconciliationMatch:
    """Post one Processing leg for a statement transaction and record it as a transfer-leg match."""
    is_out = txn.direction == "OUT"
    leg_key = "transfer_out" if is_out else "transfer_in"
    transfer_entry = (
        await create_transfer_out_entry(
            db, user_id, custody_account_id, txn.amount, txn.txn_date, txn.description, currency=txn.currency, source_id=txn.id
        )
        if is_out
        else await create_transfer_in_entry(
            db, user_id, custody_account_id, txn.amount, txn.txn_date, txn.description, currency=txn.currency, source_id=txn.id
        )
    )
    match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(transfer_entry.id)],
        match_score=match_score,
        score_breakdown={leg_key: 100.0, **(extra_breakdown or {})},
        status=status,
        disposition_kind=DispositionKind.TRANSFER_LEG,
    )
    await repository.add_match(match)
    if transfer_entry.status != JournalEntryStatus.VOID:
        transfer_entry.status = JournalEntryStatus.RECONCILED
    return match
