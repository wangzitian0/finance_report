"""App composition-root cross-domain composers.

``observed_fx_pairs`` is the thin composer that #1641 introduced (originally
in ``services/market_data_scheduler.py``; moved here when #1610 P2 absorbed
that module into ``pricing``): each domain publishes its own currencies read
(``ledger.used_currencies``, ``portfolio.position_currencies``,
``extraction.snapshot_currencies``) and this composer merges them with the
configured base/default-counterparty currencies into the
``<currency>/<base>`` pairs passed to ``pricing``'s crawl (call-convention
inversion — pricing never discovers scopes itself). It lives here, not in any
domain package, because it is cross-domain composition; ``main.py`` injects
:func:`market_data_scopes` into pricing's scheduler as its
``MarketDataScopeProvider`` — the same composition-root inversion as the
provider-port registrations in ``main.py`` (#1762/#1768 precedents).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from src.audit import (
    STATEMENT_SOURCE_TYPES,
    SqlTraceRecordRepository,
    TraceDecisionPolicyRegistry,
    TraceEmitter,
    normalize_currency_code,
)
from src.config import settings
from src.config_app import get_effective_base_currency
from src.database import async_session_maker
from src.extraction import (
    AtomicTransaction,
    ClassificationSuggestion,
    DispositionMode,
    DispositionPolicy,
    EconomicIntent,
    StatementIngestionUseCase,
    StatementPostingDependencies,
    StatementSummary,
    TransactionDirection,
    applied_rows_the_policy_accepts,
    auto_create_posted_entries_for_statement,
    balance_sheet_booking,
    build_statement_ingestion_use_case,
    classification_suggestions,
    classify_statement_by_effective_policy,
    effective_statement_transaction_filter,
    extraction_trace_policy_registry,
    general_account_name,
    get_or_create_account,
    record_correction,
    settle_drafts_after_posting,
    snapshot_currencies,
    statement_disposition_policy_for_user,
)
from src.ledger import (
    Account,
    AccountType,
    JournalEntry,
    JournalEntryStatus,
    account_service,
    current_anchored_journal_entries,
    initialize_opening_positions,
    ledger_trace_policy_registry,
    used_currencies,
)
from src.portfolio import active_stock_symbols, position_currencies
from src.pricing import MarketDataScopes, PricingError, get_exchange_rate
from src.reconciliation import (
    NamedTransfer,
    ReconciliationMatch,
    ReconciliationStatus,
    ReviewedDispositionCommand,
    ReviewedDispositionDependencies,
    accepted_transfer_txn_ids,
    post_named_transfer_legs,
    submit_reviewed_disposition,
    supersede_transaction_transfer_legs,
)
from src.runtime import StorageService


async def _load_statement_content(storage_key: str) -> bytes:
    """Read statement bytes without blocking the async worker loop."""
    storage = StorageService()
    return await run_in_threadpool(storage.get_object, storage_key)


def compose_financial_trace_emitter(db: AsyncSession) -> TraceEmitter:
    """Replay source and ledger authority across the posting causal boundary."""
    policies = TraceDecisionPolicyRegistry(
        (
            *extraction_trace_policy_registry().policies,
            *ledger_trace_policy_registry().policies,
        )
    )
    return TraceEmitter(SqlTraceRecordRepository(db, policies))


async def post_guided_opening_balances(
    db: AsyncSession,
    user_id: UUID,
    *,
    entry_date: date,
    balances: dict[UUID, Decimal],
    currency: str | None,
    memo: str,
) -> JournalEntry | None:
    """Compose ledger-owned opening targets with pricing-owned historical rates."""
    base_currency = await get_effective_base_currency(db, user_id=user_id)
    currencies = await account_service.opening_balance_currencies(db, user_id, list(balances), currency)
    fx_rates = {
        code: await get_exchange_rate(db, code, base_currency, entry_date, lazy_load=True)
        for code in sorted(currencies - {base_currency})
    }
    return await initialize_opening_positions(
        db,
        user_id,
        entry_date=entry_date,
        balances=balances,
        currency=currency,
        fx_rates=fx_rates,
        trace_emitter=compose_financial_trace_emitter(db),
        base_currency=base_currency,
        memo=memo,
    )


async def _post_named_transfers_for_user(
    db: AsyncSession, user_id: UUID, transactions: Sequence[AtomicTransaction]
) -> int:
    """Post the Processing legs of the rows that the AI named a transfer or a card repayment (#2405).

    The posting calls this for a user who lets the system accept the suggestions. The legs belong to
    reconciliation, so this adapter reads the drafts that extraction wrote and hands them over.
    """
    suggestions = await classification_suggestions(db, [txn.id for txn in transactions])
    named = [
        NamedTransfer(
            transaction=txn,
            category=suggestion.category,
            score=suggestion.confidence,
            decided_by_user=suggestion.corrected,
        )
        for txn in transactions
        if (suggestion := suggestions.get(txn.id)) is not None and suggestion.booking == "processing_leg"
    ]
    if not named:
        return 0
    legs = await post_named_transfer_legs(db, user_id=user_id, named=named, accepted_by="system")
    classification_ids = {item.transaction.id: suggestions[item.transaction.id].classification_id for item in named}
    chosen_by_user = {item.transaction.id for item in named if item.decided_by_user}
    for leg in legs:
        # The draft gets the same name as its leg: a class that the user chose is a decision of the user.
        await settle_drafts_after_posting(
            db,
            leg.atomic_txn_id,
            accepted_id=classification_ids.get(leg.atomic_txn_id),
            accepted_by="user" if leg.atomic_txn_id in chosen_by_user else "system",
        )
    return len(legs)


def compose_statement_posting_dependencies() -> StatementPostingDependencies:
    """Bind statement posting to reconciliation and pricing owner ports."""
    return StatementPostingDependencies(
        transfer_exclusions=accepted_transfer_txn_ids,
        fx_rate_provider=get_exchange_rate,
        fx_rate_error=PricingError,
        trace_emitter_factory=compose_financial_trace_emitter,
        disposition_mode=DispositionMode(settings.statement_disposition_mode),
        post_named_transfers=_post_named_transfers_for_user,
    )


def compose_reviewed_disposition_dependencies(db: AsyncSession) -> ReviewedDispositionDependencies:
    """Bind reconciliation's manual command to the canonical trace repository and policy."""
    return ReviewedDispositionDependencies(
        trace_emitter=compose_financial_trace_emitter(db),
        disposition_policy=DispositionPolicy(),
    )


async def _get_or_create_default_counter_account(
    db: AsyncSession,
    user_id: UUID,
    account_type: AccountType,
    currency: str,
    *,
    name: str | None = None,
) -> Account:
    """The default counter account of a type and a currency. The classifier uses the same resolver (#2415)."""
    return await get_or_create_account(
        db,
        name=name or general_account_name(account_type, currency),
        account_type=account_type,
        currency=currency,
        user_id=user_id,
    )


def _statement_unmatched_txns_query(statement: StatementSummary, user_id: UUID):
    matched_transaction = aliased(AtomicTransaction)
    matched_subquery = (
        select(ReconciliationMatch.atomic_txn_id)
        .join(matched_transaction, matched_transaction.id == ReconciliationMatch.atomic_txn_id)
        .where(matched_transaction.user_id == user_id)
        .where(ReconciliationMatch.status.notin_((ReconciliationStatus.REJECTED, ReconciliationStatus.SUPERSEDED)))
        .where(ReconciliationMatch.superseded_by_id.is_(None))
        .where(ReconciliationMatch.atomic_txn_id.is_not(None))
    )
    posted_source_subquery = (
        current_anchored_journal_entries(
            user_id=user_id,
            target_kind="journal_command",
            target_id=func.concat("statement-transaction:", JournalEntry.source_id),
        )
        .with_only_columns(JournalEntry.source_id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.status != JournalEntryStatus.VOID)
    )
    return select(AtomicTransaction).where(
        effective_statement_transaction_filter(user_id, statement.id),
        AtomicTransaction.id.notin_(matched_subquery),
        AtomicTransaction.id.notin_(posted_source_subquery),
    )


def _suggestion_rationale(suggestion: ClassificationSuggestion) -> str:
    if suggestion.corrected:
        return f"Category corrected by the user: {suggestion.category}"
    return f"Accepted AI suggestion {suggestion.category} (score {suggestion.confidence})"


async def _balance_sheet_disposition_for(
    db: AsyncSession, user_id: UUID, txn: AtomicTransaction, suggestion: ClassificationSuggestion
) -> tuple[EconomicIntent, Account, str, str] | None:
    """The reviewed disposition for a loan principal or an investment trade (#2415).

    The row posts to a default balance-sheet account: a liability for a loan, an asset for an investment.
    Neither is income or expense. A loan repayment lowers the liability. A drawdown raises it. A purchase
    raises the asset. A sale lowers it. Returns None for any other class.
    """
    booking = balance_sheet_booking(suggestion.category, txn.direction, txn.currency)
    if booking is None:
        return None
    intent, account_type, name = booking
    account = await _get_or_create_default_counter_account(db, user_id, account_type, txn.currency, name=name)
    return intent, account, suggestion.category, _suggestion_rationale(suggestion)


async def _accepted_suggestion_for(
    db: AsyncSession,
    user_id: UUID,
    txn: AtomicTransaction,
    suggestion: ClassificationSuggestion | None,
) -> tuple[EconomicIntent, Account, str, str] | None:
    """The reviewed disposition that accepting the draft AI suggestion of a row stands for.

    Returns None when there is no usable suggestion: no account, an account that is not the
    user's active account in the row currency, or a type that contradicts the direction of the
    row (income for an outgoing row, expense for an incoming row).
    """
    if suggestion is None or suggestion.account_id is None:
        return None
    account = await db.get(Account, suggestion.account_id)
    if account is None or account.user_id != user_id or not account.is_active or account.currency != txn.currency:
        return None
    if account.type is AccountType.INCOME and txn.direction == TransactionDirection.IN:
        intent = EconomicIntent.INCOME
    elif account.type is AccountType.EXPENSE and txn.direction == TransactionDirection.OUT:
        intent = EconomicIntent.EXPENSE
    else:
        return None
    return intent, account, suggestion.category, _suggestion_rationale(suggestion)


async def auto_fill_default_statement_dispositions(
    db: AsyncSession,
    statement: StatementSummary,
    user_id: UUID,
) -> int:
    """Accept the draft AI suggestions, then fill general counter accounts for the other rows.

    Submits reviewed dispositions which create posted journal entries for any
    unmatched statement transactions, returning the number of posted entries created.
    A row that the classifier already applied, with an account that the policy accepts, is left to
    the normal posting that follows. A row with a usable draft AI suggestion posts to the suggested
    account and category. A row that the AI named a transfer, a card repayment, a loan payment or a
    trade is not income or expense: it posts as a Processing transfer leg, like the keyword fallback
    of the reconciliation run, and the other side of the movement clears it later. Such a row stays
    for a person when its leg cannot post (#2415). Any other row posts to the general income or
    expense account of its direction.
    """
    query = _statement_unmatched_txns_query(statement, user_id)
    result = await db.execute(query)
    unmatched_txns = result.scalars().all()
    if not unmatched_txns:
        return 0

    dependencies = compose_reviewed_disposition_dependencies(db)
    resolved_count = 0
    accounts_cache: dict[tuple[AccountType, str], Account] = {}
    # A statement that was never classified (a parse that did not post by itself) has no suggestion yet. The
    # classifier runs first, so a row does not fall to the general account while the model could place it (#2405).
    # A row that already has a classification keeps it.
    await classify_statement_by_effective_policy(db, user_id, statement.id, unmatched_txns)
    suggestions = await classification_suggestions(db, [txn.id for txn in unmatched_txns])
    # The posting that follows posts these rows from their applied classification (the score gate of the
    # policy of the user, or a reviewed rule). The disposition policy decides, as in the posting itself. An applied row that the
    # policy refuses falls through to the default below, because the posting cannot clear such a row (#2419).
    left_to_posting = await applied_rows_the_policy_accepts(
        db,
        unmatched_txns,
        mode=DispositionMode(settings.statement_disposition_mode),
        policy=await statement_disposition_policy_for_user(db, user_id),
    )
    named_transfers: list[NamedTransfer] = []

    for txn in unmatched_txns:
        if txn.id in left_to_posting:
            continue
        suggestion = suggestions.get(txn.id)
        if suggestion is not None and suggestion.booking == "processing_leg":
            named_transfers.append(
                NamedTransfer(
                    transaction=txn,
                    category=suggestion.category,
                    score=suggestion.confidence,
                    decided_by_user=suggestion.corrected,
                )
            )
            continue
        if suggestion is not None and suggestion.non_pnl:
            accepted = await _balance_sheet_disposition_for(db, user_id, txn, suggestion)
        else:
            accepted = await _accepted_suggestion_for(db, user_id, txn, suggestion)
        if accepted is not None:
            intent, counter_account, category, rationale = accepted
            await submit_reviewed_disposition(
                db,
                transaction_id=txn.id,
                user_id=user_id,
                command=ReviewedDispositionCommand(
                    intent=intent,
                    counter_account_id=counter_account.id,
                    category=category,
                    rationale=rationale,
                ),
                dependencies=dependencies,
            )
            await settle_drafts_after_posting(
                db, txn.id, accepted_id=suggestion.classification_id if suggestion else None
            )
            resolved_count += 1
            continue

        if txn.direction == TransactionDirection.OUT:
            intent = EconomicIntent.EXPENSE
            account_type = AccountType.EXPENSE
            category = "General Expense"
            rationale = "Auto-filled default expense"
        else:
            intent = EconomicIntent.INCOME
            account_type = AccountType.INCOME
            category = "General Income"
            rationale = "Auto-filled default income"

        cache_key = (account_type, txn.currency)
        if cache_key not in accounts_cache:
            accounts_cache[cache_key] = await _get_or_create_default_counter_account(
                db, user_id, account_type, txn.currency
            )
        counter_account = accounts_cache[cache_key]

        await submit_reviewed_disposition(
            db,
            transaction_id=txn.id,
            user_id=user_id,
            command=ReviewedDispositionCommand(
                intent=intent,
                counter_account_id=counter_account.id,
                category=category,
                rationale=rationale,
            ),
            dependencies=dependencies,
        )
        await settle_drafts_after_posting(db, txn.id, accepted_id=None)
        resolved_count += 1

    if named_transfers:
        legs = await post_named_transfer_legs(db, user_id=user_id, named=named_transfers)
        classification_ids = {
            item.transaction.id: suggestions[item.transaction.id].classification_id for item in named_transfers
        }
        for leg in legs:
            await settle_drafts_after_posting(
                db, leg.atomic_txn_id, accepted_id=classification_ids.get(leg.atomic_txn_id)
            )
        resolved_count += len(legs)

    return resolved_count


def compose_statement_ingestion_use_case(
    *,
    session_maker: async_sessionmaker[AsyncSession] = async_session_maker,
) -> StatementIngestionUseCase:
    """Construct the same complete ingestion use case for every process topology."""
    return build_statement_ingestion_use_case(
        session_maker=session_maker,
        content_loader=_load_statement_content,
        posting_dependencies=compose_statement_posting_dependencies(),
        trace_emitter_factory=compose_financial_trace_emitter,
    )


async def observed_fx_pairs(
    db: AsyncSession,
    user_id: UUID | None,
    *,
    include_default: bool = True,
) -> list[str]:
    """The ``<currency>/<base>`` pairs implied by every currency the user holds."""
    base = normalize_currency_code(settings.base_currency)
    default_counterparty = "USD" if base != "USD" else "SGD"
    currencies: set[str] = {base}
    if include_default:
        currencies.add(default_counterparty)

    currencies |= await used_currencies(db, user_id)
    currencies |= await position_currencies(db, user_id)
    currencies |= await snapshot_currencies(db, user_id)

    return [f"{currency}/{base}" for currency in sorted(currencies) if currency != base]


async def market_data_scopes(db: AsyncSession) -> MarketDataScopes:
    """The all-users crawl scopes pricing's daily scheduler syncs.

    The ``MarketDataScopeProvider`` implementation ``main.py`` injects into
    ``run_market_data_scheduler`` — reads only; the scheduler owns the commit.
    """
    return MarketDataScopes(
        fx_pairs=await observed_fx_pairs(db, None),
        stock_symbols=await active_stock_symbols(db, None),
    )


async def _repost_approved_statement_for_correction(
    db: AsyncSession,
    statement: StatementSummary,
    user_id: UUID,
    transactions: list[AtomicTransaction],
) -> None:
    base_deps = compose_statement_posting_dependencies()
    posting_deps = StatementPostingDependencies(
        transfer_exclusions=base_deps.transfer_exclusions,
        fx_rate_provider=base_deps.fx_rate_provider,
        fx_rate_error=base_deps.fx_rate_error,
        trace_emitter_factory=base_deps.trace_emitter_factory,
        disposition_mode=DispositionMode.ENFORCE,
        post_named_transfers=base_deps.post_named_transfers,
    )
    await auto_create_posted_entries_for_statement(
        db,
        statement,
        user_id,
        dependencies=posting_deps,
        transactions=transactions,
    )


async def _supersede_transfer_legs_for_correction(
    db: AsyncSession,
    user_id: UUID,
    transaction_id: UUID,
    reason: str,
) -> None:
    await supersede_transaction_transfer_legs(
        db,
        user_id=user_id,
        transaction_id=transaction_id,
        reason=reason,
    )


def compose_correction_callbacks() -> dict[str, Any]:
    """Compose dependency injection callbacks for post-posting category correction (#2423)."""
    return {
        "supersede_transfer_legs": _supersede_transfer_legs_for_correction,
        "repost_approved_statement": _repost_approved_statement_for_correction,
    }


async def record_user_correction(
    db: AsyncSession,
    *,
    user_id: UUID,
    transaction_id: UUID,
    corrected_category: str,
    corrected_account_id: UUID | None = None,
) -> Any:
    """Record a user correction with reconciliation and statement posting callbacks wired (#2423)."""
    return await record_correction(
        db,
        user_id=user_id,
        transaction_id=transaction_id,
        corrected_category=corrected_category,
        corrected_account_id=corrected_account_id,
        **compose_correction_callbacks(),
    )
