"""Test helpers that exercise the production statement composition boundary."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.composition import compose_statement_ingestion_use_case, compose_statement_posting_dependencies
from src.extraction import (
    DispositionContext,
    DispositionDecision,
    DispositionMode,
    DispositionPolicy,
    DocumentSource,
    EconomicIntent,
    IntentProposal,
    IntentProposalOrigin,
    ParseJob,
    StatementExtractionResult,
    StatementIngestionOutcome,
    StatementPostingDependencies,
    StatementSummary,
    StatementTransaction,
)
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_validation import resolve_statement_transactions
from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import Account, AccountType


async def execute_statement_ingestion(
    job: ParseJob,
    *,
    content: bytes,
    session_maker: async_sessionmaker[AsyncSession],
) -> StatementIngestionOutcome:
    """Execute through the same explicit composition used by API and Prefect."""
    return await compose_statement_ingestion_use_case(session_maker=session_maker).execute(
        job,
        content=content,
    )


def posting_dependencies() -> StatementPostingDependencies:
    """Return the production-shaped dependency bundle for posting tests."""
    return compose_statement_posting_dependencies()


async def reviewed_posting_inputs(
    db: AsyncSession,
    *,
    user_id,
    transaction: AtomicTransaction,
    intent: EconomicIntent,
) -> tuple[DispositionDecision, Account]:
    """Build the explicit reviewed authority required by ledger-adapter tests."""
    account_type = {
        EconomicIntent.INCOME: AccountType.INCOME,
        EconomicIntent.EXPENSE: AccountType.EXPENSE,
    }.get(intent)
    if account_type is None:
        raise ValueError(f"Test helper needs an explicit counter-account type for {intent}")
    counter_account = Account(
        user_id=user_id,
        name=f"{account_type.value.title()} - Reviewed Test {transaction.id}",
        type=account_type,
        currency=transaction.currency,
    )
    db.add(counter_account)
    await db.flush()
    decision = DispositionPolicy().decide(
        StatementTransaction(
            transaction_id=transaction.id,
            transaction_date=transaction.txn_date,
            amount=transaction.amount,
            currency=transaction.currency,
            direction=transaction.direction,
            description=transaction.description,
        ),
        proposal=IntentProposal(
            schema_version="1",
            policy_version="reviewed-test-v1",
            origin=IntentProposalOrigin.REVIEWED_RULE,
            intent=intent,
            category="TEST",
            confidence=Decimal("1"),
            evidence=("reviewed-test",),
        ),
        context=DispositionContext(counter_account_id=counter_account.id),
        mode=DispositionMode.ENFORCE,
    )
    return decision, counter_account


async def parse_and_load_statement_projection(
    service: ExtractionService,
    *,
    db: AsyncSession,
    user_id,
    source: DocumentSource,
    institution: str | None,
    file_type: str = "pdf",
    account_id=None,
    force_model: str | None = None,
) -> tuple[StatementExtractionResult, StatementSummary, list[AtomicTransaction]]:
    """Parse to the canonical result, then read its persisted ODS/DWD projection."""
    result = await service.parse_document(
        source,
        institution=institution,
        user_id=user_id,
        file_type=file_type,
        account_id=account_id,
        force_model=force_model,
        db=db,
    )
    statement = (
        await db.execute(
            select(StatementSummary)
            .where(StatementSummary.user_id == user_id)
            .where(StatementSummary.file_hash == result.source_content_digest)
        )
    ).scalar_one()
    transactions = await resolve_statement_transactions(db, statement)
    return result, statement, transactions
