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

from uuid import UUID

from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.audit import SqlTraceRecordRepository, TraceEmitter, normalize_currency_code
from src.config import settings
from src.database import async_session_maker
from src.extraction import (
    DispositionMode,
    DispositionPolicy,
    StatementIngestionUseCase,
    StatementPostingDependencies,
    build_statement_ingestion_use_case,
    extraction_trace_policy_registry,
    snapshot_currencies,
)
from src.ledger import used_currencies
from src.portfolio import active_stock_symbols, position_currencies
from src.pricing import MarketDataScopes, PricingError, get_exchange_rate
from src.reconciliation import ReviewedDispositionDependencies, accepted_transfer_txn_ids
from src.runtime import StorageService


async def _load_statement_content(storage_key: str) -> bytes:
    """Read statement bytes without blocking the async worker loop."""
    storage = StorageService()
    return await run_in_threadpool(storage.get_object, storage_key)


def compose_statement_posting_dependencies() -> StatementPostingDependencies:
    """Bind statement posting to reconciliation and pricing owner ports."""
    return StatementPostingDependencies(
        transfer_exclusions=accepted_transfer_txn_ids,
        fx_rate_provider=get_exchange_rate,
        fx_rate_error=PricingError,
        trace_emitter_factory=lambda db: TraceEmitter(SqlTraceRecordRepository(db, extraction_trace_policy_registry())),
        disposition_mode=DispositionMode(settings.statement_disposition_mode),
    )


def compose_reviewed_disposition_dependencies(db: AsyncSession) -> ReviewedDispositionDependencies:
    """Bind reconciliation's manual command to the canonical trace repository and policy."""
    return ReviewedDispositionDependencies(
        trace_emitter=TraceEmitter(SqlTraceRecordRepository(db, extraction_trace_policy_registry())),
        disposition_policy=DispositionPolicy(),
    )


def compose_statement_ingestion_use_case(
    *,
    session_maker: async_sessionmaker[AsyncSession] = async_session_maker,
) -> StatementIngestionUseCase:
    """Construct the same complete ingestion use case for every process topology."""
    return build_statement_ingestion_use_case(
        session_maker=session_maker,
        content_loader=_load_statement_content,
        posting_dependencies=compose_statement_posting_dependencies(),
        trace_emitter_factory=lambda db: TraceEmitter(SqlTraceRecordRepository(db, extraction_trace_policy_registry())),
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
