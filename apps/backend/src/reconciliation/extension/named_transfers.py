"""Transfer legs for rows that the AI classification named a movement between accounts (#2415).

The keyword fallback of the reconciliation run posts a Processing leg only when the description holds
a transfer keyword. The AI classification also names a wallet payment, a card repayment, a loan payment
or a trade, and those descriptions often hold no keyword. A statement with such a row stays in review,
because posting is all or nothing per statement.

``post_named_transfer_legs`` posts the same leg for those rows. The leg joins the same pairing as the
keyword legs, so the other side of the transfer clears the Processing account when it arrives.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.config_app import get_effective_base_currency
from src.extraction.extension.statement_summary import resolve_custody_account_id
from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import ProcessingCurrencyConflictError, TransferAccountCurrencyMismatchError
from src.observability import get_logger
from src.reconciliation.base.repository import ReconciliationRepository
from src.reconciliation.extension.matching import (
    pair_transfer_legs,
    sync_reconciliation_matches_journal_entry_links_batch,
)
from src.reconciliation.extension.phases.transfer_detection import post_transfer_leg
from src.reconciliation.extension.repository import SqlReconciliationRepository
from src.reconciliation.orm.reconciliation import ReconciliationMatch, ReconciliationStatus

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class NamedTransfer:
    """A statement transaction that an earlier step named a movement between accounts.

    ``category`` is the class that the AI named (for example ``CARD_REPAYMENT``). ``score`` is its
    confidence from 0 to 100. When ``decided_by_user`` is true, the user chose the class, and the AI
    score does not describe it.
    """

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
) -> list[ReconciliationMatch]:
    """Post a Processing leg for each named transaction and return the matches that it created.

    A transaction is skipped, without an error, when it already has a live match, when its statement
    has no linked account, or when its currency does not fit the Processing account (one currency per
    user). The caller owns the database transaction.

    The match is ``accepted`` because a person asked for it. Its score is the AI score, and its
    breakdown records the class that the AI named. When the user chose the class, the score is 100 and
    the breakdown says so.
    """
    repo = repository if repository is not None else SqlReconciliationRepository(db)
    matches: list[ReconciliationMatch] = []
    for item in named:
        txn = item.transaction
        if await repo.claim_transaction(txn.id) is not None:
            continue
        custody_account_id = await resolve_custody_account_id(db, txn)
        if custody_account_id is None:
            logger.info("Named transfer skipped: the statement has no linked account", txn_id=str(txn.id))
            continue
        try:
            matches.append(
                await post_transfer_leg(
                    db,
                    repository=repo,
                    user_id=user_id,
                    txn=txn,
                    custody_account_id=custody_account_id,
                    status=ReconciliationStatus.ACCEPTED,
                    match_score=100 if item.decided_by_user else item.score,
                    extra_breakdown=(
                        {"user_category": item.category}
                        if item.decided_by_user
                        else {"ai_category": item.category, "ai_score": float(item.score)}
                    ),
                )
            )
        except (ProcessingCurrencyConflictError, TransferAccountCurrencyMismatchError) as exc:
            logger.info(
                "Named transfer skipped: the currency does not fit the Processing account",
                txn_id=str(txn.id),
                error=str(exc),
            )
    if matches:
        await db.flush()
        await sync_reconciliation_matches_journal_entry_links_batch(db, matches, user_id=user_id)
        await pair_transfer_legs(db, user_id=user_id, currency=await get_effective_base_currency(db))
    return matches
