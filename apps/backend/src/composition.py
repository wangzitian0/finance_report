"""App composition-root cross-domain composers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from src.audit import SqlTraceRecordRepository, TraceDecisionPolicyRegistry, TraceEmitter
from src.config import settings
from src.config_app import get_effective_base_currency
from src.database import async_session_maker
from src.extraction import (
    ActiveRunExists,
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
    classify_by_effective_policy,
    effective_statement_transaction_filter,
    extraction_trace_policy_registry,
    general_account_name,
    get_active_run,
    get_or_create_account,
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
    initialize_opening_positions,
    ledger_trace_policy_registry,
    used_currencies,
)
from src.portfolio import InvestmentTransaction, InvestmentTransactionType, active_stock_symbols, position_currencies
from src.pricing import MarketDataScopes, PricingError, get_exchange_rate
from src.reconciliation import (
    NamedTransfer,
    ReconciliationMatch,
    ReconciliationStatus,
    ReviewedDispositionCommand,
    ReviewedDispositionDependencies,
    accepted_transfer_txn_ids,
    post_named_transfer_legs,
    posted_statement_source_ids,
    release_transaction_dispositions,
    submit_reviewed_disposition,
    supersede_transaction_transfer_legs,
)
from src.runtime import StorageService

_DEFAULT_BALANCE_SHEET_CODES: dict[AccountType, tuple[str, str]] = {
    AccountType.ASSET: ("Investments (", "1310"),
    AccountType.LIABILITY: ("Loans Payable (", "2210"),
}


async def _load_statement_content(storage_key: str) -> bytes:
    return await run_in_threadpool(StorageService().get_object, storage_key)


def compose_financial_trace_emitter(db: AsyncSession) -> TraceEmitter:
    policies = TraceDecisionPolicyRegistry(
        (*extraction_trace_policy_registry().policies, *ledger_trace_policy_registry().policies)
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


async def _post_and_settle_named_transfers(
    db: AsyncSession,
    user_id: UUID,
    named: Sequence[NamedTransfer],
    suggestions: dict[UUID, ClassificationSuggestion],
    *,
    default_accepted_by: str | None = None,
) -> int:
    if not named:
        return 0
    if default_accepted_by is not None:
        accepted_lit: Literal["user", "system"] = "system" if default_accepted_by == "system" else "user"
        legs = await post_named_transfer_legs(db, user_id=user_id, named=list(named), accepted_by=accepted_lit)
    else:
        legs = await post_named_transfer_legs(db, user_id=user_id, named=list(named))
    classification_ids = {item.transaction.id: suggestions[item.transaction.id].classification_id for item in named}
    chosen_by_user = {item.transaction.id for item in named if item.decided_by_user}
    for leg in legs:
        settle_kwargs: dict[str, Any] = {"accepted_id": classification_ids.get(leg.atomic_txn_id)}
        if default_accepted_by is not None:
            settle_kwargs["accepted_by"] = "user" if leg.atomic_txn_id in chosen_by_user else default_accepted_by
        await settle_drafts_after_posting(db, leg.atomic_txn_id, **settle_kwargs)
    return len(legs)


async def _post_named_transfers_for_user(
    db: AsyncSession, user_id: UUID, transactions: Sequence[AtomicTransaction]
) -> int:
    suggestions = await classification_suggestions(db, [txn.id for txn in transactions])
    named = [
        NamedTransfer(
            transaction=txn,
            category=s.category,
            score=s.confidence,
            decided_by_user=s.corrected,
        )
        for txn in transactions
        if (s := suggestions.get(txn.id)) is not None and s.booking == "processing_leg"
    ]
    return await _post_and_settle_named_transfers(db, user_id, named, suggestions, default_accepted_by="system")


async def _release_reconciliation_for_user(
    db: AsyncSession, user_id: UUID, transaction_ids: Sequence[UUID], reason: str
) -> int:
    return await release_transaction_dispositions(db, user_id=user_id, transaction_ids=transaction_ids, reason=reason)


def compose_statement_posting_dependencies() -> StatementPostingDependencies:
    return StatementPostingDependencies(
        transfer_exclusions=accepted_transfer_txn_ids,
        fx_rate_provider=get_exchange_rate,
        fx_rate_error=PricingError,
        trace_emitter_factory=compose_financial_trace_emitter,
        disposition_mode=DispositionMode(settings.statement_disposition_mode),
        post_named_transfers=_post_named_transfers_for_user,
        release_reconciliation=_release_reconciliation_for_user,
    )


def compose_reviewed_disposition_dependencies(db: AsyncSession) -> ReviewedDispositionDependencies:
    return ReviewedDispositionDependencies(
        trace_emitter=compose_financial_trace_emitter(db),
        disposition_policy=DispositionPolicy(),
    )


async def _active_user_account(
    db: AsyncSession, account_id: UUID | None, user_id: UUID, currency: str, expected_type: AccountType | None = None
) -> Account | None:
    if account_id is None:
        return None
    acc = await db.get(Account, account_id)
    if acc is None or acc.user_id != user_id or not acc.is_active or acc.currency != currency:
        return None
    if expected_type is not None and acc.type != expected_type:
        return None
    return acc


async def _get_or_create_default_counter_account(
    db: AsyncSession,
    user_id: UUID,
    account_type: AccountType,
    currency: str,
    *,
    name: str | None = None,
    code: str | None = None,
) -> Account:
    resolved_name = name or general_account_name(account_type, currency)
    resolved_code = code
    if resolved_code is None and (prefix_and_code := _DEFAULT_BALANCE_SHEET_CODES.get(account_type)):
        if resolved_name.startswith(prefix_and_code[0]):
            resolved_code = prefix_and_code[1]
    if resolved_code is None:
        return await get_or_create_account(
            db, name=resolved_name, account_type=account_type, currency=currency, user_id=user_id
        )
    cache = db.info.setdefault("_default_account_cache", {})
    cache_key = (user_id, resolved_name, account_type, currency)
    if cache_key in cache:
        return cache[cache_key]

    async def find(session: AsyncSession) -> Account | None:
        return (
            await session.execute(
                select(Account)
                .where(
                    Account.type == account_type,
                    Account.currency == currency,
                    Account.user_id == user_id,
                    Account.is_active.is_(True),
                    or_(Account.code == resolved_code, Account.name == resolved_name),
                )
                .order_by((Account.code == resolved_code).desc(), Account.created_at, Account.id)
                .limit(1)
            )
        ).scalar_one_or_none()

    account = await account_service.find_or_create_account(
        db,
        user_id=user_id,
        find=find,
        build=lambda: Account(
            user_id=user_id, name=resolved_name, code=resolved_code, type=account_type, currency=currency
        ),
    )
    cache[cache_key] = account
    return account


def _statement_unmatched_txns_query(statement: StatementSummary, user_id: UUID):
    matched_txn = aliased(AtomicTransaction)
    matched_subq = (
        select(ReconciliationMatch.atomic_txn_id)
        .join(matched_txn, matched_txn.id == ReconciliationMatch.atomic_txn_id)
        .where(
            matched_txn.user_id == user_id,
            ReconciliationMatch.status.notin_((ReconciliationStatus.REJECTED, ReconciliationStatus.SUPERSEDED)),
            ReconciliationMatch.superseded_by_id.is_(None),
            ReconciliationMatch.atomic_txn_id.is_not(None),
        )
    )
    return select(AtomicTransaction).where(
        effective_statement_transaction_filter(user_id, statement.id),
        AtomicTransaction.id.notin_(matched_subq),
        AtomicTransaction.id.notin_(posted_statement_source_ids(user_id)),
    )


def _suggestion_rationale(suggestion: ClassificationSuggestion) -> str:
    if suggestion.corrected:
        return f"Category corrected by the user: {suggestion.category}"
    return f"Accepted AI suggestion {suggestion.category} (score {suggestion.confidence})"


async def _has_matching_posted_investment_trade(db: AsyncSession, user_id: UUID, txn: AtomicTransaction) -> bool:
    expected = (
        InvestmentTransactionType.BUY if txn.direction == TransactionDirection.OUT else InvestmentTransactionType.SELL
    )
    stmt = (
        select(InvestmentTransaction.id)
        .join(JournalEntry, InvestmentTransaction.journal_entry_id == JournalEntry.id)
        .where(
            InvestmentTransaction.user_id == user_id,
            InvestmentTransaction.transaction_date == txn.txn_date,
            InvestmentTransaction.currency == txn.currency,
            InvestmentTransaction.transaction_type == expected,
            InvestmentTransaction.gross_amount == txn.amount,
            JournalEntry.status.in_((JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED)),
        )
        .limit(1)
    )
    return (await db.scalar(stmt)) is not None


async def _balance_sheet_disposition_for(
    db: AsyncSession, user_id: UUID, txn: AtomicTransaction, suggestion: ClassificationSuggestion
) -> tuple[EconomicIntent, Account, str, str] | None:
    booking = balance_sheet_booking(suggestion.category, txn.direction, txn.currency)
    if booking is None:
        return None
    intent, account_type, name = booking
    if suggestion.booking == "investment_trade" and await _has_matching_posted_investment_trade(db, user_id, txn):
        return None
    account = await _active_user_account(
        db, suggestion.account_id, user_id, txn.currency, account_type
    ) or await _get_or_create_default_counter_account(db, user_id, account_type, txn.currency, name=name)
    return intent, account, suggestion.category, _suggestion_rationale(suggestion)


async def _accepted_suggestion_for(
    db: AsyncSession, user_id: UUID, txn: AtomicTransaction, suggestion: ClassificationSuggestion | None
) -> tuple[EconomicIntent, Account, str, str] | None:
    if suggestion is None:
        return None
    account = await _active_user_account(db, suggestion.account_id, user_id, txn.currency)
    if account is None:
        return None
    if account.type is AccountType.INCOME and txn.direction == TransactionDirection.IN:
        intent = EconomicIntent.INCOME
    elif account.type is AccountType.EXPENSE and txn.direction == TransactionDirection.OUT:
        intent = EconomicIntent.EXPENSE
    else:
        return None
    return intent, account, suggestion.category, _suggestion_rationale(suggestion)


async def auto_fill_default_statement_dispositions(
    db: AsyncSession, statement: StatementSummary, user_id: UUID
) -> int:
    """Accept draft AI suggestions and fill general counter accounts for remaining rows. An active run refuses (#2994)."""
    active_run = await get_active_run(db, statement.id)
    if active_run is not None:
        raise ActiveRunExists(active_run.id)
    unmatched_txns = (await db.execute(_statement_unmatched_txns_query(statement, user_id))).scalars().all()
    if not unmatched_txns:
        return 0

    dependencies = compose_reviewed_disposition_dependencies(db)
    resolved_count = 0
    accounts_cache: dict[tuple[AccountType, str], Account] = {}
    await classify_by_effective_policy(db, user_id, unmatched_txns)
    suggestions = await classification_suggestions(db, [txn.id for txn in unmatched_txns])
    left_to_posting = await applied_rows_the_policy_accepts(
        db,
        unmatched_txns,
        mode=DispositionMode(settings.statement_disposition_mode),
        policy=await statement_disposition_policy_for_user(db, user_id),
    )
    base_currency = (await get_effective_base_currency(db, user_id=user_id)).upper()
    statement_currency = (statement.currency or "").upper()
    named_transfers: list[NamedTransfer] = []

    for txn in unmatched_txns:
        if txn.id in left_to_posting:
            continue
        suggestion = suggestions.get(txn.id)
        if (
            suggestion is not None
            and suggestion.booking == "processing_leg"
            and (txn.currency or "").upper() == base_currency
            and statement_currency in {"", base_currency}
        ):
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
            if accepted is None and suggestion.booking == "investment_trade":
                await settle_drafts_after_posting(
                    db, txn.id, accepted_id=suggestion.classification_id, accepted_by="system"
                )
                continue
        else:
            accepted = await _accepted_suggestion_for(db, user_id, txn, suggestion)

        if accepted is not None:
            intent, counter_account, category, rationale = accepted
            accepted_id = suggestion.classification_id if suggestion else None
        else:
            if txn.direction == TransactionDirection.OUT:
                intent, account_type, category, rationale = (
                    EconomicIntent.EXPENSE,
                    AccountType.EXPENSE,
                    "General Expense",
                    "Auto-filled default expense",
                )
            else:
                intent, account_type, category, rationale = (
                    EconomicIntent.INCOME,
                    AccountType.INCOME,
                    "General Income",
                    "Auto-filled default income",
                )
            cache_key = (account_type, txn.currency)
            if cache_key not in accounts_cache:
                accounts_cache[cache_key] = await _get_or_create_default_counter_account(
                    db, user_id, account_type, txn.currency
                )
            counter_account = accounts_cache[cache_key]
            accepted_id = (
                suggestion.classification_id if suggestion and suggestion.booking == "processing_leg" else None
            )

        await submit_reviewed_disposition(
            db,
            transaction_id=txn.id,
            user_id=user_id,
            command=ReviewedDispositionCommand(
                intent=intent, counter_account_id=counter_account.id, category=category, rationale=rationale
            ),
            dependencies=dependencies,
        )
        await settle_drafts_after_posting(db, txn.id, accepted_id=accepted_id)
        resolved_count += 1

    resolved_count += await _post_and_settle_named_transfers(db, user_id, named_transfers, suggestions)
    return resolved_count


def compose_statement_ingestion_use_case(
    *, session_maker: async_sessionmaker[AsyncSession] = async_session_maker
) -> StatementIngestionUseCase:
    return build_statement_ingestion_use_case(
        session_maker=session_maker,
        content_loader=_load_statement_content,
        posting_dependencies=compose_statement_posting_dependencies(),
        trace_emitter_factory=compose_financial_trace_emitter,
    )


async def observed_fx_pairs(
    db: AsyncSession, user_id: UUID | None, *, include_default: bool = True, base_currency: str | None = None
) -> list[str]:
    base = (base_currency or await get_effective_base_currency(db, user_id=user_id)).strip().upper()
    currencies: set[str] = {base}
    if include_default:
        currencies.add("USD" if base != "USD" else "SGD")
    for reader in (used_currencies, position_currencies, snapshot_currencies):
        currencies |= await reader(db, user_id)
    return [f"{c}/{base}" for c in sorted(currencies) if c != base]


async def market_data_scopes(db: AsyncSession) -> MarketDataScopes:
    return MarketDataScopes(
        fx_pairs=await observed_fx_pairs(db, None),
        stock_symbols=await active_stock_symbols(db, None),
    )


async def _repost_approved_statement_for_correction(
    db: AsyncSession, statement: StatementSummary, user_id: UUID, transactions: list[AtomicTransaction]
) -> None:
    deps = replace(compose_statement_posting_dependencies(), disposition_mode=DispositionMode.ENFORCE)
    await auto_create_posted_entries_for_statement(
        db, statement, user_id, dependencies=deps, transactions=transactions
    )


async def _supersede_transfer_legs_for_correction(
    db: AsyncSession, user_id: UUID, transaction_id: UUID, reason: str
) -> None:
    await supersede_transaction_transfer_legs(db, user_id=user_id, transaction_id=transaction_id, reason=reason)


def compose_correction_callbacks() -> dict[str, Any]:
    return {
        "supersede_transfer_legs": _supersede_transfer_legs_for_correction,
        "repost_approved_statement": _repost_approved_statement_for_correction,
    }
