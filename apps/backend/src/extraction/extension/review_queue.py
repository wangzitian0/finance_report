"""Journal-entry creation from an atomic transaction (posting/classification seam)."""

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
from src.extraction.extension.custody_binding import resolve_bank_custody_account
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
_ENTRY_RELOAD_CHUNK_SIZE = 1000


async def _resolve_statement_summary(
    db: AsyncSession, txn: AtomicTransaction, *, user_id: UUID
) -> StatementSummary | None:
    doc_ids = extract_source_document_ids(txn.source_documents, doc_type=DocumentType.BANK_STATEMENT.value)
    if not doc_ids:
        return None
    result = await db.execute(
        select(StatementSummary)
        .join(UploadedDocument, StatementSummary.uploaded_document_id == UploadedDocument.id)
        .where(StatementSummary.user_id == user_id, UploadedDocument.id.in_(doc_ids))
    )
    summaries = {summary.uploaded_document_id: summary for summary in result.scalars()}
    return next((summaries[doc_id] for doc_id in doc_ids if doc_id in summaries), None)


async def get_or_create_account(
    db: AsyncSession, *, name: str, account_type: AccountType, currency: str, user_id: UUID
) -> Account:
    """Fetch or create an active default account, reusing the oldest on legacy duplicates."""
    cache = db.info.setdefault("_default_account_cache", {})
    cache_key = (user_id, name, account_type, currency)
    if cache_key in cache:
        return cache[cache_key]

    async def find(session: AsyncSession) -> Account | None:
        accounts = list(
            (
                await session.execute(
                    select(Account)
                    .where(
                        Account.name == name,
                        Account.type == account_type,
                        Account.currency == currency,
                        Account.user_id == user_id,
                        Account.is_active.is_(True),
                    )
                    .order_by(Account.created_at, Account.id)
                    .limit(2)
                )
            )
            .scalars()
            .all()
        )
        if len(accounts) > 1:
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


async def resolve_secondary_currency_custody_account(
    db: AsyncSession, *, statement: StatementSummary, user_id: UUID, currency: str
) -> Account:
    """Resolve or create a custody asset account for a secondary statement currency."""
    if statement.institution and statement.account_last4:
        return await resolve_bank_custody_account(
            db,
            user_id=user_id,
            institution=statement.institution,
            account_last4=statement.account_last4,
            currency=currency,
            create_if_missing=True,
        )
    return await get_or_create_account(
        db,
        name=f"{statement.institution or 'Statement Account'} ({currency})",
        account_type=AccountType.ASSET,
        currency=currency,
        user_id=user_id,
    )


@dataclass(frozen=True, slots=True)
class PlannedEntryCommand:
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
    if txn.user_id != user_id:
        raise ValueError("Transaction does not belong to user")
    if getattr(txn, "currency_unresolved", False):
        raise CurrencyUnresolvedError(
            f"Transaction {txn.id} has an unresolved currency and cannot be promoted to a "
            "journal entry. A reviewer must specify its currency first."
        )

    statement = preloaded_statement
    if statement is not None:
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

    statement_account_id = statement.account_id if statement else None
    bank_account: Account | None = preloaded_bank_account
    if bank_account is not None:
        if bank_account.user_id != user_id:
            raise ValueError("Bank account does not belong to user")
        if statement_account_id and bank_account.id != statement_account_id:
            raise ValueError("Preloaded bank account does not match statement")
    elif statement_account_id:
        bank_account = (
            await db.execute(select(Account).where(Account.id == statement_account_id, Account.user_id == user_id))
        ).scalar_one_or_none()

    if not bank_account:
        raise ValueError("Account mapping required before statement posting")
    if bank_account.type is not AccountType.ASSET or not bank_account.is_active:
        raise ValueError("Statement posting account must be an active asset account")
    if bank_account.currency != currency and statement is not None and len(statement.typed_currency_balances()) > 1:
        bank_account = await resolve_secondary_currency_custody_account(
            db, statement=statement, user_id=user_id, currency=currency
        )
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
        debit_account, credit_account = bank_account, counter_account
    else:
        if disposition.command.debit_role != "counter" or disposition.command.credit_role != "custody":
            raise ValueError("Disposition command conflicts with outgoing transaction flow")
        debit_account, credit_account = counter_account, bank_account

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


async def _reload_entries_with_lines(db: AsyncSession, created: Sequence[JournalEntry]) -> list[JournalEntry]:
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

    (entry,) = await _reload_entries_with_lines(db, [entry])
    if record_evidence:
        try:
            from src.extraction.extension.evidence_graph_integration import EvidenceGraphIntegrationService

            await EvidenceGraphIntegrationService().record_journal_posting(
                db, user_id=user_id, atomic_transaction=txn, journal_entry=entry
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
    async def _run() -> JournalEntry:
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
            return await _run()
    return await _run()


@dataclass(frozen=True, slots=True)
class StatementEntryRequest:
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
    if not requests:
        return []

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
        return await _reload_entries_with_lines(db, created)

    if auto_post:
        async with db.begin_nested():
            return await create()
    return await create()
