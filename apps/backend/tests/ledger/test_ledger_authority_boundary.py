"""AC-ledger.80.3 & AC-ledger.80.4: Ledger authority boundary and in-transit isolation tests (#2052).

Verifies:
1. In-transit Processing Account (Code 1199) is strictly reserved for internal transfer reconciliation (TransferPair).
2. External statements stage unverified transactions exclusively in Layer 2 AtomicTransaction;
   routing external statement postings to Code 1199 is rejected.
3. submit_anchored_journal_entry_v2 enforces DecisionAnchor validation and double-entry balance.
4. Direct DB bypass triggers physical check constraints and triggers.
5. Zero journal state pollution on malformed/unbalanced statement imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from src.audit import (
    JournalEntrySourceType,
    SqlTraceRecordRepository,
    TraceAuthorityProfile,
    TraceCausality,
    TraceDecisionOutcome,
    TraceDecisionPolicyRegistry,
    TraceEmitter,
    TraceRecord,
    TraceResult,
    TraceScope,
    TraceTargetClass,
    VersionedTraceRef,
)
from src.extraction import (
    DispositionCommand,
    DispositionDecision,
    DispositionMode,
    DispositionStatus,
    EconomicIntent,
    TransactionDirection,
)
from src.extraction.extension.review_queue import _create_entry_from_txn
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import (
    PROCESSING_ACCOUNT_CODE,
    Account,
    AccountType,
    AnchoredJournalCommandV2,
    DecisionAnchor,
    DecisionAnchorError,
    Direction,
    JournalEntry,
    JournalEntryAuthorityState,
    JournalEntryStatus,
    JournalLine,
    ValidationError,
    submit_anchored_journal_entry_v2,
)
from src.ledger.base.decision_anchor import journal_command_target


@dataclass(frozen=True, slots=True)
class _BoundaryTestPolicy:
    assertion: VersionedTraceRef = VersionedTraceRef("ledger_policy", "boundary-test-authority", "1")
    authority: TraceAuthorityProfile = TraceAuthorityProfile(
        package="ledger",
        tier="CODE-ONLY",
        proof_kind="exact",
        provenance="deterministic",
        execution_stage="product.runtime",
        assertion_owner_digest="a" * 64,
        producer_version="2026-09-24",
    )
    causality: TraceCausality = TraceCausality.DIRECT
    target_class: TraceTargetClass = TraceTargetClass.FINANCIAL

    def fold(self, parents: tuple[TraceRecord, ...]) -> TraceDecisionOutcome:
        return TraceDecisionOutcome(TraceResult.AUTHORITATIVE, "boundary_test_authority")


def _create_test_decision_records(
    *,
    user_id: UUID,
    target: VersionedTraceRef,
) -> tuple[TraceRecord, TraceRecord]:
    scope = TraceScope.tenant(user_id)
    policy = _BoundaryTestPolicy()
    exec_id = f"test-exec-{uuid4()}"
    observation = TraceRecord.observation(
        scope=scope,
        target=target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef("ledger_observation", "boundary-test-input", "1"),
        authority=policy.authority,
        result=TraceResult.PASS,
        execution_id=exec_id,
        evidence_manifest_digest="b" * 64,
        occurred_at=datetime.now(UTC),
        score=None,
        reason_code="test_input_valid",
    )
    decision = TraceRecord.decision(
        scope=scope,
        target=target,
        policy=policy,
        execution_id=exec_id,
        occurred_at=datetime.now(UTC),
        parents=(observation,),
    )
    return observation, decision


@pytest.mark.asyncio
async def test_AC_ledger_80_3_external_statement_staging_rejects_processing_account(db, test_user) -> None:
    """AC-ledger.80.3: External statements stage via AtomicTransaction and cannot route into Code 1199."""
    user_id = test_user.id
    bank_account = Account(
        user_id=user_id,
        name=f"Checking {uuid4()}",
        code="1001",
        type=AccountType.ASSET,
        currency="SGD",
        is_active=True,
    )
    processing_account = Account(
        user_id=user_id,
        name=f"Processing {uuid4()}",
        code=PROCESSING_ACCOUNT_CODE,
        type=AccountType.ASSET,
        currency="SGD",
        is_active=True,
        is_system=True,
    )
    expense_account = Account(
        user_id=user_id,
        name=f"Expense {uuid4()}",
        code="5001",
        type=AccountType.EXPENSE,
        currency="SGD",
        is_active=True,
    )
    db.add_all([bank_account, processing_account, expense_account])
    await db.flush()

    statement = StatementSummary(
        user_id=user_id,
        account_id=bank_account.id,
        file_hash="a" * 64,
        institution="Test Bank",
        currency="SGD",
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("900.00"),
    )
    db.add(statement)
    await db.flush()

    txn = AtomicTransaction(
        user_id=user_id,
        txn_date=date(2026, 9, 20),
        description="Office Supplies",
        amount=Decimal("100.00"),
        currency="SGD",
        direction=TransactionDirection.OUT,
        dedup_hash=f"dedup-{uuid4()}",
        source_documents=[{"doc_id": str(uuid4()), "doc_type": "bank_statement"}],
    )
    db.add(txn)
    await db.flush()

    disposition = DispositionDecision(
        transaction_id=txn.id,
        policy_version="1",
        status=DispositionStatus.AUTHORITATIVE,
        intent=EconomicIntent.EXPENSE,
        category="Office Supplies",
        reason_code="rule_match",
        command=DispositionCommand(
            counter_account_id=expense_account.id,
            debit_role="counter",
            credit_role="custody",
        ),
        pnl_effect=True,
        mode=DispositionMode.ENFORCE,
    )

    policy = _BoundaryTestPolicy()
    repository = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((policy,)))
    emitter = TraceEmitter(repository)
    source_decision = TraceRecord.observation(
        scope=TraceScope.tenant(user_id),
        target=VersionedTraceRef("statement_transaction", str(txn.id), "1"),
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef("source_assertion", "test", "1"),
        authority=policy.authority,
        result=TraceResult.PASS,
        execution_id="source-obs",
        evidence_manifest_digest="c" * 64,
        occurred_at=datetime.now(UTC),
        score=None,
        reason_code="source_valid",
    )
    await emitter.emit(source_decision)

    processing_statement = StatementSummary(
        user_id=user_id,
        account_id=processing_account.id,
        file_hash="b" * 64,
        institution="Test Bank",
        currency="SGD",
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("900.00"),
    )
    db.add(processing_statement)
    await db.flush()

    # 1. Attempting to use processing account (1199) as bank_account raises ValueError
    with pytest.raises(ValueError, match="Statement posting cannot use Processing account"):
        await _create_entry_from_txn(
            db,
            txn,
            user_id=user_id,
            base_currency="SGD",
            preloaded_bank_account=processing_account,
            preloaded_statement=processing_statement,
            disposition=disposition,
            counter_account=expense_account,
            source_decision=source_decision,
            trace_emitter=emitter,
        )

    # 2. Attempting to use processing account (1199) as counter_account raises ValueError
    disposition_to_processing = DispositionDecision(
        transaction_id=txn.id,
        policy_version="1",
        status=DispositionStatus.AUTHORITATIVE,
        intent=EconomicIntent.EXPENSE,
        category="Office Supplies",
        reason_code="rule_match",
        command=DispositionCommand(
            counter_account_id=processing_account.id,
            debit_role="counter",
            credit_role="custody",
        ),
        pnl_effect=True,
        mode=DispositionMode.ENFORCE,
    )
    with pytest.raises(ValueError, match="Statement posting cannot use Processing account"):
        await _create_entry_from_txn(
            db,
            txn,
            user_id=user_id,
            base_currency="SGD",
            preloaded_bank_account=bank_account,
            preloaded_statement=statement,
            disposition=disposition_to_processing,
            counter_account=processing_account,
            source_decision=source_decision,
            trace_emitter=emitter,
        )

    # 3. Confirm zero entries created in double-entry ledger
    entries = (await db.execute(select(JournalEntry).where(JournalEntry.user_id == user_id))).scalars().all()
    assert len(entries) == 0


@pytest.mark.asyncio
async def test_AC_ledger_80_3_anchored_gateway_rejects_processing_account_for_non_system_sources(db, test_user) -> None:
    """AC-ledger.80.3: Non-system journal entries cannot use Processing account 1199."""
    user_id = test_user.id
    processing_account = Account(
        user_id=user_id,
        name=f"Processing {uuid4()}",
        code=PROCESSING_ACCOUNT_CODE,
        type=AccountType.ASSET,
        currency="SGD",
        is_active=True,
        is_system=True,
    )
    regular_account = Account(
        user_id=user_id,
        name=f"Expense {uuid4()}",
        code="5002",
        type=AccountType.EXPENSE,
        currency="SGD",
        is_active=True,
    )
    db.add_all([processing_account, regular_account])
    await db.flush()

    lines_data = [
        {
            "account_id": processing_account.id,
            "direction": Direction.DEBIT,
            "amount": Decimal("50.00"),
            "currency": "SGD",
        },
        {
            "account_id": regular_account.id,
            "direction": Direction.CREDIT,
            "amount": Decimal("50.00"),
            "currency": "SGD",
        },
    ]
    target = journal_command_target(
        entry_date=date(2026, 9, 20),
        memo="Illegal processing route",
        lines_data=lines_data,
        base_currency="SGD",
        source_identity=f"manual:{uuid4()}",
    )
    obs, dec = _create_test_decision_records(user_id=user_id, target=target)
    repository = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((_BoundaryTestPolicy(),)))
    await TraceEmitter(repository).emit_many((obs, dec))

    with pytest.raises(
        ValidationError, match=r"Processing account \(code 1199\) is reserved for internal transfer reconciliation"
    ):
        await submit_anchored_journal_entry_v2(
            db,
            user_id=user_id,
            command=AnchoredJournalCommandV2.from_mappings(
                entry_date=date(2026, 9, 20),
                memo="Illegal processing route",
                lines_data=lines_data,
                base_currency="SGD",
                source_type=JournalEntrySourceType.AUTO_PARSED,
                source_id=uuid4(),
                source_identity=target.id,
                decision_anchor=DecisionAnchor.from_record(dec),
                post_immediately=False,
            ),
            base_currency="SGD",
            trace_repository=repository,
        )

    entries = (await db.execute(select(JournalEntry).where(JournalEntry.user_id == user_id))).scalars().all()
    assert len(entries) == 0


@pytest.mark.asyncio
async def test_AC_ledger_80_4_gateway_enforces_double_entry_balance_and_rejection_preserves_clean_ledger(
    db, test_user
) -> None:
    """AC-ledger.80.4: Gateway enforces double-entry balance and clean ledger on rejection."""
    user_id = test_user.id
    cash = Account(user_id=user_id, name=f"Cash {uuid4()}", type=AccountType.ASSET, currency="SGD")
    sales = Account(user_id=user_id, name=f"Sales {uuid4()}", type=AccountType.INCOME, currency="SGD")
    db.add_all([cash, sales])
    await db.flush()

    # 1. Unbalanced entry
    unbalanced_lines = [
        {"account_id": cash.id, "direction": Direction.DEBIT, "amount": Decimal("100.00"), "currency": "SGD"},
        {"account_id": sales.id, "direction": Direction.CREDIT, "amount": Decimal("80.00"), "currency": "SGD"},
    ]
    target = journal_command_target(
        entry_date=date(2026, 9, 20),
        memo="Unbalanced entry",
        lines_data=unbalanced_lines,
        base_currency="SGD",
        source_identity=f"test:{uuid4()}",
    )
    obs, dec = _create_test_decision_records(user_id=user_id, target=target)
    repository = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((_BoundaryTestPolicy(),)))
    await TraceEmitter(repository).emit_many((obs, dec))

    with pytest.raises(ValidationError):
        await submit_anchored_journal_entry_v2(
            db,
            user_id=user_id,
            command=AnchoredJournalCommandV2.from_mappings(
                entry_date=date(2026, 9, 20),
                memo="Unbalanced entry",
                lines_data=unbalanced_lines,
                base_currency="SGD",
                source_type=JournalEntrySourceType.MANUAL,
                source_id=uuid4(),
                source_identity=target.id,
                decision_anchor=DecisionAnchor.from_record(dec),
                post_immediately=False,
            ),
            base_currency="SGD",
            trace_repository=repository,
        )

    # 2. Invalid DecisionAnchor (target mismatch)
    mismatched_target = journal_command_target(
        entry_date=date(2026, 9, 21),
        memo="Different memo",
        lines_data=[
            {"account_id": cash.id, "direction": Direction.DEBIT, "amount": Decimal("100.00"), "currency": "SGD"},
            {"account_id": sales.id, "direction": Direction.CREDIT, "amount": Decimal("100.00"), "currency": "SGD"},
        ],
        base_currency="SGD",
        source_identity=f"test:{uuid4()}",
    )
    with pytest.raises(DecisionAnchorError):
        await submit_anchored_journal_entry_v2(
            db,
            user_id=user_id,
            command=AnchoredJournalCommandV2.from_mappings(
                entry_date=date(2026, 9, 21),
                memo="Different memo",
                lines_data=[
                    {
                        "account_id": cash.id,
                        "direction": Direction.DEBIT,
                        "amount": Decimal("100.00"),
                        "currency": "SGD",
                    },
                    {
                        "account_id": sales.id,
                        "direction": Direction.CREDIT,
                        "amount": Decimal("100.00"),
                        "currency": "SGD",
                    },
                ],
                base_currency="SGD",
                source_type=JournalEntrySourceType.MANUAL,
                source_id=uuid4(),
                source_identity=mismatched_target.id,
                decision_anchor=DecisionAnchor.from_record(dec),
                post_immediately=False,
            ),
            base_currency="SGD",
            trace_repository=repository,
        )

    entries = (await db.execute(select(JournalEntry).where(JournalEntry.user_id == user_id))).scalars().all()
    assert len(entries) == 0


@pytest.mark.asyncio
async def test_AC_ledger_80_4_direct_database_bypass_interception(db, test_user) -> None:
    """AC-ledger.80.4: Direct DB bypass triggers physical constraint/trigger rejection."""
    user_id = test_user.id
    cash = Account(user_id=user_id, name=f"Cash {uuid4()}", type=AccountType.ASSET, currency="SGD")
    sales = Account(user_id=user_id, name=f"Sales {uuid4()}", type=AccountType.INCOME, currency="SGD")
    db.add_all([cash, sales])
    await db.flush()

    # 1. Bypass gateway by creating an anchored entry without decision_anchor_id
    invalid_header = JournalEntry(
        user_id=user_id,
        entry_date=date(2026, 9, 20),
        memo="Bypass attempt",
        source_type=JournalEntrySourceType.MANUAL,
        decision_authority_state=JournalEntryAuthorityState.ANCHORED,
        decision_anchor_id=None,
        status=JournalEntryStatus.DRAFT,
    )
    db.add(invalid_header)
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()

    # 2. Bypass gateway by attempting to directly post an unbalanced entry to database
    cash2 = Account(user_id=user_id, name=f"Cash {uuid4()}", type=AccountType.ASSET, currency="SGD")
    sales2 = Account(user_id=user_id, name=f"Sales {uuid4()}", type=AccountType.INCOME, currency="SGD")
    db.add_all([cash2, sales2])
    await db.flush()

    entry = JournalEntry(
        user_id=user_id,
        entry_date=date(2026, 9, 20),
        memo="Unbalanced direct post attempt",
        source_type=JournalEntrySourceType.MANUAL,
        decision_authority_state=JournalEntryAuthorityState.LEGACY_UNPROVEN,
        decision_anchor_id=None,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()

    line1 = JournalLine(
        journal_entry_id=entry.id,
        account_id=cash2.id,
        direction=Direction.DEBIT,
        amount=Decimal("100.00"),
        currency="SGD",
    )
    line2 = JournalLine(
        journal_entry_id=entry.id,
        account_id=sales2.id,
        direction=Direction.CREDIT,
        amount=Decimal("50.00"),
        currency="SGD",
    )
    db.add_all([line1, line2])
    await db.flush()

    # Deferred trigger fires on SET CONSTRAINTS ALL IMMEDIATE
    with pytest.raises((DBAPIError, IntegrityError)):
        await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    await db.rollback()
