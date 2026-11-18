from __future__ import annotations

import ast
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import Result, Select, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import ORMExecuteState, Session

from src.audit import (
    JournalEntrySourceType,
    TraceAuthorityProfile,
    TraceCausality,
    TraceDecisionOutcome,
    TraceDecisionPolicyRegistry,
    TraceDecisionRef,
    TraceEmitter,
    TraceRecord,
    TraceResult,
    TraceScope,
    TraceTargetClass,
    VersionedTraceRef,
    trace_decision_projection,
)
from src.audit.extension.trace_repository import SqlTraceRecordRepository
from src.audit.money import Currency
from src.config import settings
from src.ledger import (
    AccountType,
    DecisionAnchor,
    DecisionAnchorError,
    Direction,
    JournalEntry,
    JournalEntryAuthorityState,
    JournalLine,
    ResolvedJournalContribution,
    current_anchored_journal_entries,
    ledger_trace_policy_registry,
    list_journal_contributions,
    submit_anchored_journal_entry,
    worst_confidence_tier,
)
from src.ledger.base.decision_anchor import journal_command_target
from src.ledger.base.validators import ValidationError
from src.ledger.extension import anchored_posting
from src.ledger.extension.anchored_posting import (
    AnchoredJournalCommand,
    ManualJournalAttestationPolicy,
    SystemJournalCommandPolicy,
    validate_decision_anchor,
)
from src.ledger.extension.opening_positions import OpeningPositionPolicy
from src.platform import BASE_CURRENCY_KEY, AppConfig
from src.reconciliation.extension.reviewed_disposition import _find_existing_entry
from tests.ledger._ledger_helpers import lines_pair, make_account


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


def _decision_records(
    *, user_id: UUID, target: VersionedTraceRef, result: TraceResult = TraceResult.AUTHORITATIVE, execution_id: str = "test-decision-anchor"
) -> tuple[TraceRecord, ...]:
    scope = TraceScope.tenant(user_id)
    obs = TraceRecord.observation(
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
            obs,
            TraceRecord.decision(
                scope=scope,
                target=target,
                policy=_Policy(),
                execution_id=execution_id,
                occurred_at=datetime(2026, 7, 18, tzinfo=UTC),
                parents=(obs,),
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


async def _seed_anchored(
    db: AsyncSession, user_id: UUID, memo: str, amount: str = "100.00", execution_id: str = "test-decision-anchor"
):
    debit = await make_account(db, user_id, f"{memo} cash {uuid4()}", AccountType.ASSET)
    credit = await make_account(db, user_id, f"{memo} income {uuid4()}", AccountType.INCOME)
    source_identity = f"statement-transaction:{uuid4()}"
    lines_data = lines_pair(debit.id, credit.id, amount)
    target = journal_command_target(
        entry_date=date(2026, 7, 18), memo=memo, lines_data=lines_data, base_currency="SGD", source_identity=source_identity
    )
    obs, decision = _decision_records(user_id=user_id, target=target, execution_id=execution_id)
    repository = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((_Policy(),)))
    await TraceEmitter(repository).emit_many((obs, decision))
    command = AnchoredJournalCommand.from_mappings(
        entry_date=date(2026, 7, 18),
        memo=memo,
        lines_data=lines_data,
        base_currency="SGD",
        source_type=JournalEntrySourceType.AUTO_PARSED,
        source_id=uuid4(),
        source_identity=source_identity,
        decision_anchor=DecisionAnchor.from_record(decision),
        post_immediately=True,
    )
    return source_identity, target, obs, decision, repository, command


def test_registry_confidence_tier_and_contribution_invariants() -> None:
    assert {p.assertion for p in ledger_trace_policy_registry().policies} == {
        ManualJournalAttestationPolicy().assertion,
        SystemJournalCommandPolicy().assertion,
        OpeningPositionPolicy().assertion,
    }
    backend_src = Path(__file__).resolve().parents[2] / "src"
    assert [
        (path, node.name)
        for pkg in ("ledger", "reporting", "advisor")
        for path in (backend_src / pkg).rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and "worst_confidence_tier" in node.name
    ] == [(backend_src / "ledger" / "orm" / "journal.py", "worst_confidence_tier")]
    assert (
        worst_confidence_tier(["HIGH", "LOW", "TRUSTED"]),
        worst_confidence_tier(["HIGH", "UNAVAILABLE", "LOW"]),
        worst_confidence_tier([None], default="DETERMINISTIC"),
    ) == ("LOW", "UNAVAILABLE", "DETERMINISTIC")
    with pytest.raises(ValueError, match="unproven journal contribution cannot have a decision"):
        ResolvedJournalContribution(
            entry_id=uuid4(),
            entry_date=date(2026, 7, 19),
            lines=(),
            state="unproven",
            reason_code="missing_current_decision_anchor",
            decision=TraceDecisionRef(uuid4(), VersionedTraceRef("journal_command", "entry-1", "1"), VersionedTraceRef("ledger_authority", "posted", "1")),
        )


async def test_decision_anchor_rejects_noncurrent_or_mismatched_authority() -> None:
    uid = uuid4()
    target = VersionedTraceRef("journal_command", f"statement-transaction:{uuid4()}", "a" * 64)
    decision = _decision_records(user_id=uid, target=target)[-1]
    anchor = DecisionAnchor.from_record(decision)
    await validate_decision_anchor(_TraceRepository((decision,), current=decision), user_id=uid, anchor=anchor)
    for match, repo, caller_uid, expected in (
        ("current", _TraceRepository((decision,), current=None), uid, None),
        ("target", _TraceRepository((decision,), current=decision), uid, VersionedTraceRef(target.kind, target.id, "b" * 64)),
        ("tenant", _TraceRepository((decision,), current=decision), uuid4(), None),
    ):
        with pytest.raises(DecisionAnchorError, match=match):
            await validate_decision_anchor(repo, user_id=caller_uid, anchor=anchor, expected_target=expected)


async def test_submit_anchored_journal_entry_idempotent_immutable_and_contributions(
    db: AsyncSession, test_user
) -> None:
    uid = test_user.id
    source_id, target, obs, decision, repository, command = await _seed_anchored(db, uid, "Anchored salary")
    first = await submit_anchored_journal_entry(db, user_id=uid, command=command, trace_repository=repository, base_currency="SGD")
    retry = await submit_anchored_journal_entry(db, user_id=uid, command=command, trace_repository=repository, base_currency="SGD")
    reclassified = await submit_anchored_journal_entry(
        db, user_id=uid, command=replace(command, source_type=JournalEntrySourceType.USER_CONFIRMED), trace_repository=repository, base_currency="SGD"
    )
    assert retry.id == first.id == reclassified.id
    assert first.decision_anchor_id == decision.record_id
    assert first.decision_authority_state is JournalEntryAuthorityState.ANCHORED

    current = list((await db.execute(current_anchored_journal_entries(user_id=uid, target_kind="journal_command", target_id=source_id))).scalars())
    assert [item.id for item in current] == [first.id]
    assert (await db.execute(current_anchored_journal_entries(user_id=uid, target_kind="journal_command", target_id=f"statement-transaction:{uuid4()}"))).scalar_one_or_none() is None
    contributions = await list_journal_contributions(db, user_id=uid, start_date=date(2026, 7, 1), end_date=date(2026, 7, 31))
    assert len(contributions) == 1 and contributions[0].is_authoritative and contributions[0].decision_id == decision.record_id

    await db.commit()
    first.decision_anchor_id = uuid4()
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()

    changed = _decision_records(user_id=uid, target=target, execution_id="replacement")[-1]
    with pytest.raises(DecisionAnchorError, match="source target"):
        await submit_anchored_journal_entry(
            db, user_id=uid, command=replace(command, decision_anchor=DecisionAnchor.from_record(changed)), trace_repository=_TraceRepository((changed,), current=changed), base_currency="SGD"
        )

    correction = TraceRecord.observation(
        scope=obs.scope,
        target=VersionedTraceRef(target.kind, target.id, "correction-v2"),
        target_class=TraceTargetClass.FINANCIAL,
        assertion=obs.assertion,
        authority=obs.authority,
        result=TraceResult.PASS,
        execution_id="current-authority-correction",
        evidence_manifest_digest="4" * 64,
        occurred_at=datetime(2026, 7, 18, tzinfo=UTC),
        score=None,
        reason_code="source-evidence-corrected",
        supersedes_id=obs.record_id,
    )
    await repository.append(correction)
    assert list((await db.execute(current_anchored_journal_entries(user_id=uid, target_kind="journal_command", target_id=source_id))).scalars()) == []


async def _post_draft(
    client: AsyncClient, debit_id, credit_id, memo: str, d_amt: str, c_amt: str, d_ccy: str = "SGD", c_ccy: str = "SGD", fx_rate: str | None = None
) -> tuple[dict, object]:
    d_line = {"account_id": str(debit_id), "direction": "DEBIT", "amount": d_amt, "currency": d_ccy}
    if fx_rate:
        d_line["fx_rate"] = fx_rate
    payload = {
        "entry_date": "2026-07-18",
        "memo": memo,
        "rationale": "Checked.",
        "lines": [d_line, {"account_id": str(credit_id), "direction": "CREDIT", "amount": c_amt, "currency": c_ccy}],
    }
    return payload, await client.post("/journal-entries", json=payload)


async def test_manual_journal_api_attestation_and_legacy_rows(client: AsyncClient, db: AsyncSession, test_user) -> None:
    debit = await make_account(db, test_user.id, f"manual cash {uuid4()}", AccountType.ASSET)
    credit = await make_account(db, test_user.id, f"manual income {uuid4()}", AccountType.INCOME, commit=True)
    payload, resp = await _post_draft(client, debit.id, credit.id, "Manual attested income", "100.00", "100.00")
    assert resp.status_code == 201 and resp.json()["decision_authority_state"] == "anchored" and resp.json()["decision_anchor_id"]
    assert (await client.post("/journal-entries", json={**payload, "source_type": "auto_parsed"})).status_code == 422
    conflict = await client.post("/journal-entries", json={**payload, "rationale": "Different rationale."})
    assert conflict.status_code == 400 and "different manual attestation" in conflict.json()["detail"]

    legacy = JournalEntry(user_id=test_user.id, entry_date=date(2020, 1, 1), memo="Legacy", source_type=JournalEntrySourceType.AUTO_PARSED, source_id=uuid4())
    db.add(legacy)
    await db.flush()
    assert legacy.decision_authority_state is JournalEntryAuthorityState.LEGACY_UNPROVEN and legacy.decision_anchor_id is None
    assert await _find_existing_entry(db, user_id=test_user.id, transaction_id=legacy.source_id) is None


async def test_anchored_sink_failure_rollback_and_single_persistence_boundary(
    db: AsyncSession, test_user, monkeypatch
) -> None:
    uid = test_user.id

    async def fail(*_args, **_kwargs):
        raise RuntimeError("injected ledger sink failure")

    monkeypatch.setattr(anchored_posting, "_create_anchored_journal_entry", fail)
    with pytest.raises(RuntimeError, match="injected ledger sink failure"):
        await anchored_posting.submit_system_journal_entry(
            db, user_id=uid, entry_date=date(2026, 7, 18), memo="Atomic fault", lines_data=lines_pair(uuid4(), uuid4(), "1.00"), base_currency="SGD", operation="fault-injection"
        )
    await db.rollback()
    projection = trace_decision_projection(TraceScope.tenant(uid)).subquery()
    assert await db.scalar(select(func.count()).select_from(projection)) == 0
    assert await db.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.user_id == uid)) == 0

    src_root = Path(__file__).parents[2] / "src"
    buckets: dict[str, set[str]] = {"ctor": set(), "raw_create": set(), "raw_post": set(), "anchored": set()}
    mapping = {
        "JournalEntry": "ctor",
        "JournalLine": "ctor",
        "_create_anchored_journal_entry": "raw_create",
        "_create_anchored_journal_entries": "raw_create",
        "post_journal_entry": "raw_post",
        "post_journal_entries": "raw_post",
        "submit_anchored_journal_entry": "anchored",
        "submit_anchored_journal_entries": "anchored",
    }
    for path in src_root.rglob("*.py"):
        rel = path.relative_to(src_root).as_posix()
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
                if name in mapping:
                    buckets[mapping[name]].add(rel)
    assert buckets["ctor"] == {"ledger/extension/repository.py", "reconciliation/extension/reconciliation_audit.py"}
    assert buckets["raw_create"] == {"ledger/extension/anchored_posting.py"}
    assert buckets["raw_post"] == {"ledger/extension/anchored_posting.py", "routers/journal.py"}
    assert "extraction/extension/review_queue.py" in buckets["anchored"]
    model_txt = (src_root / "ledger" / "orm" / "journal.py").read_text()
    mig_txt = (Path(__file__).parents[2] / "migrations/versions/0056_decision_anchored_journal_entries.py").read_text()
    assert all(f not in model_txt and f not in mig_txt for f in ("decision_anchor_target", "decision_anchor_policy"))


@pytest.mark.parametrize("change", ["user_override", "operator_default"])
async def test_AC_ledger_79_9_post_uses_the_base_currency_stored_on_the_draft(
    client: AsyncClient, db: AsyncSession, test_user, change: str
) -> None:
    created_base = Currency(settings.base_currency).code
    changed_base = "USD" if created_base != "USD" else "EUR"
    debit = await make_account(db, test_user.id, f"payroll cash {uuid4()}", AccountType.ASSET, created_base)
    credit = await make_account(db, test_user.id, f"payroll income {uuid4()}", AccountType.INCOME, created_base, commit=True)
    _, created = await _post_draft(client, debit.id, credit.id, "Monthly payroll", "8000.00", "8000.00", created_base, created_base)
    assert created.status_code == 201
    entry_id = UUID(created.json()["id"])
    if change == "user_override":
        assert (await client.put("/users/me/settings/base-currency", json={"base_currency": changed_base})).status_code == 200
    else:
        db.add(AppConfig(key=BASE_CURRENCY_KEY, value=changed_base))
        await db.commit()
    assert (await client.get("/users/me/settings/base-currency")).json() == {"base_currency": changed_base}
    posted = await client.post(f"/journal-entries/{entry_id}/postings")
    assert posted.status_code == 200 and {ln["currency"] for ln in posted.json()["lines"]} == {created_base}
    assert await db.scalar(select(JournalEntry.base_currency).where(JournalEntry.id == entry_id)) == created_base


def _reverse_unordered_journal_line_reads(state: ORMExecuteState) -> Result | None:
    stmt = state.statement
    if state.is_select and isinstance(stmt, Select) and not stmt._order_by_clauses and any(col.get("expr") is JournalLine for col in stmt.column_descriptions):
        return state.invoke_statement(statement=stmt.order_by(JournalLine.line_no.desc()))
    return None


@contextmanager
def _reverse_line_reads() -> Iterator[None]:
    event.listen(Session, "do_orm_execute", _reverse_unordered_journal_line_reads)
    try:
        yield
    finally:
        event.remove(Session, "do_orm_execute", _reverse_unordered_journal_line_reads)


async def test_post_order_and_decimal_scale_invariants(client: AsyncClient, db: AsyncSession, test_user) -> None:
    debit = await make_account(db, test_user.id, f"checking {uuid4()}", AccountType.ASSET)
    credit = await make_account(db, test_user.id, f"equity {uuid4()}", AccountType.EQUITY)
    usd = await make_account(db, test_user.id, f"usd {uuid4()}", AccountType.ASSET, "USD")
    sgd = await make_account(db, test_user.id, f"sgd {uuid4()}", AccountType.INCOME, "SGD", commit=True)

    _, r1 = await _post_draft(client, debit.id, credit.id, "Checking Deposit", "1000.00", "1000.00")
    draft1 = r1.json()["id"]
    with _reverse_line_reads():
        assert [ln.account_id for ln in await db.scalars(select(JournalLine).where(JournalLine.journal_entry_id == UUID(draft1)))] == [credit.id, debit.id]
        posted = await client.post(f"/journal-entries/{draft1}/postings")
    assert posted.status_code == 200 and [ln["account_id"] for ln in posted.json()["lines"]] == [str(debit.id), str(credit.id)]

    _, r2 = await _post_draft(client, usd.id, sgd.id, "Short decimals", "100", "135", "USD", "SGD", fx_rate="1.35")
    assert (await client.post(f"/journal-entries/{r2.json()['id']}/postings")).json()["status"] == "posted"
    for match, data in (
        ("more than 2 decimal places", [{"account_id": usd.id, "amount": Decimal("1.234")}]),
        ("more than 6 decimal places", [{"account_id": usd.id, "amount": Decimal("1"), "fx_rate": Decimal("1.1234567")}]),
    ):
        with pytest.raises(ValidationError, match=match):
            anchored_posting._at_stored_scale(data)
