"""Transfer legs for AI-classified movements between own accounts (#2415)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.config_app import get_effective_base_currency
from src.extraction.extension.statement_summary import resolve_custody_account_id
from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import (
    Account,
    ProcessingCurrencyConflictError,
    TransferAccountCurrencyMismatchError,
    find_processing_account,
)
from src.observability import get_logger
from src.reconciliation.base.repository import ReconciliationRepository
from src.reconciliation.extension.matching import sync_reconciliation_matches_journal_entry_links_batch
from src.reconciliation.extension.phases.transfer_detection import post_transfer_leg
from src.reconciliation.extension.repository import SqlReconciliationRepository
from src.reconciliation.orm.reconciliation import ReconciliationMatch, ReconciliationStatus

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class NamedTransfer:
    """Statement transaction named as an own-account transfer."""

    transaction: AtomicTransaction
    category: str
    score: int
    decided_by_user: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.score <= 100:
            raise ValueError("score must be between 0 and 100")


async def post_named_transfer_legs(
    db: AsyncSession,
    *,
    user_id: UUID,
    named: Sequence[NamedTransfer],
    repository: ReconciliationRepository | None = None,
    accepted_by: Literal["user", "system"] = "user",
) -> list[ReconciliationMatch]:
    """Post a Processing leg for each eligible named transfer transaction."""
    repo = repository if repository is not None else SqlReconciliationRepository(db)
    base_currency = (await get_effective_base_currency(db, user_id=user_id)).upper()
    processing = await find_processing_account(db, user_id)
    if processing is not None and processing.currency.upper() != base_currency:
        logger.info(
            "Named transfers skipped: the Processing account holds another currency",
            processing_currency=processing.currency,
            base_currency=base_currency,
        )
        return []

    matches: list[ReconciliationMatch] = []
    for item in named:
        txn = item.transaction
        if await repo.claim_transaction_for_decision(txn.id) is not None:
            continue
        if (txn.currency or "").upper() != base_currency:
            logger.info("Named transfer skipped: the row is not in the base currency", txn_id=str(txn.id))
            continue
        custody_id = await resolve_custody_account_id(db, txn)
        if custody_id is None:
            logger.info("Named transfer skipped: the statement has no linked account", txn_id=str(txn.id))
            continue
        custody = await db.get(Account, custody_id)
        if custody is None or custody.user_id != user_id or custody.currency.upper() != base_currency:
            logger.info("Named transfer skipped: the linked account is not in the base currency", txn_id=str(txn.id))
            continue
        try:
            async with db.begin_nested():
                match = await post_transfer_leg(
                    db,
                    repository=repo,
                    user_id=user_id,
                    txn=txn,
                    custody_account_id=custody_id,
                    status=ReconciliationStatus.ACCEPTED
                    if accepted_by == "user" or item.decided_by_user
                    else ReconciliationStatus.AUTO_ACCEPTED,
                    match_score=100 if item.decided_by_user else item.score,
                    extra_breakdown=(
                        {"user_category": item.category}
                        if item.decided_by_user
                        else {"ai_category": item.category, "ai_score": float(item.score)}
                    ),
                )
        except (ProcessingCurrencyConflictError, TransferAccountCurrencyMismatchError) as exc:
            logger.info("Named transfer skipped: the ledger refused the currency", txn_id=str(txn.id), error=str(exc))
            continue
        matches.append(match)
    if matches:
        await db.flush()
        await sync_reconciliation_matches_journal_entry_links_batch(db, matches, user_id=user_id)
    return matches
