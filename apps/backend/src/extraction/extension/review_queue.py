"""Journal-entry creation from an atomic transaction (posting/classification seam).

Shared by extraction's statement-posting use case and by reconciliation's
explicit reviewed-disposition command. It lives in extraction because
``AtomicTransaction`` is extraction's aggregate; no caller can use it to
invent an account or an economic meaning.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.audit import JournalEntrySourceType, TraceEmitter, TraceRecord
from src.config_app import get_effective_base_currency
from src.extraction.base.disposition import DispositionDecision, DispositionStatus, intent_matches_counter_account
from src.extraction.base.source_vocabulary import DocumentType, TransactionDirection
from src.extraction.base.types import extract_source_document_ids
from src.extraction.extension.currency_resolution import CurrencyUnresolvedError
from src.extraction.extension.disposition_trace import (
    FinancialCommandRequest,
    authorize_financial_command,
    authorize_financial_commands_many,
)
from src.extraction.orm.layer1 import UploadedDocument
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import (
    PROCESSING_ACCOUNT_CODE,
    Account,
    AccountType,
    AnchoredJournalCommand,
    DecisionAnchor,
    Direction,
    JournalEntry,
    ValidationError,
    account_service,
    fit_journal_memo,
    submit_anchored_journal_entries,
    submit_anchored_journal_entry,
)
from src.observability import get_logger
from src.pricing import ExchangeRateLookup, PricingError, get_exchange_rate

logger = get_logger(__name__)


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
    doc_ids = extract_source_document_ids(txn.source_documents, doc_type=DocumentType.BANK_STATEMENT.value)
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
    """Fetch or create a default account.

    The classifier and the one-click approval both resolve their default accounts here. An inactive account is
    not the default, because posting refuses it. Two active rows with one name (a race of an older release)
    resolve to the oldest one, not to an error. The creation commits in its own short transaction
    (``find_or_create_account``), so several workers of one user never create two rows and never wait for each
    other (#2415).
    """
    cache = db.info.setdefault("_default_account_cache", {})
    cache_key = (user_id, name, account_type, currency)
    if cache_key in cache:
        return cache[cache_key]

    async def find(session: AsyncSession) -> Account | None:
        result = await session.execute(
            select(Account)
            .where(Account.name == name)
            .where(Account.type == account_type)
            .where(Account.currency == currency)
            .where(Account.user_id == user_id)
            .where(Account.is_active.is_(True))
            .order_by(Account.created_at, Account.id)
            .limit(2)
        )
        accounts = list(result.scalars().all())
        if len(accounts) > 1:
            # A race of an older release. The oldest account is the one that every request uses from now on.
            logger.error(
                "A user holds more than one default account with one name; the oldest is used",
                user_id=str(user_id),
                account_name=name,
                account_ids=[str(account.id) for account in accounts],
            )
        return accounts[0] if accounts else None

    account = await account_service.find_or_create_account(
        db,
        user_id=user_id,
        find=find,
        build=lambda: Account(user_id=user_id, name=name, type=account_type, currency=currency),
    )
    cache[cache_key] = account
    return account


@dataclass(frozen=True, slots=True)
class PlannedEntryCommand:
    """The validated journal command of one transaction, before the decision anchor exists."""

    txn: AtomicTransaction
    lines_data: list[dict]
    memo: str
    base_currency: str
    source_type: JournalEntrySourceType
    auto_post: bool


async def _plan_entry_command(
    db: AsyncSession,
    txn: AtomicTransaction,
    *,
    user_id: UUID,
    base_currency: str | None = None,
    auto_post: bool = False,
    source_type: JournalEntrySourceType = JournalEntrySourceType.AUTO_PARSED,
    preloaded_statement: StatementSummary | None = None,
    preloaded_bank_account: Account | None = None,
    fx_rate_provider: ExchangeRateLookup | None = None,
    fx_rate_error: type[Exception] | None = None,
    disposition: DispositionDecision | None = None,
    counter_account: Account | None = None,
) -> PlannedEntryCommand:
    """Validate a transaction and its disposition, then build the journal command lines.

    Uses the owning statement summary's linked account if available. Draft entries
    may still use the legacy default account, but posted entries require an explicit
    mapping. preloaded_statement/preloaded_bank_account may be passed by trusted callers
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

    base_currency = (base_currency or await get_effective_base_currency(db, user_id=user_id)).upper()
    currency = (txn.currency or (statement.currency if statement else None) or base_currency).upper()
    line_fx_rate: Decimal | None = None
    if currency != base_currency:
        try:
            provider = fx_rate_provider or get_exchange_rate
            line_fx_rate = await provider(db, currency, base_currency, txn.txn_date, lazy_load=True)
        except fx_rate_error or PricingError as exc:
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
    if bank_account.code == PROCESSING_ACCOUNT_CODE:
        raise ValueError(
            f"Statement posting cannot use Processing account ({PROCESSING_ACCOUNT_CODE}) as bank account; "
            "external transactions must stage via AtomicTransaction"
        )
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
    if counter_account.code == PROCESSING_ACCOUNT_CODE:
        raise ValueError(
            f"Statement posting cannot use Processing account ({PROCESSING_ACCOUNT_CODE}) as counter account; "
            "external transactions must stage via AtomicTransaction"
        )
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
    if disposition.category:
        for line in lines_data:
            if line["account_id"] == counter_account.id:
                line["tags"] = {"economic_category": disposition.category}
    # The description has no length limit, but the memo column does. Cut it once:
    # the decision anchor and the command must hold the same memo.
    return PlannedEntryCommand(
        txn=txn,
        lines_data=lines_data,
        memo=fit_journal_memo(txn.description),
        base_currency=base_currency,
        source_type=source_type,
        auto_post=auto_post,
    )


def _journal_command(plan: PlannedEntryCommand, decision_anchor: DecisionAnchor) -> AnchoredJournalCommand:
    return AnchoredJournalCommand.from_mappings(
        entry_date=plan.txn.txn_date,
        memo=plan.memo,
        lines_data=plan.lines_data,
        base_currency=plan.base_currency,
        source_type=plan.source_type,
        source_id=plan.txn.id,
        source_identity=f"statement-transaction:{plan.txn.id}",
        decision_anchor=decision_anchor,
        post_immediately=plan.auto_post,
    )


def _posting_error(plan: PlannedEntryCommand, exc: ValidationError) -> ValueError:
    if plan.auto_post:
        return ValueError(f"Generated entry violates accounting invariants: {exc}")
    return ValueError(f"Generated entry does not balance: {exc}")


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
    fx_rate_provider: ExchangeRateLookup | None = None,
    fx_rate_error: type[Exception] | None = None,
    disposition: DispositionDecision | None = None,
    counter_account: Account | None = None,
    source_decision: TraceRecord | None = None,
    trace_emitter: TraceEmitter | None = None,
    record_evidence: bool = True,
) -> JournalEntry:
    """Create a journal entry from an atomic transaction.

    When auto_post is True, the generated entry is first persisted as DRAFT with its lines
    and then promoted to POSTED; otherwise it remains DRAFT. ``_plan_entry_command`` states
    which account, currency and disposition checks run before the entry exists.
    """
    plan = await _plan_entry_command(
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
    try:
        if source_decision is None or trace_emitter is None:
            raise ValueError("Statement posting requires a source-owned authoritative decision")
        decision_anchor = await authorize_financial_command(
            emitter=trace_emitter,
            user_id=user_id,
            upstream_decision=source_decision,
            entry_date=txn.txn_date,
            memo=plan.memo,
            lines_data=plan.lines_data,
            base_currency=plan.base_currency,
            source_id=txn.id,
        )
        entry = await submit_anchored_journal_entry(
            db,
            user_id=user_id,
            command=_journal_command(plan, decision_anchor),
            base_currency=plan.base_currency,
            trace_repository=trace_emitter.repository,
        )
    except ValidationError as exc:
        raise _posting_error(plan, exc) from exc

    # ``post_journal_entry`` returns an aggregate whose lines are not guaranteed
    # to be loaded. The evidence write and every caller need the same complete
    # entry boundary, rather than triggering unsupported async lazy loads.
    entry_result = await db.execute(
        select(JournalEntry).where(JournalEntry.id == entry.id).options(selectinload(JournalEntry.lines))
    )
    entry = entry_result.scalar_one()

    if record_evidence:
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
    fx_rate_provider: ExchangeRateLookup | None = None,
    fx_rate_error: type[Exception] | None = None,
    disposition: DispositionDecision | None = None,
    counter_account: Account | None = None,
    source_decision: TraceRecord | None = None,
    trace_emitter: TraceEmitter | None = None,
    record_evidence: bool = True,
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
            source_decision=source_decision,
            trace_emitter=trace_emitter,
            record_evidence=record_evidence,
        )

    if auto_post:
        async with db.begin_nested():
            return await create()
    return await create()


#: The reload of created entries names at most this many ids in one statement (bind parameter limit of the driver).
_ENTRY_RELOAD_CHUNK_SIZE = 1000


@dataclass(frozen=True, slots=True)
class StatementEntryRequest:
    """One transaction of a statement whose accepted disposition posts a journal entry."""

    txn: AtomicTransaction
    disposition: DispositionDecision
    counter_account: Account | None
    source_decision: TraceRecord
    source_type: JournalEntrySourceType


async def create_entries_from_txns(
    db: AsyncSession,
    requests: Sequence[StatementEntryRequest],
    *,
    user_id: UUID,
    base_currency: str | None,
    auto_post: bool,
    preloaded_statement: StatementSummary,
    preloaded_bank_account: Account,
    fx_rate_provider: ExchangeRateLookup | None,
    fx_rate_error: type[Exception] | None,
    trace_emitter: TraceEmitter,
) -> list[JournalEntry]:
    """Create the journal entries of many transactions of one statement.

    Each entry equals the one that ``create_entry_from_txn`` creates for the same request with
    ``record_evidence=False``. The command authorizations are written as one set, and the batch
    runs in one savepoint: one failed entry rolls back every entry of the batch, and the caller
    already aborts the posting in that case.
    """

    async def create() -> list[JournalEntry]:
        plans = [
            await _plan_entry_command(
                db,
                request.txn,
                user_id=user_id,
                base_currency=base_currency,
                auto_post=auto_post,
                source_type=request.source_type,
                preloaded_statement=preloaded_statement,
                preloaded_bank_account=preloaded_bank_account,
                fx_rate_provider=fx_rate_provider,
                fx_rate_error=fx_rate_error,
                disposition=request.disposition,
                counter_account=request.counter_account,
            )
            for request in requests
        ]
        try:
            anchors = await authorize_financial_commands_many(
                emitter=trace_emitter,
                user_id=user_id,
                requests=[
                    FinancialCommandRequest(
                        upstream_decision=request.source_decision,
                        entry_date=plan.txn.txn_date,
                        memo=plan.memo,
                        lines_data=plan.lines_data,
                        base_currency=plan.base_currency,
                        source_id=plan.txn.id,
                    )
                    for request, plan in zip(requests, plans, strict=True)
                ],
            )
            created = await submit_anchored_journal_entries(
                db,
                user_id=user_id,
                commands=[_journal_command(plan, anchor) for plan, anchor in zip(plans, anchors, strict=True)],
                base_currency=plans[0].base_currency,
                trace_repository=trace_emitter.repository,
            )
        except ValidationError as exc:
            raise _posting_error(plans[0], exc) from exc
        # ``post_journal_entry`` returns aggregates whose lines are not guaranteed to be loaded.
        by_id: dict[UUID, JournalEntry] = {}
        created_ids = [entry.id for entry in created]
        for start in range(0, len(created_ids), _ENTRY_RELOAD_CHUNK_SIZE):
            loaded = await db.execute(
                select(JournalEntry)
                .where(JournalEntry.id.in_(created_ids[start : start + _ENTRY_RELOAD_CHUNK_SIZE]))
                .options(selectinload(JournalEntry.lines))
            )
            by_id.update({entry.id: entry for entry in loaded.scalars().all()})
        return [by_id[entry.id] for entry in created]

    if not requests:
        return []
    if auto_post:
        async with db.begin_nested():
            return await create()
    return await create()
