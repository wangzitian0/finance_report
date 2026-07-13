"""Journal-entry creation from an atomic transaction (posting/classification seam).

Shared by extraction's own posting/classification call sites and by
reconciliation's review queue (``src.reconciliation.extension.review_queue``),
which posts the entry a match is accepted against. Lives in extraction because
``AtomicTransaction`` is extraction's aggregate; reconciliation depends on
extraction (never the reverse), so the accept/reject/batch review-queue
operations that also need ``entry_total_amount`` /
``sync_reconciliation_match_journal_entry_links`` live in reconciliation
instead, calling back into ``create_entry_from_txn`` here.
"""

from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import src.config
from src.audit import JournalEntrySourceType, normalize_source_type
from src.extraction.extension.currency_resolution import CurrencyUnresolvedError
from src.extraction.orm.layer1 import DocumentType, UploadedDocument
from src.extraction.orm.layer2 import AtomicTransaction, TransactionDirection
from src.extraction.orm.layer3 import ClassificationStatus, TransactionClassification
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    ValidationError,
    validate_journal_balance,
    validate_journal_posting_invariants,
)
from src.observability import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


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
_get_exchange_rate: "Callable[..., Awaitable[Decimal]] | None" = None

#: The injected FX-unavailable exception class (``src.pricing.PricingError``
#: today). Reference late-bound as ``review_queue.FxRateError``.
FxRateError: type[Exception] = _FxRateProviderNotRegisteredError


def register_fx_rate_provider(
    get_exchange_rate: "Callable[..., Awaitable[Decimal]]",
    *,
    fx_rate_error: type[Exception],
) -> None:
    """Wire the FX-rate lookup (see module note above)."""
    global _get_exchange_rate, FxRateError
    _get_exchange_rate = get_exchange_rate
    FxRateError = fx_rate_error


def _require_fx_rate_provider() -> "Callable[..., Awaitable[Decimal]]":
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


async def create_entry_from_txn(
    db: AsyncSession,
    txn: AtomicTransaction,
    *,
    user_id: UUID,
    auto_post: bool = False,
    source_type: JournalEntrySourceType = JournalEntrySourceType.AUTO_PARSED,
    preloaded_statement: StatementSummary | None = None,
    preloaded_bank_account: Account | None = None,
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
    currency = (txn.currency or (statement.currency if statement else None) or settings.base_currency).upper()
    base_currency = settings.base_currency.upper()
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
            line_fx_rate = await _require_fx_rate_provider()(db, currency, base_currency, txn.txn_date, lazy_load=True)
        except FxRateError as exc:
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

    if not bank_account and auto_post:
        raise ValueError("Account mapping required before posting. Confirm the statement account before posting.")

    if not bank_account:
        # Fallback: create or get default bank account
        bank_account = await get_or_create_account(
            db,
            name="Bank - Main",
            account_type=AccountType.ASSET,
            currency=currency,
            user_id=user_id,
        )

    classified_account: Account | None = None
    classification_result = await db.execute(
        select(TransactionClassification)
        .where(TransactionClassification.atomic_txn_id == txn.id)
        .where(TransactionClassification.status == ClassificationStatus.APPLIED)
        .order_by(TransactionClassification.created_at.desc())
    )
    classification = classification_result.scalar_one_or_none()
    if classification and classification.account_id:
        account_result = await db.execute(select(Account).where(Account.id == classification.account_id))
        classified_account = account_result.scalar_one_or_none()

    if txn.direction == TransactionDirection.IN:
        if classified_account and classified_account.type == AccountType.INCOME:
            counter_account = classified_account
        else:
            counter_account = await get_or_create_account(
                db,
                name="Income - Uncategorized",
                account_type=AccountType.INCOME,
                currency=currency,
                user_id=user_id,
            )
        debit_account = bank_account
        credit_account = counter_account
    else:
        if classified_account and classified_account.type == AccountType.EXPENSE:
            counter_account = classified_account
        else:
            counter_account = await get_or_create_account(
                db,
                name="Expense - Uncategorized",
                account_type=AccountType.EXPENSE,
                currency=currency,
                user_id=user_id,
            )
        debit_account = counter_account
        credit_account = bank_account

    entry = JournalEntry(
        user_id=user_id,
        entry_date=txn.txn_date,
        memo=txn.description,
        source_type=normalize_source_type(source_type),
        source_id=txn.id,
        status=JournalEntryStatus.DRAFT,
    )

    entry.lines.append(
        JournalLine(
            account=debit_account,
            direction=Direction.DEBIT,
            amount=txn.amount,
            currency=currency,
            fx_rate=line_fx_rate,
            event_type="bank_txn",
        )
    )
    entry.lines.append(
        JournalLine(
            account=credit_account,
            direction=Direction.CREDIT,
            amount=txn.amount,
            currency=currency,
            fx_rate=line_fx_rate,
            event_type="bank_txn",
        )
    )

    try:
        if auto_post:
            validate_journal_posting_invariants(entry)
        else:
            validate_journal_balance(entry.lines)
    except ValidationError as exc:
        if not auto_post:
            raise ValueError(f"Generated entry does not balance: {exc}") from exc
        raise ValueError(f"Generated entry violates accounting invariants: {exc}") from exc

    db.add(entry)
    await db.flush()
    if auto_post:
        entry.status = JournalEntryStatus.POSTED
        await db.flush()
    await db.refresh(entry, ["lines"])

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
