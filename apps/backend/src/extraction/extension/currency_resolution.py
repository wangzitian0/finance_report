"""Ingest-boundary currency resolution (EPIC-012 AC12.40, #1341).

Phase E of the currency strong-type invariant. A transaction's currency must be
established **at the ingest boundary**, never silent-defaulted:

* **AC12.40.1** — when the currency is determinable (statement metadata / linked
  account), attach it explicitly.
* **AC12.40.2** — when it is unknown/ambiguous, flag the row ``currency_unresolved``
  and route it to human review; it cannot be promoted to a ``JournalLine``.
* **AC12.40.3** — a reviewer specifies the currency (ISO-4217 validated via
  ``src.audit.money.Currency``); the resolution is audited (who / when / chosen value).
* **AC12.40.4** — the promotion gate blocks ``currency_unresolved`` items (enforced
  in ``review_queue.create_entry_from_txn``).

This module owns the *decision*: it is dependency-light (kernel ``src.audit.money`` +
models only) so both the ingest path (``deduplication``) and the review path
(``review_queue`` / routers) reuse the same rule without an import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.money import Currency, InvalidCurrencyError
from src.extraction.orm.layer2 import AtomicTransaction
from src.observability import get_logger
from src.platform import BaseAppException

logger = get_logger(__name__)

__all__ = [
    "UNRESOLVED_PLACEHOLDER",
    "CurrencyUnresolvedError",
    "ResolvedCurrency",
    "resolve_ingest_currency",
    "resolve_transaction_currency",
]


class CurrencyUnresolvedError(BaseAppException, ValueError):
    """A transaction whose currency was never human-confirmed was promoted.

    Subclasses ``BaseAppException`` so the global handler returns a structured 409
    to API callers (the promotion routers don't catch ``ValueError``), and
    ``ValueError`` so existing ``except ValueError`` callers still match.
    """

    def __init__(self, message: str) -> None:
        super().__init__(error_id="currency_unresolved", message=message, status_code=409)


@dataclass(frozen=True)
class ResolvedCurrency:
    """Outcome of resolving a transaction's currency at the ingest boundary.

    ``code`` is always a stored placeholder; when ``unresolved`` is True it is a
    non-authoritative fallback that MUST NOT be trusted until a reviewer specifies
    the real currency.
    """

    code: str
    unresolved: bool


# Non-authoritative placeholder stored in the ``currency`` NOT NULL column while a
# row is flagged ``currency_unresolved``. It is never trusted: the flag gates
# promotion, and a reviewer overwrites this on resolution. ``XXX`` is the ISO-4217
# code for "no currency" and is deliberately NOT in this project's active currency
# set, so ``Currency("XXX")`` raises — a placeholder can never masquerade as a
# real, resolved currency.
UNRESOLVED_PLACEHOLDER = "XXX"


def resolve_ingest_currency(
    *candidates: str | None,
) -> ResolvedCurrency:
    """Decide a transaction's currency from ingest-boundary candidates, in priority order.

    Returns the first candidate that is a valid ISO-4217 code (e.g. the parsed
    transaction currency, then the linked statement currency). When no candidate is
    a valid code, returns the ``XXX`` placeholder flagged ``unresolved`` instead of
    silently defaulting to the base currency — the row is then routed to human
    review (AC12.40.2).
    """
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            return ResolvedCurrency(code=Currency.of(candidate).code, unresolved=False)
        except InvalidCurrencyError:
            continue
    return ResolvedCurrency(code=UNRESOLVED_PLACEHOLDER, unresolved=True)


async def resolve_transaction_currency(
    db: AsyncSession,
    txn_id: UUID,
    *,
    user_id: UUID,
    currency: str,
) -> AtomicTransaction:
    """Reviewer specifies the currency for a ``currency_unresolved`` transaction (AC12.40.3).

    Validates ``currency`` as an ISO-4217 code via ``src.audit.money.Currency``, writes it
    to the row, clears the ``currency_unresolved`` flag, and records the resolution
    audit (who / when). After this the promotion gate (AC12.40.4) lets the row
    become a ``JournalLine``.

    Raises:
        ValueError: the transaction does not exist / belong to the user.
        InvalidCurrencyError: ``currency`` is not a valid ISO-4217 code.
    """
    result = await db.execute(
        select(AtomicTransaction).where(AtomicTransaction.id == txn_id).where(AtomicTransaction.user_id == user_id)
    )
    txn = result.scalar_one_or_none()
    if txn is None:
        raise ValueError("Transaction not found")

    # ISO-4217 validation is the single gate; an invalid code raises and nothing is written.
    resolved = Currency.of(currency).code

    txn.currency = resolved
    txn.currency_unresolved = False
    txn.currency_resolved_by = user_id
    txn.currency_resolved_at = datetime.now(UTC)
    await db.flush()

    logger.info(
        "currency.resolved",
        audit_event="currency.resolved",
        atomic_txn_id=str(txn.id),
        resolved_currency=resolved,
        resolved_by=str(user_id),
    )
    return txn
