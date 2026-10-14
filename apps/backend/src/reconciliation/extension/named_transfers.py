"""Transfer legs for rows that the AI classification named a movement between own accounts (#2415).

The keyword fallback of the reconciliation run posts a Processing leg only when the description holds
a transfer keyword. The AI classification also names a wallet payment or a card repayment, and those
descriptions often hold no keyword. A statement with such a row stays in review, because posting is
all or nothing per statement.

``post_named_transfer_legs`` posts the same leg for those rows. The legs carry the normalized anchors, so
the next reconciliation run pairs them with the other side of the movement and clears the Processing
account. The function does not pair: pairing is quadratic in the number of legs of the user, and it only
labels legs without changing the balance.

The Processing account holds the effective base currency (``common/ledger/readme.md``). A row in
another currency waits for a person. The function checks this before any ledger call, so a row
that a pre-check skips never creates the Processing account.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
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
    """A statement transaction that an earlier step named a movement between own accounts.

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

    A transaction is skipped, without an error and without a ledger effect, when it already has a live
    match (pending or accepted; a rejected or superseded match is history), when its statement has no
    linked account, when its currency is not the effective base currency, or when the Processing account
    of the user holds another currency. The caller owns the database transaction.

    The match is ``accepted`` because a person asked for it. Its score is the AI score, and its
    breakdown records the class that the AI named. When the user chose the class, the score is 100 and
    the breakdown says so. Each leg has its own savepoint, so a failure in one leg leaves the others.
    """
    repo = repository if repository is not None else SqlReconciliationRepository(db)
    base_currency = (await get_effective_base_currency(db)).upper()
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
        custody_account_id = await resolve_custody_account_id(db, txn)
        if custody_account_id is None:
            logger.info("Named transfer skipped: the statement has no linked account", txn_id=str(txn.id))
            continue
        custody = await db.get(Account, custody_account_id)
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
                    custody_account_id=custody_account_id,
                    status=ReconciliationStatus.ACCEPTED,
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
