from __future__ import annotations; from dataclasses import replace; from datetime import UTC, datetime; from uuid import UUID; from decimal import Decimal; from sqlalchemy import select; from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker; from src.audit import TraceEmitter, TraceRecord; from src.database import create_session_maker_from_db; from src.composition import compose_statement_ingestion_use_case, compose_statement_posting_dependencies; from src.extraction import DispositionContext, DispositionDecision, DispositionMode, DispositionPolicy, DocumentSource, EconomicIntent, IntentProposal, IntentProposalOrigin, ParseJob, StatementExtractionResult, StatementIngestionOutcome, StatementPostingDependencies, StatementSummary, StatementTransaction; from src.extraction.extension.disposition_trace import emit_disposition_trace_records; from src.extraction.extension.service import ExtractionService; from src.extraction.extension.statement_validation import resolve_statement_transactions; from src.extraction.orm.layer2 import AtomicTransaction; from src.ledger import Account, AccountType
async def _no_sleep(_delay: float) -> None: return None
async def execute_statement_ingestion(job: ParseJob, *, content: bytes, session_maker: async_sessionmaker[AsyncSession]) -> StatementIngestionOutcome: return await replace(compose_statement_ingestion_use_case(session_maker=session_maker), sleep=_no_sleep).execute(job, content=content)
posting_dependencies = lambda: compose_statement_posting_dependencies()
async def reviewed_posting_inputs(db: AsyncSession, *, user_id, transaction: AtomicTransaction, intent: EconomicIntent) -> tuple[DispositionDecision, Account]:
    account_type = {EconomicIntent.INCOME: AccountType.INCOME, EconomicIntent.EXPENSE: AccountType.EXPENSE}.get(intent)
    if account_type is None: raise ValueError(f'Test helper needs an explicit counter-account type for {intent}')
    counter_account = Account(user_id=user_id, name=f'{account_type.value.title()} - Reviewed Test {transaction.id}', type=account_type, currency=transaction.currency); db.add(counter_account); await db.flush(); decision = DispositionPolicy().decide(StatementTransaction(transaction_id=transaction.id, transaction_date=transaction.txn_date, amount=transaction.amount, currency=transaction.currency, direction=transaction.direction, description=transaction.description), proposal=IntentProposal(schema_version='1', policy_version='reviewed-test-v1', origin=IntentProposalOrigin.REVIEWED_RULE, intent=intent, category='TEST', confidence=Decimal('1'), evidence=('reviewed-test',)), context=DispositionContext(counter_account_id=counter_account.id), mode=DispositionMode.ENFORCE); return (decision, counter_account)
async def anchored_reviewed_posting_inputs(db: AsyncSession, *, user_id, transaction: AtomicTransaction, intent: EconomicIntent) -> tuple[DispositionDecision, Account, TraceRecord, TraceEmitter]: decision, counter_account = await reviewed_posting_inputs(db, user_id=user_id, transaction=transaction, intent=intent); proposal = IntentProposal(schema_version='1', policy_version='reviewed-test-v1', origin=IntentProposalOrigin.REVIEWED_RULE, intent=intent, category='TEST', confidence=Decimal('1'), evidence=('reviewed-test',)); statement_transaction = StatementTransaction(transaction_id=transaction.id, transaction_date=transaction.txn_date, amount=transaction.amount, currency=transaction.currency, direction=transaction.direction, description=transaction.description); emitter = compose_statement_posting_dependencies().trace_emitter_factory(db); records = await emit_disposition_trace_records(emitter=emitter, user_id=user_id, execution_id=f'test-reviewed-statement:{transaction.id}', occurred_at=datetime.now(UTC), transaction=statement_transaction, proposal=proposal, decision=decision); return (decision, counter_account, records[-1], emitter)
async def parse_and_load_statement_projection(service: ExtractionService, *, db: AsyncSession, user_id, source: DocumentSource, institution: str | None, file_type: str='pdf', account_id=None, force_model: str | None=None) -> tuple[StatementExtractionResult, StatementSummary, list[AtomicTransaction]]: result = await service.parse_document(source, institution=institution, user_id=user_id, file_type=file_type, account_id=account_id, force_model=force_model, db=db); statement = (await db.execute(select(StatementSummary).where(StatementSummary.user_id == user_id).where(StatementSummary.file_hash == result.source_content_digest))).scalar_one(); transactions = await resolve_statement_transactions(db, statement); return (result, statement, transactions)


async def run_for(db: AsyncSession, statement_id) -> UUID:
    """Create and commit the requested extract run that a ParseJob of an existing statement names (#2994)."""
    from src.extraction import RunActorKind, RunHints, RunKind, RunTrigger, create_run

    user_id = await db.scalar(select(StatementSummary.user_id).where(StatementSummary.id == statement_id))
    run = await create_run(
        db,
        statement_id=statement_id,
        user_id=user_id,
        kind=RunKind.EXTRACT,
        actor_kind=RunActorKind.SYSTEM,
        trigger=RunTrigger.UPLOAD,
        hints=RunHints(),
    )
    run_id = run.id
    await db.commit()
    return run_id


async def classify_run_for(db: AsyncSession, statement_id, *, parent_run_id=None) -> UUID:
    """Create and commit the requested classify run that the worker creates after an extract run (#2994, S3)."""
    from src.extraction import RunActorKind, RunHints, RunKind, RunTrigger, create_run

    user_id = await db.scalar(select(StatementSummary.user_id).where(StatementSummary.id == statement_id))
    run = await create_run(
        db,
        statement_id=statement_id,
        user_id=user_id,
        kind=RunKind.CLASSIFY,
        actor_kind=RunActorKind.SYSTEM,
        trigger=RunTrigger.AUTO_CLASSIFY,
        hints=RunHints(),
        parent_run_id=parent_run_id,
    )
    run_id = run.id
    await db.commit()
    return run_id


async def classify_statement(db: AsyncSession, statement_id, **options) -> UUID:
    """Create a classify run for a seeded statement and execute it as the worker does. Return the run id."""
    from src.extraction.extension.statement_classification_run import execute_classify_run

    run_id = await classify_run_for(db, statement_id)
    await execute_classify_run(
        create_session_maker_from_db(db), run_id=run_id, posting_dependencies=compose_statement_posting_dependencies(), **options
    )
    return run_id


async def classify_rows(db: AsyncSession, user_id, transactions) -> None:
    """Apply the stored rules and ask the model for the rows, as the classify run does before a test posts (#2994)."""
    from src.extraction import classify_by_effective_policy

    await classify_by_effective_policy(db, user_id, list(transactions))
    await db.flush()


async def classify_statement_rows(db: AsyncSession, statement) -> None:
    """Classify the rows of a statement before a test approves it: the approve no longer asks the model (#2994)."""
    from src.extraction import resolve_statement_transactions

    await classify_rows(db, statement.user_id, await resolve_statement_transactions(db, statement))
