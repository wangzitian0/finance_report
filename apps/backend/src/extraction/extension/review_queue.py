"""Journal-entry creation from an atomic transaction (posting/classification seam).

Shared by extraction's statement-posting use case and by reconciliation's
explicit reviewed-disposition command. It lives in extraction because
``AtomicTransaction`` is extraction's aggregate; no caller can use it to
invent an account or an economic meaning.
"""

from collections.abc import Awaitable
from datetime import date
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import src.config
from src.audit import JournalEntrySourceType
from src.extraction.base.disposition import DispositionDecision, DispositionStatus, intent_matches_counter_account
from src.extraction.extension.currency_resolution import CurrencyUnresolvedError
from src.extraction.orm.layer1 import DocumentType, UploadedDocument
from src.extraction.orm.layer2 import AtomicTransaction, TransactionDirection
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    ValidationError,
    create_journal_entry,
    post_journal_entry,
)
from src.observability import get_logger


class FxRateProvider(Protocol):
    def __call__(
        self,
        db: AsyncSession,
        base_currency: str,
        quote_currency: str,
        rate_date: date,
        *,
        lazy_load: bool = False,
    ) -> Awaitable[Decimal]: ...


class _FxRateProviderNotRegisteredError(Exception):
    """Placeholder bound to :data:`FxRateError` before wiring.

    Never raised by anything, so a pre-wiring ``except FxRateError`` simply
    matches nothing instead of crashing on a non-exception sentinel (mirrors
    ``reporting.extension.fx_gateway``'s identical placeholder).
    """


logger = get_logger(__name__)
settings = src.config.settings

# ``extraction`` and ``pricing`` are both L3 domains; pricing's own
# repository/manual-valuation reads need extraction's published ORM entities
# (ManualValuationSnapshot, #1675 D5c), so a direct extraction -> pricing
# import here (even function-local — the package-contract gate's cycle check
# is a static AST scan, not a runtime-timing one) would make depends_on
# cyclic (extraction -> pricing -> extraction). Same inversion as
# ``reporting.extension.fx_gateway`` (#1666) and the #1675 D3 / D5c provider
# ports: the port lives here, main.py (L4) wires the real
# pricing.get_exchange_rate/PricingError at startup; tests wire it directly.
_get_exchange_rate: "FxRateProvider | None" = None

#: The injected FX-unavailable exception class (``src.pricing.PricingError``
#: today). Reference late-bound as ``review_queue.FxRateError``.
FxRateError: type[Exception] = _FxRateProviderNotRegisteredError


def register_fx_rate_provider(
    get_exchange_rate: "FxRateProvider",
    *,
    fx_rate_error: type[Exception],
) -> None:
    """Wire the FX-rate lookup (see module note above)."""
    global _get_exchange_rate, FxRateError
    _get_exchange_rate = get_exchange_rate
    FxRateError = fx_rate_error


def _require_fx_rate_provider() -> "FxRateProvider":
    if _get_exchange_rate is None:
        raise RuntimeError(
            "review_queue.register_fx_rate_provider() was never called — "
            "main.py wires it at startup (#1675 D5c); a test exercising this "
            "path must call it too."
        )
    return _get_exchange_rate


def _source_document_ids(source_documents: object) -> list[UUID]:
    """Extract source ``UploadedDocument`` ids (bank-statement sources), in order.

    Mirrors ``statement_summary._ordered_bank_statement_doc_ids``: accepts the
    canonical list form (``[{"doc_id": ..., "doc_type": ...}]``) and a
    ``{"documents": [...]}`` wrapper, keeps entries with a missing ``doc_type``,
    and skips invalid UUID strings so they never raise during query binding.
    """
    if isinstance(source_documents, dict):
        source_documents = source_documents.get("documents", [])
    if not isinstance(source_documents, list):
        return []

    bank_statement = DocumentType.BANK_STATEMENT.value
    ordered: list[UUID] = []
    seen: set[UUID] = set()
    for entry in source_documents:
        if not isinstance(entry, dict):
            continue
        doc_type = entry.get("doc_type")
        if doc_type is not None and doc_type != bank_statement:
            continue
        raw = entry.get("doc_id")
        if not raw:
            continue
        try:
            doc_id = UUID(str(raw))
        except (ValueError, TypeError):
            continue
        if doc_id not in seen:
            seen.add(doc_id)
            ordered.append(doc_id)
    return ordered


async def _resolve_statement_summary(
    db: AsyncSession,
    txn: AtomicTransaction,
    *,
    user_id: UUID,
) -> StatementSummary | None:
    """Resolve the owning ``StatementSummary`` for an atomic transaction.

    Walks ``txn.source_documents -> UploadedDocument -> StatementSummary`` and
    returns the first source document's statement summary (in source-document
    order). Returns ``None`` when no source document maps to a statement summary.
    """
    doc_ids = _source_document_ids(txn.source_documents)
    if not doc_ids:
        return None

    result = await db.execute(
        select(StatementSummary)
        .join(UploadedDocument, StatementSummary.uploaded_document_id == UploadedDocument.id)
        .where(StatementSummary.user_id == user_id)
        .where(UploadedDocument.id.in_(doc_ids))
    )
    summaries = {summary.uploaded_document_id: summary for summary in result.scalars()}
    for doc_id in doc_ids:
        summary = summaries.get(doc_id)
        if summary is not None:
            return summary
    return None


async def get_or_create_account(
    db: AsyncSession,
    *,
    name: str,
    account_type: AccountType,
    currency: str,
    user_id: UUID,
) -> Account:
    """Fetch or create a default account."""
    result = await db.execute(
        select(Account)
        .where(Account.name == name)
        .where(Account.type == account_type)
        .where(Account.currency == currency)
        .where(Account.user_id == user_id)
    )
    account = result.scalar_one_or_none()
    if account:
        return account

    account = Account(
        user_id=user_id,
        name=name,
        type=account_type,
        currency=currency,
    )
    db.add(account)
    await db.flush()
    await db.refresh(account)
    return account


async def _create_entry_from_txn(
    db: AsyncSession,
    txn: AtomicTransaction,
    *,
    user_id: UUID,
    base_currency: str | None = None,
    auto_post: bool = False,
    source_type: JournalEntrySourceType = JournalEntrySourceType.AUTO_PARSED,
    preloaded_statement: StatementSummary | None = None,
    preloaded_bank_account: Account | None = None,
    fx_rate_provider: FxRateProvider | None = None,
    fx_rate_error: type[Exception] | None = None,
    disposition: DispositionDecision | None = None,
    counter_account: Account | None = None,
) -> JournalEntry:
    """Create a journal entry from an atomic transaction.

    Uses the owning statement summary's linked account if available. Draft entries
    may still use the legacy default account, but posted entries require an explicit
    mapping. When auto_post is True, the generated entry is first persisted as
    DRAFT with its lines and then promoted to POSTED; otherwise it remains DRAFT.
    preloaded_statement/preloaded_bank_account may be passed by trusted callers
    that already loaded them for the same authenticated user context.

    The owning statement is resolved via ``txn.source_documents -> UploadedDocument
    -> StatementSummary`` (atomic transactions have no ``statement_id``).
    """
    # Validate transaction belongs to user and resolve owning statement summary.
    if txn.user_id != user_id:
        raise ValueError("Transaction does not belong to user")

    # Promotion-gate (EPIC-012 AC12.40.4): a transaction whose currency could not be
    # established at the ingest boundary is non-authoritative. It cannot become a
    # JournalLine until a reviewer specifies the currency (see resolve_transaction_currency).
    # This is the load-bearing guard that makes JournalLine.currency human-confirmed.
    if getattr(txn, "currency_unresolved", False):
        raise CurrencyUnresolvedError(
            f"Transaction {txn.id} has an unresolved currency and cannot be promoted to a "
            "journal entry. A reviewer must specify its currency first."
        )

    statement = preloaded_statement
    if statement is not None:
        # Caller must preload statement under the same authenticated user context.
        if statement.user_id != user_id:
            raise ValueError("Preloaded statement does not match transaction or user")
    else:
        statement = await _resolve_statement_summary(db, txn, user_id=user_id)

    # The transaction's own (human-confirmed at this point) currency is authoritative
    # per AC12.40; the statement currency is only a fallback, then the base SSOT. This
    # preserves a transaction-specific currency in multi-currency statements.
    base_currency = (base_currency or settings.base_currency).upper()
    currency = (txn.currency or (statement.currency if statement else None) or base_currency).upper()
    line_fx_rate: Decimal | None = None
    if currency != base_currency:
        try:
            # lazy_load=True (#1779): a date->rate fact is immutable once resolved, so
            # the on-demand chain (stored inverse -> USD-bridge derivation -> live
            # provider fetch, all persisted to fx_rates) is safe to consult here, the
            # same way reporting (_core.py) and internal transfers already opt into
            # it. Only when that chain also comes up empty does this still fail
            # closed below -- a journal entry cannot post without a real rate,
            # unlike a report line, which can just omit the value.
            provider = fx_rate_provider or _require_fx_rate_provider()
            line_fx_rate = await provider(db, currency, base_currency, txn.txn_date, lazy_load=True)
        except fx_rate_error or FxRateError as exc:
            raise ValueError(f"FX rate required to create {currency} journal entry: {exc}") from exc

    # Use statement's linked account if available.
    statement_account_id = statement.account_id if statement else None
    bank_account: Account | None = preloaded_bank_account
    if bank_account is not None:
        if bank_account.user_id != user_id:
            # Caller must preload bank account under the same authenticated user context.
            raise ValueError("Bank account does not belong to user")
        if statement_account_id and bank_account.id != statement_account_id:
            raise ValueError("Preloaded bank account does not match statement")
    elif statement_account_id:
        account_result = await db.execute(
            select(Account).where(Account.id == statement_account_id).where(Account.user_id == user_id)
        )
        bank_account = account_result.scalar_one_or_none()

    if not bank_account:
        raise ValueError("Account mapping required before statement posting")
    if bank_account.type is not AccountType.ASSET or not bank_account.is_active:
        raise ValueError("Statement posting account must be an active asset account")
    if bank_account.currency != currency:
        raise ValueError("Statement posting account currency must match the transaction currency")
    if (
        disposition is None
        or disposition.status is not DispositionStatus.AUTHORITATIVE
        or disposition.command is None
        or disposition.transaction_id != txn.id
    ):
        raise ValueError("Authoritative economic disposition is required before statement posting")
    if counter_account is None or counter_account.id != disposition.command.counter_account_id:
        raise ValueError("Disposition counter-account context is missing or mismatched")
    if counter_account.user_id != user_id or not counter_account.is_active:
        raise ValueError("Disposition counter-account must be an active account owned by the user")
    if counter_account.currency != currency:
        raise ValueError("Disposition counter-account currency must match the transaction currency")
    if not intent_matches_counter_account(disposition.intent, counter_account.type.value):
        raise ValueError("Disposition intent is incompatible with the counter-account type")
    if txn.direction == TransactionDirection.IN:
        if disposition.command.debit_role != "custody" or disposition.command.credit_role != "counter":
            raise ValueError("Disposition command conflicts with incoming transaction flow")
        debit_account = bank_account
        credit_account = counter_account
    else:
        if disposition.command.debit_role != "counter" or disposition.command.credit_role != "custody":
            raise ValueError("Disposition command conflicts with outgoing transaction flow")
        debit_account = counter_account
        credit_account = bank_account

    lines_data = [
        {
            "account_id": debit_account.id,
            "direction": Direction.DEBIT,
            "amount": txn.amount,
            "currency": currency,
            "fx_rate": line_fx_rate,
            "event_type": "bank_txn",
        },
        {
            "account_id": credit_account.id,
            "direction": Direction.CREDIT,
            "amount": txn.amount,
            "currency": currency,
            "fx_rate": line_fx_rate,
            "event_type": "bank_txn",
        },
    ]
    try:
        entry = await create_journal_entry(
            db,
            user_id,
            entry_date=txn.txn_date,
            memo=txn.description,
            lines_data=lines_data,
            source_type=source_type,
            source_id=txn.id,
            base_currency=base_currency,
        )
        if auto_post:
            entry = await post_journal_entry(
                db,
                entry.id,
                user_id,
                base_currency=base_currency,
            )
    except ValidationError as exc:
        if auto_post:
            raise ValueError(f"Generated entry violates accounting invariants: {exc}") from exc
        raise ValueError(f"Generated entry does not balance: {exc}") from exc

    # ``post_journal_entry`` returns an aggregate whose lines are not guaranteed
    # to be loaded. The evidence write and every caller need the same complete
    # entry boundary, rather than triggering unsupported async lazy loads.
    entry_result = await db.execute(
        select(JournalEntry).where(JournalEntry.id == entry.id).options(selectinload(JournalEntry.lines))
    )
    entry = entry_result.scalar_one()

    # Eager evidence-graph lineage (AtomicTransaction --posted_as--> JournalEntry
    # --contains--> JournalLine). Imported lazily to avoid an import cycle.
    # Best-effort: provenance must never break journal posting.
    try:
        from src.extraction.extension.evidence_graph_integration import EvidenceGraphIntegrationService

        await EvidenceGraphIntegrationService().record_journal_posting(
            db,
            user_id=user_id,
            atomic_transaction=txn,
            journal_entry=entry,
        )
    except Exception as evidence_exc:
        logger.warning(
            "Evidence-graph journal-posting lineage failed (posting continues)",
            extra={
                "error": str(evidence_exc),
                "error_type": type(evidence_exc).__name__,
                "user_id": str(user_id),
                "journal_entry_id": str(entry.id),
            },
        )

    return entry


async def create_entry_from_txn(
    db: AsyncSession,
    txn: AtomicTransaction,
    *,
    user_id: UUID,
    base_currency: str | None = None,
    auto_post: bool = False,
    source_type: JournalEntrySourceType = JournalEntrySourceType.AUTO_PARSED,
    preloaded_statement: StatementSummary | None = None,
    preloaded_bank_account: Account | None = None,
    fx_rate_provider: FxRateProvider | None = None,
    fx_rate_error: type[Exception] | None = None,
    disposition: DispositionDecision | None = None,
    counter_account: Account | None = None,
) -> JournalEntry:
    """Create a journal entry, atomically including all auto-post side effects."""

    async def create() -> JournalEntry:
        return await _create_entry_from_txn(
            db,
            txn,
            user_id=user_id,
            base_currency=base_currency,
            auto_post=auto_post,
            source_type=source_type,
            preloaded_statement=preloaded_statement,
            preloaded_bank_account=preloaded_bank_account,
            fx_rate_provider=fx_rate_provider,
            fx_rate_error=fx_rate_error,
            disposition=disposition,
            counter_account=counter_account,
        )

    if auto_post:
        async with db.begin_nested():
            return await create()
    return await create()
