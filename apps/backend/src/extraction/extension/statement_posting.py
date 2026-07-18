"""Stage 1 statement posting guards and auto-approval helpers (DWD conform).

Posting guards now operate on the ``StatementSummary`` envelope and its Layer-2
``AtomicTransaction`` rows (resolved via the linked ODS ``UploadedDocument``),
instead of the legacy statement/transaction pair.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import STATEMENT_SOURCE_TYPES, JournalEntrySourceType, TraceEmitter, TraceRecord, TraceResult
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
from src.extraction.base.types import (
    StatementIngestionConfigurationError,
    StatementPostingOutcome,
    StatementPostingStatus,
)
from src.extraction.extension.disposition_trace import emit_disposition_trace_records
from src.extraction.extension.review_queue import FxRateProvider, create_entry_from_txn
from src.extraction.extension.statement_validation import approve_statement, resolve_statement_transactions
from src.extraction.extension.transaction_classification import classify_by_effective_policy
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.layer3 import ClassificationRule, ClassificationStatus, RuleType, TransactionClassification
from src.extraction.orm.statement_enums import BankStatementStatus, Stage1Status
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import (
    Account,
    AccountType,
    JournalEntry,
    JournalEntryAuthorityState,
    JournalEntryStatus,
    JournalLine,
    ValidationError,
    current_anchored_journal_entries,
)
from src.observability import get_logger

logger = get_logger(__name__)

HIGH_CONFIDENCE_AUTO_APPROVE_THRESHOLD = 85

# "Which of these atomic txns are already covered by an accepted transfer
# match" is reconciliation-owned knowledge. extraction must not import
# reconciliation (reconciliation already declares depends_on extraction — the
# reverse edge would be a dependency cycle), so the read arrives through a
# provider port carried by immutable ``StatementPostingDependencies``. The app
# composition root binds reconciliation's published
# ``accepted_transfer_txn_ids`` for each statement-ingestion use case; extraction
# never consults worker-process startup state.
TransferExclusionsProvider = Callable[[AsyncSession, Sequence[UUID]], Awaitable[set[UUID]]]
TraceEmitterFactory = Callable[[AsyncSession], TraceEmitter]


@dataclass(frozen=True, slots=True, kw_only=True)
class StatementPostingDependencies:
    """Cross-domain reads required to turn approved statement facts into entries."""

    transfer_exclusions: TransferExclusionsProvider
    fx_rate_provider: FxRateProvider
    fx_rate_error: type[Exception]
    trace_emitter_factory: TraceEmitterFactory
    disposition_mode: DispositionMode

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
    """Return whether parsing confidence is high enough for automatic Stage 1 approval."""
    return (
        statement.status == BankStatementStatus.APPROVED
        and statement.balance_validated is True
        and statement.confidence_score is not None
        and statement.confidence_score >= HIGH_CONFIDENCE_AUTO_APPROVE_THRESHOLD
    )


async def auto_create_posted_entries_for_statement(
    db: AsyncSession,
    statement: StatementSummary,
    user_id: UUID,
    *,
    dependencies: StatementPostingDependencies,
) -> StatementPostingOutcome:
    """Evaluate then apply one statement posting plan after Stage 1 source confirmation."""
    transactions = await resolve_statement_transactions(db, statement)
    txn_ids = [txn.id for txn in transactions]
    if not txn_ids:
        return StatementPostingOutcome(status=StatementPostingStatus.POSTED, created_count=0)

    statement_target_ids = {f"statement-transaction:{txn_id}" for txn_id in txn_ids}
    existing_entry_result = await db.execute(
        current_anchored_journal_entries(
            user_id=user_id,
            target_kind="journal_command",
            target_ids=statement_target_ids,
        ).where(JournalEntry.status != JournalEntryStatus.VOID)
    )
    existing_entries = list(existing_entry_result.scalars().all())
    existing_entry_txn_ids = {entry.source_id for entry in existing_entries if entry.source_id in txn_ids}

    # Pre-anchor historical rows are not evidence that this source command is
    # accepted. Do not silently skip them or generate a duplicate; route the
    # operator to the correction/void lifecycle instead.
    legacy_result = await db.execute(
        select(JournalEntry.id)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
        .where(JournalEntry.source_id.in_(txn_ids))
        .where(JournalEntry.decision_authority_state == JournalEntryAuthorityState.LEGACY_UNPROVEN)
        .where(JournalEntry.status != JournalEntryStatus.VOID)
        .limit(1)
    )
    if legacy_result.scalar_one_or_none() is not None:
        statement.status = BankStatementStatus.PARSED
        statement.stage1_status = Stage1Status.PENDING_REVIEW
        statement.validation_error = "Economic review required: legacy_unanchored_source_entry"
        await db.flush()
        return StatementPostingOutcome(
            status=StatementPostingStatus.REVIEW_REQUIRED,
            created_count=0,
            review_reasons=("legacy_unanchored_source_entry",),
        )

    transfer_txn_ids = await dependencies.transfer_exclusions(db, txn_ids)
    txns_to_post = [txn for txn in transactions if txn.id not in existing_entry_txn_ids]
    if not txns_to_post:
        return StatementPostingOutcome(status=StatementPostingStatus.POSTED, created_count=0)

    preloaded_bank_account = await resolve_statement_posting_account(db, statement, user_id)
    await validate_statement_period_unique(db, statement, user_id, preloaded_bank_account.id)

    # Classification proposes P&L meaning. Disposition is the sole authority that
    # can turn that proposal plus reconciliation/account context into a command.
    await classify_by_effective_policy(db, user_id, txns_to_post)
    base_currency = await get_effective_base_currency(db)
    policy = DispositionPolicy()
    planned: list[
        tuple[AtomicTransaction, IntentProposal | None, DispositionDecision, Account | None, StatementTransaction]
    ] = []

    for txn in txns_to_post:
        classification_and_rule = (
            await db.execute(
                select(TransactionClassification, ClassificationRule)
                .join(ClassificationRule, TransactionClassification.rule_version_id == ClassificationRule.id)
                .where(TransactionClassification.atomic_txn_id == txn.id)
                .where(TransactionClassification.status == ClassificationStatus.APPLIED)
                .order_by(
                    case(
                        (
                            ClassificationRule.rule_type.in_((RuleType.KEYWORD_MATCH, RuleType.REGEX_MATCH)),
                            0,
                        ),
                        else_=1,
                    ),
                    TransactionClassification.created_at.desc(),
                )
            )
        ).first()
        counter_account = None
        proposal = None
        if classification_and_rule is not None:
            classification, classification_rule = classification_and_rule
        else:
            classification = None
            classification_rule = None
        if classification is not None and classification.account_id is not None:
            counter_account = await db.get(Account, classification.account_id)
            if counter_account is None:
                raise ValueError("Applied classification references a missing account")
            intent = _classification_intent(classification, counter_account)
            proposal = IntentProposal(
                schema_version="1",
                policy_version=str(classification.rule_version_id),
                origin=_classification_proposal_origin(classification_rule.rule_type),
                intent=intent,
                category=str((classification.tags or {}).get("category") or "") or None,
                confidence=Decimal(classification.confidence_score or 0) / Decimal("100"),
                evidence=(str(classification.id),),
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
    execution_id = f"statement:{statement.id}:result:{result_id or statement.file_hash}"
    occurred_at = statement.created_at or datetime.now(UTC)
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)
    emitter = dependencies.trace_emitter_factory(db)
    source_decisions: dict[UUID, TraceRecord] = {}
    for txn, proposal, decision, _counter_account, transaction in planned:
        records = await emit_disposition_trace_records(
            emitter=emitter,
            user_id=user_id,
            execution_id=execution_id,
            occurred_at=occurred_at,
            transaction=transaction,
            proposal=proposal,
            decision=decision,
        )
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
        statement.validation_error = f"Economic review required: {', '.join(normalized_reasons)}"[:500]
        await db.flush()
        return StatementPostingOutcome(
            status=StatementPostingStatus.REVIEW_REQUIRED,
            created_count=0,
            review_reasons=normalized_reasons,
        )

    created = 0
    for txn, _proposal, decision, counter_account, _transaction in planned:
        if decision.status is DispositionStatus.ALREADY_COVERED:
            continue
        if not decision.should_apply:
            raise RuntimeError("Disposition command reached application without enforce authority")
        # ``create_entry_from_txn`` consumes the Layer-2 ``AtomicTransaction``.
        source_decision = source_decisions.get(txn.id)
        if source_decision is None:
            raise RuntimeError("authoritative disposition is missing its source decision")
        await create_entry_from_txn(
            db,
            txn,
            user_id=user_id,
            base_currency=base_currency,
            auto_post=True,
            source_type=JournalEntrySourceType.AUTO_PARSED,
            preloaded_bank_account=preloaded_bank_account,
            fx_rate_provider=dependencies.fx_rate_provider,
            fx_rate_error=dependencies.fx_rate_error,
            disposition=decision,
            counter_account=counter_account,
            source_decision=source_decision,
            trace_emitter=emitter,
        )
        created += 1

    return StatementPostingOutcome(status=StatementPostingStatus.POSTED, created_count=created)


def _classification_intent(
    classification: TransactionClassification,
    counter_account: Account,
) -> EconomicIntent:
    """Resolve an explicit, account-compatible intent from a trusted classification.

    A category account only implies income or expense. Assets and liabilities are
    economically ambiguous: an asset counterparty may be an investment purchase,
    sale, or transfer; a liability may be principal, interest, or a card payment.
    Those cases therefore require an explicit intent tag supplied by the reviewed
    classification rather than being inferred from debit/credit direction.
    """
    tags = classification.tags if isinstance(classification.tags, dict) else {}
    tagged_intent = tags.get("intent")
    if tagged_intent is not None:
        try:
            intent = EconomicIntent(str(tagged_intent))
        except ValueError:
            return EconomicIntent.UNKNOWN
        if intent_matches_counter_account(intent, counter_account.type.value):
            return intent
        return EconomicIntent.UNKNOWN
    if counter_account.type is AccountType.INCOME:
        return EconomicIntent.INCOME
    if counter_account.type is AccountType.EXPENSE:
        return EconomicIntent.EXPENSE
    return EconomicIntent.UNKNOWN


def _classification_proposal_origin(rule_type: RuleType) -> IntentProposalOrigin:
    """Preserve the producer class instead of inferring it from economic intent."""
    if rule_type in {RuleType.KEYWORD_MATCH, RuleType.REGEX_MATCH}:
        return IntentProposalOrigin.REVIEWED_RULE
    if rule_type is RuleType.ML_MODEL:
        return IntentProposalOrigin.LIVE_LLM
    raise StatementIngestionConfigurationError(f"Unsupported classification rule type: {rule_type}")


async def resolve_statement_posting_account(
    db: AsyncSession,
    statement: StatementSummary,
    user_id: UUID,
) -> Account:
    """Resolve the asset account for automatic posting without generic fallback."""
    currency = normalize_currency_code(statement.currency or "")
    if not currency:
        raise ValueError("Statement currency required before posting. Confirm the source currency before posting.")

    if statement.account_id:
        account_result = await db.execute(
            select(Account).where(Account.id == statement.account_id).where(Account.user_id == user_id)
        )
        account = account_result.scalar_one_or_none()
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

    institution = (statement.institution or "").strip()
    account_last4 = (statement.account_last4 or "").strip()
    if not institution or not account_last4 or not currency:
        raise ValueError(
            "Account mapping required before posting. Confirm the statement account because institution, "
            "account_last4, or currency metadata is missing."
        )

    account_result = await db.execute(
        select(Account)
        .join(StatementSummary, StatementSummary.account_id == Account.id)
        .where(Account.user_id == user_id)
        .where(Account.type == AccountType.ASSET)
        .where(Account.currency == currency)
        .where(Account.is_active.is_(True))
        .where(StatementSummary.user_id == user_id)
        .where(StatementSummary.id != statement.id)
        .where(StatementSummary.status == BankStatementStatus.APPROVED)
        .where(StatementSummary.account_id.is_not(None))
        .where(func.lower(StatementSummary.institution) == institution.lower())
        .where(StatementSummary.account_last4 == account_last4)
        .where(func.upper(StatementSummary.currency) == currency)
    )
    accounts_by_id = {account.id: account for account in account_result.scalars().all()}
    if len(accounts_by_id) == 1:
        account = next(iter(accounts_by_id.values()))
        statement.account_id = account.id
        await db.flush()
        return account
    if len(accounts_by_id) > 1:
        raise ValueError(
            "Ambiguous account mapping. Multiple accounts match this statement's institution, account_last4, "
            "and currency; confirm the target account before posting."
        )
    raise ValueError(
        "Account mapping required before posting. No confirmed account matches this statement's institution, "
        "account_last4, and currency."
    )


async def validate_statement_period_unique(
    db: AsyncSession,
    statement: StatementSummary,
    user_id: UUID,
    account_id: UUID,
) -> None:
    """Block posted entries when the statement source period is missing, duplicated, or overlapping."""
    if statement.period_start is None or statement.period_end is None:
        raise ValueError("Statement period required before posting. Confirm the source date range before posting.")
    if statement.period_start > statement.period_end:
        raise ValueError("Statement period is invalid. Confirm the source date range before posting.")

    currency = normalize_currency_code(statement.currency or "")
    if not currency:
        raise ValueError("Statement currency required before posting. Confirm the source currency before posting.")

    overlap_result = await db.execute(
        select(StatementSummary)
        .where(StatementSummary.user_id == user_id)
        .where(StatementSummary.id != statement.id)
        .where(StatementSummary.account_id == account_id)
        .where(StatementSummary.status == BankStatementStatus.APPROVED)
        .where(func.upper(StatementSummary.currency) == currency)
        .where(StatementSummary.period_start.is_not(None))
        .where(StatementSummary.period_end.is_not(None))
        .where(StatementSummary.period_start <= statement.period_end)
        .where(StatementSummary.period_end >= statement.period_start)
        .limit(1)
    )
    overlapping_statement = overlap_result.scalar_one_or_none()
    if overlapping_statement:
        raise ValueError(
            "Statement period overlaps an approved statement for this account and currency. "
            "Resolve the duplicate source date range before posting."
        )


async def _account_has_opening_balance_entry(
    db: AsyncSession,
    user_id: UUID,
    account_id: UUID,
) -> bool:
    """Whether ``account_id`` already has a guided opening-balance entry.

    An opening balance establishes a one-time starting position for an account,
    not a per-period fact — so the right idempotency check is "has this account
    ever received one", not a date-ordering heuristic. (``post_opening_balance_entry``
    itself only rejects when prior *posted activity* exists strictly before the
    new entry_date, which does not cover two statements sharing the same
    period_start; this check is a stronger, statement-auto-post-specific guard on
    top of it.)
    """
    equity_entry_ids = (
        select(JournalLine.journal_entry_id)
        .join(Account, Account.id == JournalLine.account_id)
        .where(Account.user_id == user_id, Account.is_system.is_(True), Account.code == "3199")
    )
    result = await db.execute(
        select(JournalLine.id)
        .where(JournalLine.account_id == account_id)
        .where(JournalLine.journal_entry_id.in_(equity_entry_ids))
        .limit(1)
    )
    return result.first() is not None


async def try_auto_post_statement_opening_balance(
    db: AsyncSession,
    statement: StatementSummary,
    user_id: UUID,
) -> bool:
    """Post the statement's chain-validated opening balance as a guided opening entry (#1833).

    Auto-approval already trusted the extracted opening balance to the same standard
    it trusted the transactions (the running-balance chain reconciled), so the
    starting position is posted against the system Opening Balance Equity account —
    otherwise the account's ledger balance is the period net flow, not the closing
    balance, and the balance sheet headline is wrong until a manual fix.

    Called unconditionally after a successful auto-approve — NOT gated on whether
    any transactions were posted this call: a statement can be high-confidence and
    balance-validated with zero transactions in its period (e.g. a dormant-account
    month), and that statement's opening balance still needs posting or the account
    balance is silently wrong (review comment on PR #1842). Idempotency is instead
    enforced by ``_account_has_opening_balance_entry`` plus ``post_opening_balance_entry``'s
    own guards (fail-soft: non-base currencies, non-positive amounts, and prior
    activity all skip without disturbing already-posted transactions).
    """
    from src.ledger import post_opening_balance_entry

    opening_balance = statement.opening_balance
    if (
        opening_balance is None
        or opening_balance <= 0
        or statement.period_start is None
        or statement.account_id is None
    ):
        return False

    if await _account_has_opening_balance_entry(db, user_id, statement.account_id):
        return False

    try:
        base_currency = await get_effective_base_currency(db)
        async with db.begin_nested():
            await post_opening_balance_entry(
                db,
                user_id,
                entry_date=statement.period_start,
                balances={statement.account_id: opening_balance},
                currency=normalize_currency_code(statement.currency or ""),
                base_currency=base_currency,
                memo="Opening balance (statement import)",
            )
        return True
    except (ValidationError, ValueError) as exc:
        logger.info(
            "statement.opening_balance.auto_post_skipped",
            statement_id=str(statement.id),
            reason=str(exc)[:200],
        )
        return False


async def try_auto_approve_high_confidence_statement(
    db: AsyncSession,
    statement_id: UUID,
    user_id: UUID,
    *,
    dependencies: StatementPostingDependencies,
) -> int:
    """Auto-approve and post a high-confidence parsed statement when all posting guards pass.

    If a high-confidence statement cannot be safely posted automatically, leave it in
    Stage 1 pending review instead of failing parsing.
    """
    result = await db.execute(
        select(StatementSummary).where(StatementSummary.id == statement_id).where(StatementSummary.user_id == user_id)
    )
    statement = result.scalar_one_or_none()
    if statement is None or not is_high_confidence_auto_approve_candidate(statement):
        return 0

    try:
        async with db.begin_nested():
            approved = await approve_statement(db, statement_id, user_id)
            outcome = await auto_create_posted_entries_for_statement(db, approved, user_id, dependencies=dependencies)
            await db.flush()
    except ValueError as exc:
        refreshed = await db.get(StatementSummary, statement_id)
        if refreshed is not None:
            refreshed.status = BankStatementStatus.PARSED
            refreshed.stage1_status = Stage1Status.PENDING_REVIEW
            refreshed.validation_error = str(exc)[:500]
            await db.flush()
        return 0

    # Not gated on created_count: a statement can be high-confidence and
    # balance-validated with zero transactions in its period (e.g. a dormant
    # account), and its opening balance still needs posting (#1833, PR #1842
    # review). Idempotency lives in try_auto_post_statement_opening_balance
    # itself (_account_has_opening_balance_entry + post_opening_balance_entry's
    # own guards), not here.
    if outcome.status is StatementPostingStatus.REVIEW_REQUIRED:
        return 0
    await try_auto_post_statement_opening_balance(db, statement, user_id)
    return outcome.created_count
