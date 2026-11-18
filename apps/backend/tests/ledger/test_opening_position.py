import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.audit import SqlTraceRecordRepository, TraceDecisionPolicyRegistry, TraceEmitter, TraceRecord, TraceResult, TraceScope, TraceTargetClass, VersionedTraceRef
from src.extraction import DocumentSource, TransactionDirection, extraction_trace_policy_registry, resolve_statement_contribution
from src.extraction.extension.extraction_trace import build_extraction_trace_records
from src.extraction.extension.reviewed_statement_envelope import persist_statement_extraction_result
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_posting import try_auto_approve_high_confidence_statement
from src.ledger import (
    Account,
    AccountType,
    JournalEntryStatus,
    JournalLine,
    ValidationError,
    get_opening_balance_readiness,
    initialize_opening_positions,
    ledger_trace_policy_registry,
    list_opening_positions,
    validate_journal_balance,
    void_journal_entry,
)
from src.ledger.extension.anchored_posting import SystemJournalCommandPolicy, submit_system_journal_entry
from src.ledger.extension.opening_positions import record_opening_position
from src.request_context import RequestContext
from src.routers import statements
from src.schemas.extraction import Stage1ApprovalRequest
from tests.api._statement_router_fixtures import add_reviewed_disposition_rule
from tests.api.conftest import DummyStorage
from tests.factories import UserFactory, seed_parsed_statement
from tests.integration.test_statement_opening_balance_auto_post import _attach_dispositions
from tests.ledger._ledger_helpers import make_account
from tests.statement_ingestion import parse_and_load_statement_projection, posting_dependencies


async def test_manual_approval_posts_opening_and_pins_category(db, test_user) -> None:
    bank = await make_account(db, test_user.id, "Starting account")
    seeded = await seed_parsed_statement(
        db, test_user.id, original_filename="generated-opening.pdf", transactions=[{"description": "Synthetic expense", "amount": Decimal("100"), "direction": TransactionDirection.OUT}]
    )
    await add_reviewed_disposition_rule(db, user_id=test_user.id, keyword="synthetic expense", account_type=AccountType.EXPENSE, category="AUDIT")
    seeded.statement.account_id = bank.id
    await db.commit()
    with patch.object(statements, "StorageService", DummyStorage):
        response = await statements.approve_statement_stage1(
            statement_id=seeded.statement.id, request=Stage1ApprovalRequest(create_account_if_missing=False), ctx=RequestContext(db, test_user.id)
        )
    lines = (await db.execute(select(JournalLine).where(JournalLine.account_id == bank.id))).scalars().all()
    exp_rows = (
        await db.execute(select(JournalLine).join(Account, Account.id == JournalLine.account_id).where(Account.user_id == test_user.id, Account.type == AccountType.EXPENSE))
    ).scalars().all()
    assert response.status.value == "approved" and exp_rows[0].tags["economic_category"] == "AUDIT"
    assert sum((ln.amount if ln.direction.value == "DEBIT" else -ln.amount for ln in lines), Decimal("0")) == Decimal("900")


async def test_concurrent_opening_initialization(db_engine) -> None:
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with sessions() as setup:
        user = await UserFactory.create_async(setup, email=f"opening-{uuid4()}@example.invalid")
        bank = await make_account(setup, user.id, "Starting account")
        uid, aid = user.id, bank.id
        await setup.commit()

    async def initialize():
        async with sessions() as session:
            entry = await initialize_opening_positions(session, uid, entry_date=date(2026, 1, 1), balances={aid: Decimal("1000")}, currency="SGD", base_currency="SGD")
            await session.commit()
            return entry.id

    results = await asyncio.gather(initialize(), initialize())
    assert results[0] == results[1]
    async with sessions() as session:
        positions = await list_opening_positions(session, user_id=uid, as_of=date(2026, 1, 31))
        assert len(positions) == 1 and positions[0].amount == Decimal("1000")


async def test_zero_projection_date_and_immutability(db, test_user) -> None:
    first = await make_account(db, test_user.id, "Initialized")
    second = await make_account(db, test_user.id, "Explicit zero")
    entry = await initialize_opening_positions(db, test_user.id, entry_date=date(2026, 1, 1), balances={first.id: Decimal("100"), second.id: Decimal("0")}, currency="SGD", base_currency="SGD")
    positions = await list_opening_positions(db, user_id=test_user.id, as_of=date(2026, 1, 1))
    by_acc = {p.account_id: p for p in positions}
    assert by_acc[first.id].effective_date == entry.entry_date == date(2026, 1, 1) and by_acc[first.id].state == "authoritative"
    assert by_acc[second.id].amount == 0 and by_acc[second.id].journal_entry_id is None and by_acc[second.id].decision is not None
    assert (await get_opening_balance_readiness(db, test_user.id))["needs_opening_balance"] is False
    await db.commit()
    with pytest.raises(DBAPIError):
        async with db.begin_nested():
            await db.execute(text("UPDATE opening_position_records SET amount=999 WHERE account_id=:id"), {"id": first.id})


async def test_foreign_opening_missing_rate_and_cent_rounding(db, test_user) -> None:
    first = await make_account(db, test_user.id, "First USD", currency="USD")
    second = await make_account(db, test_user.id, "Second USD", currency="USD")
    with pytest.raises(ValidationError, match="FX rate"):
        await initialize_opening_positions(db, test_user.id, entry_date=date(2026, 1, 1), balances={first.id: Decimal("100")}, currency="USD", base_currency="SGD")
    entry = await initialize_opening_positions(
        db, test_user.id, entry_date=date(2026, 1, 1), balances={first.id: Decimal("0.01"), second.id: Decimal("0.01")}, currency="USD", base_currency="SGD", fx_rates={"USD": Decimal("0.5")}
    )
    await db.commit()
    await db.refresh(entry, ["lines"])
    validate_journal_balance(entry.lines, base_currency="SGD")
    assert sum((ln.amount for ln in entry.lines if ln.currency == "SGD"), Decimal("0")) == Decimal("0.01")
    assert len([ln for ln in entry.lines if ln.currency == "USD" and ln.fx_rate == Decimal("0.5")]) == 2


async def test_stale_authority_and_void_opening_behavior(db, test_user) -> None:
    bank = await make_account(db, test_user.id, "Starting account")
    old = await initialize_opening_positions(db, test_user.id, entry_date=date(2026, 1, 1), balances={bank.id: Decimal("100")}, currency="SGD", base_currency="SGD")
    newer = await submit_system_journal_entry(
        db, user_id=test_user.id, entry_date=date(2026, 1, 1), memo="Corrected stock", operation="opening-balance", base_currency="SGD", lines_data=[{"account_id": ln.account_id, "direction": ln.direction, "amount": Decimal("200"), "currency": "SGD"} for ln in old.lines]
    )
    await record_opening_position(db, user_id=test_user.id, account_id=bank.id, effective_date=date(2026, 1, 1), amount=Decimal("200"), currency="SGD", fx_rate=None, journal_entry_id=newer.id)
    assert (await list_opening_positions(db, user_id=test_user.id, as_of=date(2026, 1, 31)))[0].amount == Decimal("200")
    await void_journal_entry(db, newer.id, reason="Withdrawn", user_id=test_user.id, base_currency="SGD")
    assert old.status == JournalEntryStatus.POSTED and await list_opening_positions(db, user_id=test_user.id, as_of=date(2026, 1, 31)) == ()

    bank2 = await make_account(db, test_user.id, "Stale bank")
    entry = await initialize_opening_positions(db, test_user.id, entry_date=date(2026, 1, 1), balances={bank2.id: Decimal("100")}, currency="SGD", base_currency="SGD")
    repo = SqlTraceRecordRepository(db, ledger_trace_policy_registry())
    scope = TraceScope.tenant(test_user.id)
    prev = await repo.get(scope, entry.decision_anchor_id)
    policy = SystemJournalCommandPolicy()
    now = datetime.now(UTC)
    obs = TraceRecord.observation(scope=scope, target=prev.target, target_class=TraceTargetClass.FINANCIAL, assertion=VersionedTraceRef("ledger_system_input", "opening-balance", "1"), authority=policy.authority, result=TraceResult.FAIL, execution_id="revoked-opening", evidence_manifest_digest=prev.target.version, occurred_at=now, reason_code="revoked", score=None)
    revoked = TraceRecord.decision(scope=scope, target=prev.target, policy=policy, execution_id=obs.execution_id, occurred_at=now, parents=(obs,), supersedes_id=prev.record_id)
    await TraceEmitter(repo).emit_many((obs, revoked))
    pos = await list_opening_positions(db, user_id=test_user.id, as_of=date(2026, 1, 31))
    assert len(pos) == 1 and pos[0].state == "unproven" and pos[0].decision is None


@pytest.mark.parametrize("opening", ["1000", "0"])
async def test_source_opening_retains_pdf_ancestor(db, test_user, opening: str) -> None:
    payload = {
        "institution": "GXS",
        "account_last4": "1234",
        "currency": "SGD",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "opening_balance": opening,
        "closing_balance": str(Decimal(opening) + Decimal("100")),
        "transactions": [{"date": "2026-01-10", "description": "Salary credit", "amount": "100", "direction": "IN", "currency": "SGD", "balance_after": str(Decimal(opening) + Decimal("100"))}],
    }
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(return_value=payload)
    result, statement, transactions = await parse_and_load_statement_projection(
        service, db=db, source=DocumentSource.resolve(path=Path("synthetic-opening.pdf"), content=b"%PDF-1.7"), institution="GXS", user_id=test_user.id
    )
    traces = build_extraction_trace_records(result, user_id=test_user.id, execution_id="synthetic-source-opening", occurred_at=datetime.now(UTC))
    await TraceEmitter(SqlTraceRecordRepository(db, extraction_trace_policy_registry())).emit_many(traces)
    await persist_statement_extraction_result(db, statement=statement, result=result, source_trace_record_id=traces[0].record_id)
    await _attach_dispositions(db, test_user.id, transactions)
    assert await try_auto_approve_high_confidence_statement(db, statement.id, test_user.id, dependencies=posting_dependencies()) > 0
    source = await resolve_statement_contribution(db, user_id=test_user.id, statement_id=statement.id)
    position = (await list_opening_positions(db, user_id=test_user.id, as_of=date(2026, 1, 31)))[0]
    repo = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((*extraction_trace_policy_registry().policies, *ledger_trace_policy_registry().policies)))
    pending, visited = [position.decision.decision_id], set()
    while pending:
        rid = pending.pop()
        if rid not in visited:
            visited.add(rid)
            pending.extend((await repo.get(TraceScope.tenant(test_user.id), rid)).parent_ids)
    assert source.decision.decision_id in visited and position.source_decision == source.decision and (position.journal_entry_id is None) == (opening == "0")
