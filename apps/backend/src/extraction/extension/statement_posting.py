"""Stage 1 statement posting guards and auto-approval helpers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import (
    STATEMENT_BALANCE_TOLERANCE,
    STATEMENT_SOURCE_TYPES,
    JournalEntrySourceType,
    TraceEmitter,
    TraceRecord,
    TraceResult,
)
from src.audit.money.currency import normalize_currency_code
from src.config_app import get_effective_base_currency
from src.extraction.base.disposition import (
    DispositionContext,
    DispositionDecision,
    DispositionMode,
    DispositionPolicy,
    DispositionStatus,
    EconomicIntent,
    IntentProposal,
    IntentProposalOrigin,
    StatementTransaction,
    intent_matches_counter_account,
)
from src.extraction.base.source_vocabulary import (
    BankStatementStatus,
    ClassificationStatus,
    RuleType,
    Stage1Status,
)
from src.extraction.base.types import (
    StatementIngestionConfigurationError,
    StatementPostingOutcome,
    StatementPostingStatus,
    extract_source_document_ids,
)
from src.extraction.base.validation import (
    HIGH_CONFIDENCE_AUTO_APPROVE_THRESHOLD,
    STATEMENT_RESOLVED_TRANSACTIONS_ATTR,
)
from src.extraction.extension.ai_settings import auto_accept_enabled
from src.extraction.extension.custody_binding import is_bank_custody_source, resolve_bank_custody_account
from src.extraction.extension.disposition_policy import (
    current_statement_disposition_policy_snapshot,
    statement_disposition_policy_for_user,
)
from src.extraction.extension.disposition_trace import DispositionTraceInput, emit_disposition_trace_records_many
from src.extraction.extension.review_queue import (
    StatementEntryRequest,
    create_entries_from_txns,
    resolve_secondary_currency_custody_account,
)
from src.extraction.extension.reviewed_statement_envelope import get_current_statement_extraction_result
from src.extraction.extension.statement_validation import (
    BalanceChainValidationError,
    approve_statement_with_transactions,
    resolve_statement_transactions,
)
from src.extraction.extension.transaction_classification import (
    classification_suggestions,
    classify_statement_by_effective_policy,
    try_lock_statement_classification,
)
from src.extraction.extension.transaction_membership import effective_statement_transaction_filter
from src.extraction.orm.layer1 import UploadedDocument
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.layer3 import ClassificationRule, TransactionClassification
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryAuthorityState,
    JournalEntryStatus,
    JournalLine,
    ValidationError,
    account_service,
    active_journal_entry_filter,
    current_anchored_journal_entries,
    fit_journal_memo,
    initialize_opening_positions,
    list_opening_positions,
    submit_system_journal_entry,
    void_journal_entry,
)
from src.observability import get_logger
from src.pricing import ExchangeRateLookup

logger = get_logger(__name__)

TransferExclusionsProvider = Callable[[AsyncSession, Sequence[UUID]], Awaitable[set[UUID]]]
TraceEmitterFactory = Callable[[AsyncSession], TraceEmitter]
NamedTransferPoster = Callable[[AsyncSession, UUID, Sequence[AtomicTransaction]], Awaitable[int]]
ReconciliationRelease = Callable[[AsyncSession, UUID, Sequence[UUID], str], Awaitable[int]]

ECONOMIC_REVIEW_NOTICE = "Economic review required:"


@dataclass(frozen=True, slots=True, kw_only=True)
class StatementPostingDependencies:
    """Cross-domain reads required to turn approved statement facts into entries."""

    transfer_exclusions: TransferExclusionsProvider
    fx_rate_provider: ExchangeRateLookup
    fx_rate_error: type[Exception]
    trace_emitter_factory: TraceEmitterFactory
    disposition_mode: DispositionMode
    post_named_transfers: NamedTransferPoster | None = None
    release_reconciliation: ReconciliationRelease | None = None

    def __post_init__(self) -> None:
        for name in (
            "transfer_exclusions",
            "fx_rate_provider",
            "fx_rate_error",
            "trace_emitter_factory",
            "disposition_mode",
        ):
            if getattr(self, name) is None:
                raise StatementIngestionConfigurationError(f"Missing statement posting dependency: {name}")
        if not isinstance(self.disposition_mode, DispositionMode):
            raise StatementIngestionConfigurationError("Statement disposition mode must be explicit")


def is_high_confidence_auto_approve_candidate(statement: StatementSummary) -> bool:
    return (
        statement.status == BankStatementStatus.APPROVED
        and statement.balance_validated is True
        and statement.confidence_score is not None
        and statement.confidence_score >= HIGH_CONFIDENCE_AUTO_APPROVE_THRESHOLD
    )


def _clear_economic_review_notice(statement: StatementSummary) -> None:
    if statement.validation_error and statement.validation_error.startswith(ECONOMIC_REVIEW_NOTICE):
        statement.validation_error = None


async def posted_entry_txn_ids(db: AsyncSession, user_id: UUID, txn_ids: Sequence[UUID]) -> set[UUID]:
    result = await db.execute(
        current_anchored_journal_entries(
            user_id=user_id,
            target_kind="journal_command",
            target_ids={f"statement-transaction:{txn_id}" for txn_id in txn_ids},
        ).where(JournalEntry.status != JournalEntryStatus.VOID)
    )
    wanted = set(txn_ids)
    return {entry.source_id for entry in result.scalars().all() if entry.source_id in wanted}


async def auto_create_posted_entries_for_statement(
    db: AsyncSession,
    statement: StatementSummary,
    user_id: UUID,
    *,
    dependencies: StatementPostingDependencies,
    transactions: list[AtomicTransaction] | None = None,
) -> StatementPostingOutcome:
    """Evaluate then apply one statement posting plan after Stage 1 source confirmation."""
    if transactions is None:
        transactions = getattr(statement, STATEMENT_RESOLVED_TRANSACTIONS_ATTR, None)
    if transactions is None:
        transactions = await resolve_statement_transactions(db, statement)
    txn_ids = [txn.id for txn in transactions]
    if not txn_ids:
        _clear_economic_review_notice(statement)
        return StatementPostingOutcome(status=StatementPostingStatus.POSTED, created_count=0)

    existing_entry_txn_ids = await posted_entry_txn_ids(db, user_id, txn_ids)
    legacy_result = await db.execute(
        select(JournalEntry.id)
        .where(
            JournalEntry.user_id == user_id,
            JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES),
            JournalEntry.source_id.in_(txn_ids),
            JournalEntry.decision_authority_state == JournalEntryAuthorityState.LEGACY_UNPROVEN,
            JournalEntry.status != JournalEntryStatus.VOID,
        )
        .limit(1)
    )
    if legacy_result.scalar_one_or_none() is not None:
        statement.status = BankStatementStatus.PARSED
        statement.stage1_status = Stage1Status.PENDING_REVIEW
        statement.validation_error = f"{ECONOMIC_REVIEW_NOTICE} legacy_unanchored_source_entry"
        await db.flush()
        return StatementPostingOutcome(
            status=StatementPostingStatus.REVIEW_REQUIRED,
            created_count=0,
            review_reasons=("legacy_unanchored_source_entry",),
        )

    transfer_txn_ids = await dependencies.transfer_exclusions(db, txn_ids)
    txns_to_post = [txn for txn in transactions if txn.id not in existing_entry_txn_ids]
    if not txns_to_post:
        _clear_economic_review_notice(statement)
        return StatementPostingOutcome(status=StatementPostingStatus.POSTED, created_count=0)

    preloaded_bank_account = await resolve_statement_posting_account(db, statement, user_id)
    await validate_statement_period_unique(db, statement, user_id, preloaded_bank_account.id)

    await classify_statement_by_effective_policy(db, user_id, statement.id, txns_to_post)
    legs_posted = 0
    if dependencies.post_named_transfers is not None and dependencies.disposition_mode is DispositionMode.ENFORCE:
        if await auto_accept_enabled(db, user_id):
            legs_posted = await dependencies.post_named_transfers(db, user_id, txns_to_post)
            transfer_txn_ids = await dependencies.transfer_exclusions(db, txn_ids)
        else:
            suggestions = await classification_suggestions(db, [txn.id for txn in txns_to_post])
            user_transfer_txns = [
                txn
                for txn in txns_to_post
                if (s := suggestions.get(txn.id)) is not None and s.corrected and s.booking == "processing_leg"
            ]
            if user_transfer_txns:
                legs_posted = await dependencies.post_named_transfers(db, user_id, user_transfer_txns)
                transfer_txn_ids = await dependencies.transfer_exclusions(db, txn_ids)

    base_currency = await get_effective_base_currency(db, user_id=user_id)
    policy = await statement_disposition_policy_for_user(db, user_id)
    policy_snapshot = current_statement_disposition_policy_snapshot(mode=dependencies.disposition_mode, policy=policy)
    planned: list[
        tuple[AtomicTransaction, IntentProposal | None, DispositionDecision, Account | None, StatementTransaction]
    ] = []

    classification_by_txn_id, accounts_by_id = await _applied_classifications(db, [txn.id for txn in txns_to_post])
    for txn in txns_to_post:
        pair = classification_by_txn_id.get(txn.id)
        classification, classification_rule = pair if pair is not None else (None, None)
        counter_account = None
        proposal = None
        if classification is not None and classification.account_id is not None and classification_rule is not None:
            counter_account = accounts_by_id.get(classification.account_id)
            if counter_account is None:
                raise ValueError("Applied classification references a missing account")
            proposal = _applied_proposal(
                classification, classification_rule, counter_account, covered_by_match=txn.id in transfer_txn_ids
            )
        elif txn.id in transfer_txn_ids:
            proposal = IntentProposal(
                schema_version="1",
                policy_version="reconciliation-match-v1",
                origin=IntentProposalOrigin.RECONCILIATION_FACT,
                intent=EconomicIntent.TRANSFER,
                category=None,
                confidence=Decimal("1"),
                evidence=("accepted-transfer-match",),
            )

        transaction = StatementTransaction(
            transaction_id=txn.id,
            transaction_date=txn.txn_date,
            amount=txn.amount,
            currency=txn.currency,
            direction=txn.direction,
            description=txn.description,
        )
        decision = policy.decide(
            transaction,
            proposal=proposal,
            context=DispositionContext(
                accepted_transfer_match=txn.id in transfer_txn_ids,
                counter_account_id=counter_account.id if counter_account else None,
                counter_account_type=counter_account.type.value if counter_account else None,
            ),
            mode=dependencies.disposition_mode,
        )
        planned.append((txn, proposal, decision, counter_account, transaction))

    result_payload = (statement.extraction_metadata or {}).get("statement_extraction_result")
    result_id = result_payload.get("result_id") if isinstance(result_payload, dict) else None
    occurred_at = statement.created_at or datetime.now(UTC)
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)
    emitter = dependencies.trace_emitter_factory(db)
    source_decisions: dict[UUID, TraceRecord] = {}
    disposition_records = await emit_disposition_trace_records_many(
        emitter=emitter,
        user_id=user_id,
        execution_id=f"statement:{statement.id}:result:{result_id or statement.file_hash}",
        occurred_at=occurred_at,
        inputs=[
            DispositionTraceInput(transaction=transaction, proposal=proposal, decision=decision)
            for _txn, proposal, decision, _counter_account, transaction in planned
        ],
        policy_snapshot=policy_snapshot,
    )
    for (txn, *_rest), records in zip(planned, disposition_records, strict=True):
        if records and records[-1].result is TraceResult.AUTHORITATIVE:
            source_decisions[txn.id] = records[-1]

    review_reasons = [
        decision.reason_code
        for _txn, _proposal, decision, _counter_account, _transaction in planned
        if decision.status is DispositionStatus.REVIEW
    ]
    review_reasons.extend(
        "source_authority_missing"
        for txn, _proposal, decision, _counter_account, _transaction in planned
        if decision.should_apply and txn.id not in source_decisions
    )
    if dependencies.disposition_mode is not DispositionMode.ENFORCE:
        review_reasons.extend(
            f"authoritative_command_not_applied_in_{dependencies.disposition_mode.value}"
            for _txn, _proposal, decision, _counter_account, _transaction in planned
            if decision.status is DispositionStatus.AUTHORITATIVE
        )
    if review_reasons:
        statement.status = BankStatementStatus.PARSED
        statement.stage1_status = Stage1Status.PENDING_REVIEW
        normalized_reasons = tuple(sorted(set(review_reasons)))
        statement.validation_error = f"{ECONOMIC_REVIEW_NOTICE} {', '.join(normalized_reasons)}"[:500]
        await db.flush()
        return StatementPostingOutcome(
            status=StatementPostingStatus.REVIEW_REQUIRED,
            created_count=legs_posted,
            review_reasons=normalized_reasons,
        )

    requests: list[StatementEntryRequest] = []
    for txn, proposal, decision, counter_account, _transaction in planned:
        if decision.status is DispositionStatus.ALREADY_COVERED:
            continue
        if not decision.should_apply:
            raise RuntimeError("Disposition command reached application without enforce authority")
        source_decision = source_decisions.get(txn.id)
        if source_decision is None:
            raise RuntimeError("authoritative disposition is missing its source decision")
        requests.append(
            StatementEntryRequest(
                txn=txn,
                disposition=decision,
                counter_account=counter_account,
                source_decision=source_decision,
                source_type=(
                    JournalEntrySourceType.USER_CONFIRMED
                    if proposal is not None and proposal.origin is IntentProposalOrigin.MANUAL_ADJUDICATION
                    else JournalEntrySourceType.AUTO_PARSED
                ),
            )
        )
    entries = await create_entries_from_txns(
        db,
        requests,
        user_id=user_id,
        base_currency=base_currency,
        auto_post=True,
        preloaded_statement=statement,
        preloaded_bank_account=preloaded_bank_account,
        fx_rate_provider=dependencies.fx_rate_provider,
        fx_rate_error=dependencies.fx_rate_error,
        trace_emitter=emitter,
    )
    postings = [(entry, request.txn) for entry, request in zip(entries, requests, strict=True)]
    if postings:
        try:
            from src.extraction.extension.evidence_graph_integration import EvidenceGraphIntegrationService

            async with db.begin_nested():
                await EvidenceGraphIntegrationService().record_journal_postings_batch(
                    db, user_id=user_id, postings=postings
                )
        except Exception as evidence_exc:
            logger.warning(
                "Evidence-graph journal-posting batch lineage failed (posting continues)",
                extra={
                    "error": str(evidence_exc),
                    "error_type": type(evidence_exc).__name__,
                    "user_id": str(user_id),
                    "statement_id": str(statement.id),
                },
            )

    _clear_economic_review_notice(statement)
    return StatementPostingOutcome(status=StatementPostingStatus.POSTED, created_count=legs_posted + len(postings))


async def _applied_classifications(
    db: AsyncSession, txn_ids: Sequence[UUID]
) -> tuple[dict[UUID, tuple[TransactionClassification, ClassificationRule]], dict[UUID, Account]]:
    classification_by_txn_id: dict[UUID, tuple[TransactionClassification, ClassificationRule]] = {}
    accounts_by_id: dict[UUID, Account] = {}
    if not txn_ids:
        return classification_by_txn_id, accounts_by_id
    rows = (
        await db.execute(
            select(TransactionClassification, ClassificationRule)
            .join(ClassificationRule, TransactionClassification.rule_version_id == ClassificationRule.id)
            .where(
                TransactionClassification.atomic_txn_id.in_(list(txn_ids)),
                TransactionClassification.status == ClassificationStatus.APPLIED,
            )
            .order_by(
                case(
                    (ClassificationRule.rule_type.in_((RuleType.KEYWORD_MATCH, RuleType.REGEX_MATCH)), 0),
                    else_=1,
                ),
                TransactionClassification.created_at.desc(),
            )
        )
    ).all()
    for cl, rule in rows:
        classification_by_txn_id.setdefault(cl.atomic_txn_id, (cl, rule))

    needed_account_ids = {cl.account_id for cl, _ in classification_by_txn_id.values() if cl.account_id is not None}
    if needed_account_ids:
        accounts_res = await db.execute(select(Account).where(Account.id.in_(needed_account_ids)))
        accounts_by_id = {acc.id: acc for acc in accounts_res.scalars().all()}
    return classification_by_txn_id, accounts_by_id


def _applied_proposal(
    classification: TransactionClassification,
    classification_rule: ClassificationRule,
    counter_account: Account,
    *,
    covered_by_match: bool = False,
) -> IntentProposal:
    corrected_by_user = (classification.tags or {}).get("corrected_by_user") is True
    if corrected_by_user and covered_by_match:
        logger.warning(
            "A correction of the user conflicts with an accepted match; the match stays",
            classification_id=str(classification.id),
        )
        corrected_by_user = False
    return IntentProposal(
        schema_version="1",
        policy_version=str(classification.rule_version_id),
        origin=(
            IntentProposalOrigin.MANUAL_ADJUDICATION
            if corrected_by_user
            else _classification_proposal_origin(classification_rule.rule_type)
        ),
        intent=_classification_intent(classification, counter_account),
        category=str((classification.tags or {}).get("category") or "") or None,
        confidence=None if corrected_by_user else Decimal(classification.confidence_score or 0) / Decimal("100"),
        evidence=(str(classification.id),),
    )


async def applied_rows_the_policy_accepts(
    db: AsyncSession,
    transactions: Sequence[AtomicTransaction],
    *,
    mode: DispositionMode,
    policy: DispositionPolicy | None = None,
) -> set[UUID]:
    classification_by_txn_id, accounts_by_id = await _applied_classifications(db, [txn.id for txn in transactions])
    policy = policy or DispositionPolicy()
    accepted: set[UUID] = set()
    for txn in transactions:
        pair = classification_by_txn_id.get(txn.id)
        if pair is None or pair[0].account_id is None:
            continue
        counter_account = accounts_by_id.get(pair[0].account_id)
        if counter_account is None:
            continue
        decision = policy.decide(
            StatementTransaction(
                transaction_id=txn.id,
                transaction_date=txn.txn_date,
                amount=txn.amount,
                currency=txn.currency,
                direction=txn.direction,
                description=txn.description,
            ),
            proposal=_applied_proposal(pair[0], pair[1], counter_account),
            context=DispositionContext(
                counter_account_id=counter_account.id,
                counter_account_type=counter_account.type.value,
            ),
            mode=mode,
        )
        if decision.status is DispositionStatus.AUTHORITATIVE and decision.should_apply:
            accepted.add(txn.id)
    return accepted


def _classification_intent(classification: TransactionClassification, counter_account: Account) -> EconomicIntent:
    tags = classification.tags if isinstance(classification.tags, dict) else {}
    tagged_intent = tags.get("intent")
    if tagged_intent is not None:
        try:
            intent = EconomicIntent(str(tagged_intent))
        except ValueError:
            return EconomicIntent.UNKNOWN
        return intent if intent_matches_counter_account(intent, counter_account.type.value) else EconomicIntent.UNKNOWN
    if counter_account.type is AccountType.INCOME:
        return EconomicIntent.INCOME
    if counter_account.type is AccountType.EXPENSE:
        return EconomicIntent.EXPENSE
    return EconomicIntent.UNKNOWN


def _classification_proposal_origin(rule_type: RuleType) -> IntentProposalOrigin:
    if rule_type in {RuleType.KEYWORD_MATCH, RuleType.REGEX_MATCH}:
        return IntentProposalOrigin.REVIEWED_RULE
    if rule_type is RuleType.ML_MODEL:
        return IntentProposalOrigin.LIVE_LLM
    raise StatementIngestionConfigurationError(f"Unsupported classification rule type: {rule_type}")


async def resolve_statement_posting_account(
    db: AsyncSession, statement: StatementSummary, user_id: UUID
) -> Account:
    currency = normalize_currency_code(statement.currency or "")
    if not currency:
        raise ValueError("Statement currency required before posting. Confirm the source currency before posting.")

    source = await get_current_statement_extraction_result(db, user_id=user_id, statement_id=statement.id)
    document = (
        await db.get(UploadedDocument, statement.uploaded_document_id) if statement.uploaded_document_id else None
    )
    if is_bank_custody_source(source, document) and statement.institution and statement.account_last4:
        resolved_account = await resolve_bank_custody_account(
            db,
            user_id=user_id,
            institution=statement.institution,
            account_last4=statement.account_last4,
            currency=currency,
            account_id=statement.account_id,
            create_if_missing=False,
        )
        statement.account_id = resolved_account.id
        await db.flush()
        return resolved_account

    if statement.account_id:
        account = (
            await db.execute(select(Account).where(Account.id == statement.account_id, Account.user_id == user_id))
        ).scalar_one_or_none()
        if account is None:
            raise ValueError("Statement account mapping is invalid. Confirm the target account before posting.")
        if account.type != AccountType.ASSET or not account.is_active:
            raise ValueError(
                "Statement account mapping must reference an active asset account. "
                "Confirm the target account before posting."
            )
        if account.currency != currency:
            raise ValueError(
                "Statement account mapping must match the statement currency. "
                "Confirm the target account before posting."
            )
        return account

    if not (statement.institution or "").strip() or not (statement.account_last4 or "").strip():
        raise ValueError(
            "Account mapping required before posting. Confirm the statement account because institution, "
            "account_last4, or currency metadata is missing."
        )
    raise ValueError("Account mapping required before posting. Confirm the statement custody identity.")


async def validate_statement_period_unique(
    db: AsyncSession, statement: StatementSummary, user_id: UUID, account_id: UUID
) -> None:
    if statement.period_start is None or statement.period_end is None:
        raise ValueError("Statement period required before posting. Confirm the source date range before posting.")
    if statement.period_start > statement.period_end:
        raise ValueError("Statement period is invalid. Confirm the source date range before posting.")

    currency = normalize_currency_code(statement.currency or "")
    if not currency:
        raise ValueError("Statement currency required before posting. Confirm the source currency before posting.")

    overlapping = (
        await db.execute(
            select(StatementSummary)
            .where(
                StatementSummary.user_id == user_id,
                StatementSummary.id != statement.id,
                StatementSummary.account_id == account_id,
                StatementSummary.status == BankStatementStatus.APPROVED,
                func.upper(StatementSummary.currency) == currency,
                StatementSummary.period_start.is_not(None),
                StatementSummary.period_end.is_not(None),
                StatementSummary.period_start <= statement.period_end,
                StatementSummary.period_end >= statement.period_start,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if overlapping:
        raise ValueError(
            "Statement period overlaps an approved statement for this account and currency. "
            "Resolve the duplicate source date range before posting."
        )


def _signed_line_amount(line: JournalLine, *, debit_normal: bool) -> Decimal:
    return line.amount if (line.direction == Direction.DEBIT) == debit_normal else -line.amount


async def _rows_kept_by_other_statements(
    db: AsyncSession,
    statement: StatementSummary,
    user_id: UUID,
    transactions: Sequence[AtomicTransaction],
    *,
    was_approved: bool,
) -> set[UUID]:
    document_ids = {doc_id for txn in transactions for doc_id in extract_source_document_ids(txn.source_documents)}
    if not document_ids:
        return set()
    other_statement_ids = (
        await db.execute(
            select(StatementSummary.id).where(
                StatementSummary.user_id == user_id,
                StatementSummary.id != statement.id,
                StatementSummary.uploaded_document_id.in_(document_ids),
            )
        )
    ).scalars()
    row_ids = [txn.id for txn in transactions]
    kept: set[UUID] = set()
    for other_statement_id in other_statement_ids.all():
        members = await db.execute(
            select(AtomicTransaction.id).where(
                AtomicTransaction.id.in_(row_ids),
                effective_statement_transaction_filter(
                    user_id, other_statement_id, include_pending_stage1=not was_approved
                ),
            )
        )
        kept.update(members.scalars().all())
    return kept


async def statement_owned_transaction_ids(
    db: AsyncSession,
    statement: StatementSummary,
    user_id: UUID,
    *,
    was_approved: bool,
    tolerate_unresolved_rows: bool = False,
) -> list[UUID]:
    try:
        transactions = await resolve_statement_transactions(db, statement)
    except ValueError as exc:
        if not tolerate_unresolved_rows:
            raise
        logger.warning(
            "statement.release.skipped_unresolved_rows",
            statement_id=str(statement.id),
            error_type=type(exc).__name__,
        )
        return []
    if not transactions:
        return []
    kept = await _rows_kept_by_other_statements(db, statement, user_id, transactions, was_approved=was_approved)
    return [txn.id for txn in transactions if txn.id not in kept]


async def _void_reconciled_entry(
    db: AsyncSession, entry_id: UUID, *, user_id: UUID, base_currency: str, reason: str
) -> None:
    await void_journal_entry(
        db, entry_id, reason=reason, user_id=user_id, allow_reconciled=True, base_currency=base_currency
    )


async def _void_entries_of_transactions(
    db: AsyncSession, user_id: UUID, txn_ids: Sequence[UUID], *, reason: str
) -> int:
    if not txn_ids:
        return 0
    base_currency = await get_effective_base_currency(db, user_id=user_id)
    active_entries = (
        (
            await db.execute(
                select(JournalEntry)
                .where(
                    JournalEntry.user_id == user_id,
                    JournalEntry.source_id.in_(txn_ids),
                    JournalEntry.source_type.in_((*STATEMENT_SOURCE_TYPES, JournalEntrySourceType.SYSTEM)),
                    JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]),
                    ~JournalEntry.memo.startswith("VOID: "),
                )
                .order_by(JournalEntry.entry_date, JournalEntry.id)
            )
        )
        .scalars()
        .all()
    )
    for entry in active_entries:
        await _void_reconciled_entry(db, entry.id, user_id=user_id, base_currency=base_currency, reason=reason)
    return len(active_entries)


async def release_statement_ledger_effects(
    db: AsyncSession,
    statement: StatementSummary,
    user_id: UUID,
    *,
    was_approved: bool,
    reason: str,
    dependencies: StatementPostingDependencies | None,
    tolerate_unresolved_rows: bool = False,
) -> int:
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"statement-release:{user_id}"}
    )
    owned = await statement_owned_transaction_ids(
        db, statement, user_id, was_approved=was_approved, tolerate_unresolved_rows=tolerate_unresolved_rows
    )
    if not owned:
        return 0
    if dependencies is not None and dependencies.release_reconciliation is not None:
        await dependencies.release_reconciliation(db, user_id, owned, reason)
    return await _void_entries_of_transactions(db, user_id, owned, reason=reason)


async def _active_gap_plug_entries_for_account(
    db: AsyncSession, user_id: UUID, account_id: UUID
) -> list[tuple[JournalEntry, JournalLine]]:
    rows = (
        await db.execute(
            select(JournalEntry, JournalLine)
            .join(JournalLine, JournalLine.journal_entry_id == JournalEntry.id)
            .where(
                JournalEntry.user_id == user_id,
                JournalEntry.source_type == JournalEntrySourceType.SYSTEM,
                JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]),
                ~JournalEntry.memo.startswith("VOID: "),
                JournalLine.account_id == account_id,
                JournalLine.event_type == account_service.CROSS_PERIOD_GAP_PLUG_EVENT_TYPE,
            )
            .order_by(JournalEntry.entry_date, JournalEntry.id)
        )
    ).all()
    return [(entry, line) for entry, line in rows]


async def _non_plug_account_movement_between(
    db: AsyncSession,
    user_id: UUID,
    account: Account,
    *,
    after_date: date,
    before_date: date,
    opening_entry_ids: set[UUID],
) -> Decimal:
    if before_date <= after_date + timedelta(days=1):
        return Decimal("0")
    rows = (
        await db.execute(
            select(JournalEntry, JournalLine)
            .join(JournalLine, JournalLine.journal_entry_id == JournalEntry.id)
            .where(
                JournalEntry.user_id == user_id,
                active_journal_entry_filter(JournalEntry),
                JournalLine.account_id == account.id,
                JournalEntry.entry_date > after_date,
                JournalEntry.entry_date < before_date,
            )
        )
    ).all()
    debit_normal = account.type in (AccountType.ASSET, AccountType.EXPENSE)
    return sum(
        (
            _signed_line_amount(line, debit_normal=debit_normal)
            for entry, line in rows
            if entry.id not in opening_entry_ids and line.event_type != account_service.CROSS_PERIOD_GAP_PLUG_EVENT_TYPE
        ),
        Decimal("0"),
    )


async def _lookup_fx_rate(
    db: AsyncSession,
    *,
    currency: str,
    base_currency: str,
    as_of: date,
    dependencies: StatementPostingDependencies | None,
    error_message: str,
    require_provider: bool = False,
) -> Decimal:
    if dependencies is not None:
        try:
            return await dependencies.fx_rate_provider(db, currency, base_currency, as_of, lazy_load=True)
        except dependencies.fx_rate_error as exc:
            raise ValueError(error_message) from exc
    if require_provider:
        raise ValueError("FX rate provider required for statement opening balance")
    from src.pricing import PricingError, get_exchange_rate

    try:
        return await get_exchange_rate(db, currency, base_currency, as_of, lazy_load=True)
    except PricingError as exc:
        raise ValueError(error_message) from exc


async def reconcile_account_statement_chain(
    db: AsyncSession,
    user_id: UUID,
    account_id: UUID,
    *,
    dependencies: StatementPostingDependencies | None = None,
    candidate_statement: StatementSummary | None = None,
) -> bool:
    """Idempotently anchor S_0 to 3199 and calibrate inter-statement gaps to 3198."""
    from src.audit.money import to_money
    from src.extraction.extension.statement_contribution import resolve_statement_contribution

    account = await db.scalar(select(Account).where(Account.id == account_id, Account.user_id == user_id))
    if account is None:
        return False

    approved_rows = list(
        (
            await db.execute(
                select(StatementSummary)
                .where(
                    StatementSummary.user_id == user_id,
                    StatementSummary.account_id == account_id,
                    StatementSummary.status == BankStatementStatus.APPROVED,
                    StatementSummary.period_start.is_not(None),
                )
                .order_by(
                    StatementSummary.period_start.asc(), StatementSummary.period_end.asc(), StatementSummary.id.asc()
                )
            )
        )
        .scalars()
        .all()
    )
    if (
        candidate_statement is not None
        and candidate_statement.account_id == account_id
        and candidate_statement.period_start is not None
        and candidate_statement.effective_opening_balance() is not None
        and all(row.id != candidate_statement.id for row in approved_rows)
        and candidate_statement.status != BankStatementStatus.RETIRED
    ):
        approved_rows.append(candidate_statement)
        approved_rows.sort(key=StatementSummary.chain_sort_key)

    base_currency = await get_effective_base_currency(db, user_id=user_id)
    existing_plugs = await _active_gap_plug_entries_for_account(db, user_id, account_id)
    positions = await list_opening_positions(db, user_id=user_id, as_of=date.max)
    existing_opening = next((p for p in positions if p.account_id == account_id), None)

    if not approved_rows:
        changed = False
        for entry, _line in existing_plugs:
            await _void_reconciled_entry(
                db,
                entry.id,
                user_id=user_id,
                base_currency=base_currency,
                reason="All statements for account retired or rejected",
            )
            changed = True
        if existing_opening is not None and existing_opening.journal_entry_id is not None:
            entry_obj = await db.get(JournalEntry, existing_opening.journal_entry_id)
            if existing_opening.source_decision is not None or (
                entry_obj is not None and entry_obj.memo == "Opening balance (statement import)"
            ):
                await _void_reconciled_entry(
                    db,
                    existing_opening.journal_entry_id,
                    user_id=user_id,
                    base_currency=base_currency,
                    reason="All statements for account retired or rejected",
                )
                changed = True
        return changed

    earliest = approved_rows[0]
    earliest_opening = earliest.effective_opening_balance()
    if earliest_opening is None or earliest.period_start is None:
        raise ValueError("Statement opening balance, date, and account are required before posting")

    currency = normalize_currency_code(earliest.currency or account.currency or "")
    changed = False

    need_opening_post = True
    allow_supersede = False
    if existing_opening is not None:
        if existing_opening.state != "authoritative":
            raise ValueError("Opening balance authority needs review")
        if existing_opening.effective_date < earliest.period_start:
            existing_entry_obj = (
                await db.get(JournalEntry, existing_opening.journal_entry_id)
                if existing_opening.journal_entry_id is not None
                else None
            )
            is_statement_import_opening = existing_opening.source_decision is not None or (
                existing_entry_obj is not None and existing_entry_obj.memo == "Opening balance (statement import)"
            )
            inactive_at_existing = await db.scalar(
                select(StatementSummary.id)
                .where(
                    StatementSummary.user_id == user_id,
                    StatementSummary.account_id == account_id,
                    StatementSummary.status.in_((BankStatementStatus.RETIRED, BankStatementStatus.REJECTED)),
                    StatementSummary.period_start == existing_opening.effective_date,
                )
                .limit(1)
            )
            if is_statement_import_opening and inactive_at_existing is not None:
                allow_supersede = True
            else:
                need_opening_post = False
        elif existing_opening.effective_date == earliest.period_start:
            if abs(earliest_opening - existing_opening.amount) <= STATEMENT_BALANCE_TOLERANCE:
                need_opening_post = False
            elif earliest.manual_opening_balance is not None:
                allow_supersede = True
            else:
                raise ValueError("Opening balance conflicts with existing opening position for the same date")

    if need_opening_post:
        remaining_plugs: list[tuple[JournalEntry, JournalLine]] = []
        for entry, line in existing_plugs:
            if entry.entry_date < earliest.period_start:
                await _void_reconciled_entry(
                    db,
                    entry.id,
                    user_id=user_id,
                    base_currency=base_currency,
                    reason="Superseded by statement chain reconciliation",
                )
                changed = True
            else:
                remaining_plugs.append((entry, line))
        existing_plugs = remaining_plugs
        source_decision_id = None
        if earliest.current_extraction_result_id is not None:
            contribution = await resolve_statement_contribution(db, user_id=user_id, statement_id=earliest.id)
            if contribution.state != "authoritative" or contribution.decision is None:
                raise ValueError("Statement opening balance requires current source authority")
            source_decision_id = contribution.decision.decision_id
        fx_rates: dict[str, Decimal] = {}
        if currency != base_currency and earliest_opening != 0:
            fx_rates[currency] = await _lookup_fx_rate(
                db,
                currency=currency,
                base_currency=base_currency,
                as_of=earliest.period_start,
                dependencies=dependencies,
                error_message="FX rate required for statement opening balance",
                require_provider=candidate_statement is not None,
            )
        trace_emitter = dependencies.trace_emitter_factory(db) if dependencies is not None else None
        if trace_emitter is None and source_decision_id is not None:
            from src.audit import SqlTraceRecordRepository, TraceDecisionPolicyRegistry
            from src.extraction import extraction_trace_policy_registry
            from src.ledger import ledger_trace_policy_registry

            trace_emitter = TraceEmitter(
                SqlTraceRecordRepository(
                    db,
                    TraceDecisionPolicyRegistry(
                        (*extraction_trace_policy_registry().policies, *ledger_trace_policy_registry().policies)
                    ),
                )
            )
        try:
            await initialize_opening_positions(
                db,
                user_id,
                entry_date=earliest.period_start,
                balances={account_id: earliest_opening},
                currency=currency,
                base_currency=base_currency,
                fx_rates=fx_rates,
                source_decision_id=source_decision_id,
                trace_emitter=trace_emitter,
                memo="Opening balance (statement import)",
                allow_supersede=allow_supersede,
                preserve_account_currency_equity=True,
            )
            changed = True
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc

    updated_positions = await list_opening_positions(db, user_id=user_id, as_of=date.max)
    opening_entry_ids = {p.journal_entry_id for p in updated_positions if p.journal_entry_id is not None}

    desired_plugs: dict[tuple[str, str], tuple[StatementSummary, StatementSummary, date, Decimal]] = {}
    for idx in range(len(approved_rows) - 1):
        s_prev, s_next = approved_rows[idx], approved_rows[idx + 1]
        if s_prev.closing_balance is None or s_prev.period_end is None or s_next.period_start is None:
            continue
        next_open = s_next.effective_opening_balance()
        if next_open is None:
            continue
        non_plug_movement = await _non_plug_account_movement_between(
            db,
            user_id,
            account,
            after_date=s_prev.period_end,
            before_date=s_next.period_start,
            opening_entry_ids=opening_entry_ids,
        )
        delta = to_money(next_open - s_prev.closing_balance - non_plug_movement)
        if abs(delta) > account_service.CROSS_PERIOD_GAP_PLUG_TOLERANCE:
            plug_date = min(
                max(s_prev.period_end + timedelta(days=1), s_next.period_start - timedelta(days=1)),
                s_next.period_start,
            )
            desired_plugs[(str(s_prev.id), str(s_next.id))] = (s_prev, s_next, plug_date, delta)

    debit_normal = account.type in (AccountType.ASSET, AccountType.EXPENSE)
    kept_pairs: set[tuple[str, str]] = set()
    for entry, line in existing_plugs:
        tags = line.tags if isinstance(line.tags, dict) else {}
        pair_key = (str(tags.get("gap_from_statement_id") or ""), str(tags.get("gap_to_statement_id") or ""))
        signed_existing = _signed_line_amount(line, debit_normal=debit_normal)
        desired = desired_plugs.get(pair_key)
        if (
            desired is not None
            and pair_key not in kept_pairs
            and entry.entry_date == desired[2]
            and abs(signed_existing - desired[3]) <= STATEMENT_BALANCE_TOLERANCE
        ):
            kept_pairs.add(pair_key)
            continue
        await _void_reconciled_entry(
            db,
            entry.id,
            user_id=user_id,
            base_currency=base_currency,
            reason="Superseded by statement chain reconciliation",
        )
        changed = True

    for pair_key, (s_prev, s_next, plug_date, delta) in desired_plugs.items():
        if pair_key in kept_pairs:
            continue
        acct_currency = normalize_currency_code(account.currency or currency)
        fx_rate = (
            await _lookup_fx_rate(
                db,
                currency=acct_currency,
                base_currency=base_currency,
                as_of=plug_date,
                dependencies=dependencies,
                error_message=f"FX rate required for cross-period gap plug in {acct_currency}",
            )
            if acct_currency != base_currency
            else None
        )
        gap_equity = await account_service.get_or_create_unexplained_gap_equity_account(db, user_id, acct_currency)
        debit_custody = debit_normal if delta > 0 else not debit_normal
        custody_direction = Direction.DEBIT if debit_custody else Direction.CREDIT
        equity_direction = Direction.CREDIT if debit_custody else Direction.DEBIT
        plug_tags = {
            "gap_from_statement_id": str(s_prev.id),
            "gap_to_statement_id": str(s_next.id),
            "gap_start": s_prev.period_end.isoformat() if s_prev.period_end else "",
            "gap_end": s_next.period_start.isoformat() if s_next.period_start else "",
        }
        line_common = {
            "amount": abs(delta),
            "currency": acct_currency,
            "fx_rate": fx_rate,
            "event_type": account_service.CROSS_PERIOD_GAP_PLUG_EVENT_TYPE,
            "tags": plug_tags,
        }
        await submit_system_journal_entry(
            db,
            user_id=user_id,
            entry_date=plug_date,
            memo=fit_journal_memo(
                f"Unexplained statement gap adjustment ({s_prev.period_end} to {s_next.period_start})"
            ),
            lines_data=[
                {"account_id": account.id, "direction": custody_direction, **line_common},
                {"account_id": gap_equity.id, "direction": equity_direction, **line_common},
            ],
            base_currency=base_currency,
            operation="cross-period-gap",
        )
        changed = True

    return changed


async def _reconcile_secondary_currency_opening_balance(
    db: AsyncSession,
    *,
    statement: StatementSummary,
    user_id: UUID,
    currency: str,
    opening_amount: Decimal,
    dependencies: StatementPostingDependencies | None = None,
) -> bool:
    secondary_account = await resolve_secondary_currency_custody_account(
        db, statement=statement, user_id=user_id, currency=currency
    )
    secondary_candidate = StatementSummary(
        id=statement.id,
        user_id=user_id,
        account_id=secondary_account.id,
        institution=statement.institution,
        account_last4=statement.account_last4,
        currency=currency,
        period_start=statement.period_start,
        period_end=statement.period_end,
        opening_balance=opening_amount,
        closing_balance=statement.closing_balance,
        manual_opening_balance=statement.manual_opening_balance,
        status=statement.status,
        current_extraction_result_id=statement.current_extraction_result_id,
    )
    return await reconcile_account_statement_chain(
        db,
        user_id=user_id,
        account_id=secondary_account.id,
        dependencies=dependencies,
        candidate_statement=secondary_candidate,
    )


async def try_auto_post_statement_opening_balance(
    db: AsyncSession,
    statement: StatementSummary,
    user_id: UUID,
    *,
    dependencies: StatementPostingDependencies | None = None,
) -> bool:
    if statement.effective_opening_balance() is None or statement.period_start is None or statement.account_id is None:
        raise ValueError("Statement opening balance, date, and account are required before posting")
    changed = await reconcile_account_statement_chain(
        db,
        user_id=user_id,
        account_id=statement.account_id,
        dependencies=dependencies,
        candidate_statement=statement,
    )
    typed_balances = statement.typed_currency_balances()
    if len(typed_balances) > 1:
        primary_account = await db.get(Account, statement.account_id)
        primary_currency = normalize_currency_code(
            (primary_account.currency if primary_account is not None else None) or statement.currency or ""
        )
        for balance in typed_balances:
            bucket_currency = balance.currency.code
            if bucket_currency == primary_currency:
                continue
            bucket_changed = await _reconcile_secondary_currency_opening_balance(
                db,
                statement=statement,
                user_id=user_id,
                currency=bucket_currency,
                opening_amount=balance.opening.amount,
                dependencies=dependencies,
            )
            changed = changed or bucket_changed
    return changed


async def try_auto_approve_high_confidence_statement(
    db: AsyncSession,
    statement_id: UUID,
    user_id: UUID,
    *,
    dependencies: StatementPostingDependencies,
) -> int:
    statement = (
        await db.execute(
            select(StatementSummary).where(StatementSummary.id == statement_id, StatementSummary.user_id == user_id)
        )
    ).scalar_one_or_none()
    if statement is None or not is_high_confidence_auto_approve_candidate(statement):
        return 0

    if not await try_lock_statement_classification(db, statement_id):
        statement.status = BankStatementStatus.PARSED
        statement.stage1_status = Stage1Status.PENDING_REVIEW
        await db.flush()
        return 0

    try:
        async with db.begin_nested():
            approved, transactions = await approve_statement_with_transactions(db, statement_id, user_id)
            outcome = await auto_create_posted_entries_for_statement(
                db, approved, user_id, dependencies=dependencies, transactions=transactions
            )
            if outcome.status is not StatementPostingStatus.REVIEW_REQUIRED:
                await try_auto_post_statement_opening_balance(db, approved, user_id, dependencies=dependencies)
            await db.flush()
    except ValueError as exc:
        refreshed = await db.get(StatementSummary, statement_id)
        if refreshed is not None:
            refreshed.status = BankStatementStatus.PARSED
            refreshed.stage1_status = Stage1Status.PENDING_REVIEW
            refreshed.validation_error = str(exc)[:500]
            if isinstance(exc, BalanceChainValidationError):
                refreshed.balance_validated = False
            await db.flush()
        return 0

    return outcome.created_count
