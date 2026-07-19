"""AC-ledger.79.* decision-anchored ledger command coverage."""

from __future__ import annotations

import ast
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import (
    JournalEntrySourceType,
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
    trace_decision_projection,
)
from src.audit.extension.trace_repository import SqlTraceRecordRepository
from src.ledger import (
    Account,
    AccountType,
    DecisionAnchor,
    DecisionAnchorError,
    Direction,
    JournalEntry,
    JournalEntryAuthorityState,
    current_anchored_journal_entries,
    ledger_trace_policy_registry,
    list_journal_contributions,
    submit_anchored_journal_entry,
)
from src.ledger.base.decision_anchor import journal_command_target
from src.ledger.extension import anchored_posting
from src.ledger.extension.anchored_posting import (
    AnchoredJournalCommand,
    ManualJournalAttestationPolicy,
    SystemJournalCommandPolicy,
    validate_decision_anchor,
)
from src.reconciliation.extension.reviewed_disposition import _find_existing_entry


def test_AC_ledger_80_2_publishes_decision_policy_registry() -> None:
    """AC-ledger.80.2: package consumers restore decisions through a public port."""
    assertions = {policy.assertion for policy in ledger_trace_policy_registry().policies}
    assert assertions == {
        ManualJournalAttestationPolicy().assertion,
        SystemJournalCommandPolicy().assertion,
    }


@dataclass(frozen=True, slots=True)
class _Policy:
    assertion: VersionedTraceRef = VersionedTraceRef("ledger_policy", "test-authority", "2026-07-18")
    authority: TraceAuthorityProfile = TraceAuthorityProfile(
        package="ledger",
        tier="CODE-ONLY",
        proof_kind="exact",
        provenance="deterministic",
        execution_stage="product.runtime",
        assertion_owner_digest="1" * 64,
        producer_version="2026-07-18",
    )
    causality: TraceCausality = TraceCausality.DIRECT
    target_class: TraceTargetClass = TraceTargetClass.FINANCIAL

    def fold(self, parents: tuple[TraceRecord, ...]) -> TraceDecisionOutcome:
        return TraceDecisionOutcome(TraceResult.AUTHORITATIVE, "test_authority")


def _decision(
    *,
    user_id: UUID,
    target: VersionedTraceRef,
    result: TraceResult = TraceResult.AUTHORITATIVE,
    execution_id: str = "test-decision-anchor",
) -> TraceRecord:
    return _decision_records(
        user_id=user_id,
        target=target,
        result=result,
        execution_id=execution_id,
    )[-1]


def _decision_records(
    *,
    user_id: UUID,
    target: VersionedTraceRef,
    result: TraceResult = TraceResult.AUTHORITATIVE,
    execution_id: str = "test-decision-anchor",
) -> tuple[TraceRecord, ...]:
    scope = TraceScope.tenant(user_id)
    observation = TraceRecord.observation(
        scope=scope,
        target=target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef("ledger_observation", "test-input", "1"),
        authority=_Policy().authority,
        result=TraceResult.PASS,
        execution_id=execution_id,
        evidence_manifest_digest="2" * 64,
        occurred_at=datetime(2026, 7, 18, tzinfo=UTC),
        score=None,
        reason_code="test_input_valid",
    )
    if result is TraceResult.AUTHORITATIVE:
        return (
            observation,
            TraceRecord.decision(
                scope=scope,
                target=target,
                policy=_Policy(),
                execution_id=execution_id,
                occurred_at=datetime(2026, 7, 18, tzinfo=UTC),
                parents=(observation,),
            ),
        )
    return (
        TraceRecord.observation(
            scope=scope,
            target=target,
            target_class=TraceTargetClass.FINANCIAL,
            assertion=_Policy().assertion,
            authority=_Policy().authority,
            result=TraceResult.FAIL,
            execution_id="test-decision-anchor-rejected",
            evidence_manifest_digest="3" * 64,
            occurred_at=datetime(2026, 7, 18, tzinfo=UTC),
            score=None,
            reason_code="test_authority_rejected",
        ),
    )


class _TraceRepository:
    def __init__(self, records: tuple[TraceRecord, ...], *, current: TraceRecord | None = None) -> None:
        self._records = {record.record_id: record for record in records}
        self._current = current

    async def get(self, scope: TraceScope, record_id: UUID) -> TraceRecord | None:
        record = self._records.get(record_id)
        return record if record is not None and record.scope == scope else None

    async def current_decision(self, scope: TraceScope, _lineage) -> TraceRecord | None:
        return self._current if self._current is not None and self._current.scope == scope else None


@pytest.mark.asyncio
async def test_decision_anchor_rejects_noncurrent_or_mismatched_authority() -> None:
    """AC-ledger.79.1."""
    user_id = uuid4()
    source_identity = f"statement-transaction:{uuid4()}"
    target = VersionedTraceRef("journal_command", source_identity, "a" * 64)
    decision = _decision(user_id=user_id, target=target)
    anchor = DecisionAnchor.from_record(decision)

    await validate_decision_anchor(_TraceRepository((decision,), current=decision), user_id=user_id, anchor=anchor)

    with pytest.raises(DecisionAnchorError, match="current"):
        await validate_decision_anchor(_TraceRepository((decision,), current=None), user_id=user_id, anchor=anchor)

    other_target = VersionedTraceRef(target.kind, target.id, "b" * 64)
    with pytest.raises(DecisionAnchorError, match="target"):
        await validate_decision_anchor(
            _TraceRepository((decision,), current=decision),
            user_id=user_id,
            anchor=anchor,
            expected_target=other_target,
        )

    with pytest.raises(DecisionAnchorError, match="tenant"):
        await validate_decision_anchor(
            _TraceRepository((decision,), current=decision),
            user_id=uuid4(),
            anchor=anchor,
        )


@pytest.mark.asyncio
async def test_submit_anchored_journal_entry_is_idempotent_and_conflicts_on_new_authority(
    db: AsyncSession,
    test_user,
) -> None:
    """AC-ledger.79.2."""
    user_id = test_user.id
    debit = Account(user_id=user_id, name=f"anchor cash {uuid4()}", type=AccountType.ASSET, currency="SGD")
    credit = Account(user_id=user_id, name=f"anchor income {uuid4()}", type=AccountType.INCOME, currency="SGD")
    db.add_all((debit, credit))
    await db.flush()

    source_identity = f"statement-transaction:{uuid4()}"
    lines_data = [
        {"account_id": debit.id, "direction": Direction.DEBIT, "amount": Decimal("100.00"), "currency": "SGD"},
        {"account_id": credit.id, "direction": Direction.CREDIT, "amount": Decimal("100.00"), "currency": "SGD"},
    ]
    target = journal_command_target(
        entry_date=date(2026, 7, 18),
        memo="Anchored salary",
        lines_data=lines_data,
        base_currency="SGD",
        source_identity=source_identity,
    )
    observation, decision = _decision_records(user_id=user_id, target=target)
    repository = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((_Policy(),)))
    await TraceEmitter(repository).emit_many((observation, decision))
    anchor = DecisionAnchor.from_record(decision)
    command = AnchoredJournalCommand(
        entry_date=date(2026, 7, 18),
        memo="Anchored salary",
        lines_data=lines_data,
        source_type=JournalEntrySourceType.AUTO_PARSED,
        source_id=uuid4(),
        source_identity=source_identity,
        decision_anchor=anchor,
        post_immediately=True,
    )
    first = await submit_anchored_journal_entry(
        db,
        user_id=user_id,
        command=command,
        trace_repository=repository,
        base_currency="SGD",
    )
    retry = await submit_anchored_journal_entry(
        db,
        user_id=user_id,
        command=command,
        trace_repository=repository,
        base_currency="SGD",
    )
    assert retry.id == first.id
    assert first.decision_anchor_id == decision.record_id
    assert first.decision_authority_state is JournalEntryAuthorityState.ANCHORED

    # Provenance may evolve during review, but it is never a second command
    # identity for the same statement transaction.
    reclassified = await submit_anchored_journal_entry(
        db,
        user_id=user_id,
        command=replace(command, source_type=JournalEntrySourceType.USER_CONFIRMED),
        trace_repository=repository,
        base_currency="SGD",
    )
    assert reclassified.id == first.id

    await db.commit()
    first.decision_anchor_id = uuid4()
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()

    changed = _decision(
        user_id=user_id,
        target=target,
        execution_id="test-decision-anchor-replacement",
    )
    with pytest.raises(DecisionAnchorError, match="source target"):
        await submit_anchored_journal_entry(
            db,
            user_id=user_id,
            command=replace(command, decision_anchor=DecisionAnchor.from_record(changed)),
            trace_repository=_TraceRepository((changed,), current=changed),
            base_currency="SGD",
        )


@pytest.mark.asyncio
async def test_manual_journal_api_creates_an_attested_anchor_without_source_impersonation(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
) -> None:
    """AC-ledger.79.3."""
    debit = Account(user_id=test_user.id, name=f"manual cash {uuid4()}", type=AccountType.ASSET, currency="SGD")
    credit = Account(user_id=test_user.id, name=f"manual income {uuid4()}", type=AccountType.INCOME, currency="SGD")
    db.add_all((debit, credit))
    await db.commit()

    payload = {
        "entry_date": "2026-07-18",
        "memo": "Manual attested income",
        "rationale": "I verified this cash receipt against my paper record.",
        "lines": [
            {"account_id": str(debit.id), "direction": "DEBIT", "amount": "100.00", "currency": "SGD"},
            {"account_id": str(credit.id), "direction": "CREDIT", "amount": "100.00", "currency": "SGD"},
        ],
    }
    response = await client.post("/journal-entries", json=payload)
    assert response.status_code == 201
    assert response.json()["source_type"] == "manual"
    assert response.json()["decision_authority_state"] == "anchored"
    assert response.json()["decision_anchor_id"]

    impersonation = await client.post("/journal-entries", json={**payload, "source_type": "auto_parsed"})
    assert impersonation.status_code == 422

    conflicting_attestation = await client.post(
        "/journal-entries",
        json={**payload, "rationale": "A different person claims this same immutable journal command."},
    )
    assert conflicting_attestation.status_code == 400
    assert "different manual attestation" in conflicting_attestation.json()["detail"]


@pytest.mark.asyncio
async def test_anchor_provenance_is_immutable_and_legacy_rows_remain_unproven(
    db: AsyncSession,
    test_user,
) -> None:
    """AC-ledger.79.4."""
    legacy = JournalEntry(
        user_id=test_user.id,
        entry_date=date(2020, 1, 1),
        memo="Imported historical row",
        source_type=JournalEntrySourceType.AUTO_PARSED,
        source_id=uuid4(),
    )
    db.add(legacy)
    await db.flush()
    assert legacy.decision_authority_state is JournalEntryAuthorityState.LEGACY_UNPROVEN
    assert legacy.decision_anchor_id is None
    assert await _find_existing_entry(db, user_id=test_user.id, transaction_id=legacy.source_id) is None


@pytest.mark.asyncio
async def test_current_anchored_journal_entries_rejects_stale_or_mismatched_authority(
    db: AsyncSession,
    test_user,
) -> None:
    """AC-ledger.79.5: trusted reads join the public current-authority projection."""
    debit = Account(user_id=test_user.id, name=f"current cash {uuid4()}", type=AccountType.ASSET, currency="SGD")
    credit = Account(user_id=test_user.id, name=f"current income {uuid4()}", type=AccountType.INCOME, currency="SGD")
    db.add_all((debit, credit))
    await db.flush()

    source_identity = f"statement-transaction:{uuid4()}"
    lines_data = [
        {"account_id": debit.id, "direction": Direction.DEBIT, "amount": Decimal("50.00"), "currency": "SGD"},
        {"account_id": credit.id, "direction": Direction.CREDIT, "amount": Decimal("50.00"), "currency": "SGD"},
    ]
    target = journal_command_target(
        entry_date=date(2026, 7, 18),
        memo="Current-authority salary",
        lines_data=lines_data,
        base_currency="SGD",
        source_identity=source_identity,
    )
    observation, decision = _decision_records(user_id=test_user.id, target=target, execution_id="current-authority")
    repository = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((_Policy(),)))
    await TraceEmitter(repository).emit_many((observation, decision))
    entry = await submit_anchored_journal_entry(
        db,
        user_id=test_user.id,
        command=AnchoredJournalCommand(
            entry_date=date(2026, 7, 18),
            memo="Current-authority salary",
            lines_data=lines_data,
            source_type=JournalEntrySourceType.AUTO_PARSED,
            source_id=uuid4(),
            source_identity=source_identity,
            decision_anchor=DecisionAnchor.from_record(decision),
            post_immediately=True,
        ),
        trace_repository=repository,
        base_currency="SGD",
    )

    current = list(
        (
            await db.execute(
                current_anchored_journal_entries(
                    user_id=test_user.id,
                    target_kind="journal_command",
                    target_id=source_identity,
                )
            )
        ).scalars()
    )
    assert [item.id for item in current] == [entry.id]
    mismatched = await db.execute(
        current_anchored_journal_entries(
            user_id=test_user.id,
            target_kind="journal_command",
            target_id=f"statement-transaction:{uuid4()}",
        )
    )
    assert mismatched.scalar_one_or_none() is None

    correction = TraceRecord.observation(
        scope=observation.scope,
        target=VersionedTraceRef(target.kind, target.id, "correction-v2"),
        target_class=TraceTargetClass.FINANCIAL,
        assertion=observation.assertion,
        authority=observation.authority,
        result=TraceResult.PASS,
        execution_id="current-authority-correction",
        evidence_manifest_digest="4" * 64,
        occurred_at=datetime(2026, 7, 18, tzinfo=UTC),
        score=None,
        reason_code="source-evidence-corrected",
        supersedes_id=observation.record_id,
    )
    await repository.append(correction)

    current = list(
        (
            await db.execute(
                current_anchored_journal_entries(
                    user_id=test_user.id,
                    target_kind="journal_command",
                    target_id=source_identity,
                )
            )
        ).scalars()
    )
    assert current == []


@pytest.mark.asyncio
async def test_anchored_command_sink_failure_rolls_back_trace_and_ledger(
    db: AsyncSession,
    test_user,
    monkeypatch,
) -> None:
    """AC-ledger.79.7: the caller can roll back the complete causal write set."""

    user_id = test_user.id

    async def fail_after_trace_flush(*_args, **_kwargs):
        raise RuntimeError("injected ledger sink failure")

    monkeypatch.setattr(anchored_posting, "_create_anchored_journal_entry", fail_after_trace_flush)
    account_a, account_b = uuid4(), uuid4()
    with pytest.raises(RuntimeError, match="injected ledger sink failure"):
        await anchored_posting.submit_system_journal_entry(
            db,
            user_id=user_id,
            entry_date=date(2026, 7, 18),
            memo="Atomic fault injection",
            lines_data=[
                {
                    "account_id": account_a,
                    "direction": Direction.DEBIT,
                    "amount": Decimal("1.00"),
                    "currency": "SGD",
                },
                {
                    "account_id": account_b,
                    "direction": Direction.CREDIT,
                    "amount": Decimal("1.00"),
                    "currency": "SGD",
                },
            ],
            base_currency="SGD",
            operation="fault-injection",
        )
    await db.rollback()

    projection = trace_decision_projection(TraceScope.tenant(user_id)).subquery()
    trace_count = await db.scalar(select(func.count()).select_from(projection))
    journal_count = await db.scalar(
        select(func.count()).select_from(JournalEntry).where(JournalEntry.user_id == user_id)
    )
    assert trace_count == 0
    assert journal_count == 0


def test_production_financial_writers_have_one_anchored_persistence_boundary() -> None:
    """AC-ledger.79.6: source/review writers cannot retain an unanchored fork."""
    source_root = Path(__file__).parents[2] / "src"
    allowed_constructors = {
        "ledger/extension/repository.py",
        # This module builds an in-memory golden corpus and never persists it.
        "reconciliation/extension/reconciliation_audit.py",
    }
    allowed_raw_create = {"ledger/extension/anchored_posting.py"}
    allowed_raw_post = {
        "ledger/extension/anchored_posting.py",
        "routers/journal.py",
    }
    constructor_files: set[str] = set()
    raw_create_files: set[str] = set()
    raw_post_files: set[str] = set()

    for path in source_root.rglob("*.py"):
        relative = path.relative_to(source_root).as_posix()
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
            if name in {"JournalEntry", "JournalLine"}:
                constructor_files.add(relative)
            elif name == "_create_anchored_journal_entry":
                raw_create_files.add(relative)
            elif name == "post_journal_entry":
                raw_post_files.add(relative)

    assert constructor_files == allowed_constructors
    assert raw_create_files == allowed_raw_create
    assert raw_post_files == allowed_raw_post

    extraction_writer = source_root / "extraction" / "extension" / "review_queue.py"
    assert "submit_anchored_journal_entry(" in extraction_writer.read_text()

    journal_model = (source_root / "ledger" / "orm" / "journal.py").read_text()
    migration = (
        Path(__file__).parents[2] / "migrations/versions/0056_decision_anchored_journal_entries.py"
    ).read_text()
    for duplicated_field in ("decision_anchor_target", "decision_anchor_policy"):
        assert duplicated_field not in journal_model
        assert duplicated_field not in migration


async def test_AC_ledger_80_1_publishes_only_current_decision_anchored_journal_facts(db, test_user):
    """AC-ledger.80.1: package consumers receive facts plus one current anchor."""
    debit = Account(user_id=test_user.id, name=f"package cash {uuid4()}", type=AccountType.ASSET, currency="SGD")
    credit = Account(user_id=test_user.id, name=f"package income {uuid4()}", type=AccountType.INCOME, currency="SGD")
    db.add_all((debit, credit))
    await db.flush()
    lines_data = [
        {"account_id": debit.id, "direction": Direction.DEBIT, "amount": Decimal("100.00"), "currency": "SGD"},
        {"account_id": credit.id, "direction": Direction.CREDIT, "amount": Decimal("100.00"), "currency": "SGD"},
    ]
    target = journal_command_target(
        entry_date=date(2026, 7, 18),
        memo="Package contribution",
        lines_data=lines_data,
        base_currency="SGD",
        source_identity=f"statement-transaction:{uuid4()}",
    )
    observation, decision = _decision_records(user_id=test_user.id, target=target)
    repository = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((_Policy(),)))
    await TraceEmitter(repository).emit_many((observation, decision))
    await submit_anchored_journal_entry(
        db,
        user_id=test_user.id,
        command=AnchoredJournalCommand(
            entry_date=date(2026, 7, 18),
            memo="Package contribution",
            lines_data=lines_data,
            source_type=JournalEntrySourceType.AUTO_PARSED,
            source_id=uuid4(),
            source_identity=target.id,
            decision_anchor=DecisionAnchor.from_record(decision),
            post_immediately=True,
        ),
        trace_repository=repository,
        base_currency="SGD",
    )
    contributions = await list_journal_contributions(
        db, user_id=test_user.id, start_date=date(2026, 7, 1), end_date=date(2026, 7, 31)
    )
    assert len(contributions) == 1
    contribution = contributions[0]
    assert contribution.is_authoritative
    assert contribution.decision_id == decision.record_id
    assert contribution.decision is not None
    assert contribution.decision.target == decision.target
    assert contribution.decision.assertion == decision.assertion
    assert len(contribution.lines) == 2
