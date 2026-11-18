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
from src.extraction import DispositionCommand, DispositionDecision, DispositionMode, DispositionStatus, EconomicIntent, TransactionDirection
from src.extraction.extension.review_queue import _create_entry_from_txn
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import (
    PROCESSING_ACCOUNT_CODE,
    AccountType,
    AnchoredJournalCommand,
    DecisionAnchor,
    DecisionAnchorError,
    Direction,
    JournalEntry,
    JournalEntryAuthorityState,
    JournalEntryStatus,
    ValidationError,
    submit_anchored_journal_entry,
)
from src.ledger.base.decision_anchor import journal_command_target
from tests.ledger._ledger_helpers import lines_pair, make_account, make_entry


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


async def _emit_decision(db, user_id: UUID, target: VersionedTraceRef) -> tuple[SqlTraceRecordRepository, TraceRecord]:
    scope = TraceScope.tenant(user_id)
    policy = _BoundaryTestPolicy()
    exec_id = f"test-exec-{uuid4()}"
    obs = TraceRecord.observation(
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
    dec = TraceRecord.decision(scope=scope, target=target, policy=policy, execution_id=exec_id, occurred_at=datetime.now(UTC), parents=(obs,))
    repo = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((policy,)))
    await TraceEmitter(repo).emit_many((obs, dec))
    return repo, dec


async def test_statement_staging_rejects_processing_account(db, test_user) -> None:
    uid = test_user.id
    bank = await make_account(db, uid, f"Checking {uuid4()}", AccountType.ASSET, code="1001", is_active=True)
    proc = await make_account(db, uid, f"Processing {uuid4()}", AccountType.ASSET, code=PROCESSING_ACCOUNT_CODE, is_active=True, is_system=True)
    exp = await make_account(db, uid, f"Expense {uuid4()}", AccountType.EXPENSE, code="5001", is_active=True)
    stmt = StatementSummary(user_id=uid, account_id=bank.id, file_hash="a" * 64, institution="Bank", currency="SGD", opening_balance=Decimal("1000"), closing_balance=Decimal("900"))
    proc_stmt = StatementSummary(user_id=uid, account_id=proc.id, file_hash="b" * 64, institution="Bank", currency="SGD", opening_balance=Decimal("1000"), closing_balance=Decimal("900"))
    txn = AtomicTransaction(user_id=uid, txn_date=date(2024, 1, 15), description="Office", amount=Decimal("100.00"), currency="SGD", direction=TransactionDirection.OUT, dedup_hash=f"dedup-{uuid4()}", source_documents=[{"doc_id": str(uuid4()), "doc_type": "bank_statement"}])
    db.add_all([stmt, proc_stmt, txn])
    await db.flush()

    policy = _BoundaryTestPolicy()
    emitter = TraceEmitter(SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((policy,))))
    source_dec = TraceRecord.observation(
        scope=TraceScope.tenant(uid),
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
    await emitter.emit(source_dec)

    for pre_bank, pre_stmt, counter in ((proc, proc_stmt, exp), (bank, stmt, proc)):
        disp = DispositionDecision(
            transaction_id=txn.id,
            policy_version="1",
            status=DispositionStatus.AUTHORITATIVE,
            intent=EconomicIntent.EXPENSE,
            category="Office",
            reason_code="rule_match",
            command=DispositionCommand(counter_account_id=counter.id, debit_role="counter", credit_role="custody"),
            pnl_effect=True,
            mode=DispositionMode.ENFORCE,
        )
        with pytest.raises(ValueError, match="Statement posting cannot use Processing account"):
            await _create_entry_from_txn(
                db, txn, user_id=uid, base_currency="SGD", preloaded_bank_account=pre_bank, preloaded_statement=pre_stmt, disposition=disp, counter_account=counter, source_decision=source_dec, trace_emitter=emitter
            )
    assert (await db.execute(select(JournalEntry).where(JournalEntry.user_id == uid))).scalars().all() == []


async def test_anchored_gateway_rejects_processing_unbalanced_and_mismatched_target(db, test_user) -> None:
    uid = test_user.id
    proc = await make_account(db, uid, f"Proc {uuid4()}", AccountType.ASSET, code=PROCESSING_ACCOUNT_CODE, is_active=True, is_system=True)
    cash = await make_account(db, uid, f"Cash {uuid4()}", AccountType.ASSET)
    sales = await make_account(db, uid, f"Sales {uuid4()}", AccountType.INCOME)

    proc_lines = lines_pair(proc.id, sales.id, "50.00")
    t1 = journal_command_target(entry_date=date(2024, 1, 15), memo="Illegal proc", lines_data=proc_lines, base_currency="SGD", source_identity=f"manual:{uuid4()}")
    repo1, dec1 = await _emit_decision(db, uid, t1)
    with pytest.raises(ValidationError, match="Processing account \\(code 1199\\) is reserved"):
        await submit_anchored_journal_entry(
            db, user_id=uid, command=AnchoredJournalCommand.from_mappings(entry_date=date(2024, 1, 15), memo="Illegal proc", lines_data=proc_lines, base_currency="SGD", source_type=JournalEntrySourceType.AUTO_PARSED, source_id=uuid4(), source_identity=t1.id, decision_anchor=DecisionAnchor.from_record(dec1), post_immediately=False), base_currency="SGD", trace_repository=repo1
        )

    unbal = [{"account_id": cash.id, "direction": Direction.DEBIT, "amount": Decimal("100.00"), "currency": "SGD"}, {"account_id": sales.id, "direction": Direction.CREDIT, "amount": Decimal("80.00"), "currency": "SGD"}]
    t2 = journal_command_target(entry_date=date(2024, 1, 15), memo="Unbal", lines_data=unbal, base_currency="SGD", source_identity=f"test:{uuid4()}")
    repo2, dec2 = await _emit_decision(db, uid, t2)
    with pytest.raises(ValidationError):
        await submit_anchored_journal_entry(
            db, user_id=uid, command=AnchoredJournalCommand.from_mappings(entry_date=date(2024, 1, 15), memo="Unbal", lines_data=unbal, base_currency="SGD", source_type=JournalEntrySourceType.MANUAL, source_id=uuid4(), source_identity=t2.id, decision_anchor=DecisionAnchor.from_record(dec2), post_immediately=False), base_currency="SGD", trace_repository=repo2
        )

    bal = lines_pair(cash.id, sales.id, "100.00")
    t3 = journal_command_target(entry_date=date(2026, 9, 21), memo="Other", lines_data=bal, base_currency="SGD", source_identity=f"test:{uuid4()}")
    with pytest.raises(DecisionAnchorError):
        await submit_anchored_journal_entry(
            db, user_id=uid, command=AnchoredJournalCommand.from_mappings(entry_date=date(2026, 9, 21), memo="Other", lines_data=bal, base_currency="SGD", source_type=JournalEntrySourceType.MANUAL, source_id=uuid4(), source_identity=t3.id, decision_anchor=DecisionAnchor.from_record(dec2), post_immediately=False), base_currency="SGD", trace_repository=repo2
        )
    assert (await db.execute(select(JournalEntry).where(JournalEntry.user_id == uid))).scalars().all() == []


async def test_direct_database_bypass_interception(db, test_user) -> None:
    uid = test_user.id
    db.add(JournalEntry(user_id=uid, entry_date=date(2024, 1, 15), memo="Bypass", source_type=JournalEntrySourceType.MANUAL, decision_authority_state=JournalEntryAuthorityState.ANCHORED, decision_anchor_id=None, status=JournalEntryStatus.DRAFT))
    with pytest.raises((IntegrityError, DBAPIError)):
        await db.flush()
    await db.rollback()

    cash = await make_account(db, uid, f"Cash {uuid4()}", AccountType.ASSET)
    sales = await make_account(db, uid, f"Sales {uuid4()}", AccountType.INCOME)
    await make_entry(
        db,
        uid,
        [(cash.id, Direction.DEBIT, "100"), (sales.id, Direction.CREDIT, "50")],
        entry_date=date(2024, 1, 15),
        decision_authority_state=JournalEntryAuthorityState.LEGACY_UNPROVEN,
        decision_anchor_id=None,
    )
    with pytest.raises((DBAPIError, IntegrityError)):
        await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    await db.rollback()
