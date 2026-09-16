"""AC-ledger.opening-position: starting stock survives the complete posting lifecycle."""

import asyncio
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.extraction import TransactionDirection
from src.ledger import (
    Account,
    AccountType,
    JournalLine,
    ValidationError,
    get_opening_balance_readiness,
    initialize_opening_positions,
    list_opening_positions,
)
from src.routers import statements
from src.schemas.review import Stage1ApprovalRequest
from tests.api.test_statements_router import DummyStorage, add_reviewed_disposition_rule
from tests.factories import UserFactory, seed_parsed_statement


async def account(db, user_id, name="Starting account", currency="SGD"):
    row = Account(user_id=user_id, name=name, type=AccountType.ASSET, currency=currency)
    db.add(row)
    await db.flush()
    return row


async def test_manual_approval_posts_opening(db, test_user):
    """AC-ledger.opening-position.1: first source balance is not merely net flow."""
    bank = await account(db, test_user.id)
    await add_reviewed_disposition_rule(
        db, user_id=test_user.id, keyword="synthetic expense", account_type=AccountType.EXPENSE, category="AUDIT"
    )
    seeded = await seed_parsed_statement(
        db,
        test_user.id,
        original_filename="generated-opening.pdf",
        transactions=[
            {"description": "Synthetic expense", "amount": Decimal("100"), "direction": TransactionDirection.OUT}
        ],
    )
    seeded.statement.account_id = bank.id
    await db.commit()
    with patch.object(statements, "StorageService", DummyStorage):
        response = await statements.approve_statement_stage1(
            statement_id=seeded.statement.id,
            db=db,
            user_id=test_user.id,
            request=Stage1ApprovalRequest(create_account_if_missing=False),
        )
    assert response.status.value == "approved"
    lines = (await db.execute(select(JournalLine).where(JournalLine.account_id == bank.id))).scalars().all()
    assert sum(
        (line.amount if line.direction.value == "DEBIT" else -line.amount for line in lines), Decimal("0")
    ) == Decimal("900")


async def test_concurrent_opening_initialization(db_engine):
    """AC-ledger.opening-position.2: independent database sessions race on one account."""
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with sessions() as setup:
        user = await UserFactory.create_async(setup, email=f"opening-{uuid4()}@example.invalid")
        bank = await account(setup, user.id)
        uid, aid = user.id, bank.id
        await setup.commit()

    async def initialize():
        async with sessions() as session:
            entry = await initialize_opening_positions(
                session,
                uid,
                entry_date=date(2026, 1, 1),
                balances={aid: Decimal("1000")},
                currency="SGD",
                base_currency="SGD",
            )
            await session.commit()
            return entry.id

    results = await asyncio.gather(initialize(), initialize())
    assert results[0] == results[1]
    async with sessions() as session:
        positions = await list_opening_positions(session, user_id=uid, as_of=date(2026, 1, 31))
        assert len(positions) == 1
        assert positions[0].amount == Decimal("1000")


async def test_zero_and_per_account_readiness(db, test_user):
    """AC-ledger.opening-position.3: one initialized account cannot mask another."""
    first = await account(db, test_user.id, "Initialized")
    second = await account(db, test_user.id, "Explicit zero")
    await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2026, 1, 1),
        balances={first.id: Decimal("100"), second.id: Decimal("0")},
        currency="SGD",
        base_currency="SGD",
    )
    positions = await list_opening_positions(db, user_id=test_user.id, as_of=date(2026, 1, 31))
    zero = next(p for p in positions if p.account_id == second.id)
    assert zero.amount == 0 and zero.journal_entry_id is None
    assert zero.decision is not None
    assert (await get_opening_balance_readiness(db, test_user.id))["needs_opening_balance"] is False


async def test_foreign_opening_and_missing_rate(db, test_user):
    """AC-ledger.opening-position.4: original currency survives with a real FX basis."""
    bank = await account(db, test_user.id, currency="USD")
    with pytest.raises(ValidationError, match="FX rate"):
        await initialize_opening_positions(
            db,
            test_user.id,
            entry_date=date(2026, 1, 1),
            balances={bank.id: Decimal("100")},
            currency="USD",
            base_currency="SGD",
        )
    entry = await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2026, 1, 1),
        balances={bank.id: Decimal("100")},
        currency="USD",
        base_currency="SGD",
        fx_rates={"USD": Decimal("1.35")},
    )
    assert any(line.currency == "USD" and line.fx_rate == Decimal("1.35") for line in entry.lines)
    assert any(line.currency == "SGD" and line.amount == Decimal("135") for line in entry.lines)


async def test_opening_projection_and_immutability(db, test_user):
    """AC-ledger.opening-position.5: initialization facts reject in-place edits."""
    bank = await account(db, test_user.id)
    await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2026, 1, 1),
        balances={bank.id: Decimal("100")},
        currency="SGD",
        base_currency="SGD",
    )
    await db.commit()
    with pytest.raises(DBAPIError):
        async with db.begin_nested():
            await db.execute(
                text("UPDATE opening_position_records SET amount=999 WHERE account_id=:id"), {"id": bank.id}
            )


async def test_opening_projection_preserves_date(db, test_user):
    """AC-ledger.opening-position.6: same-day stock is an explicit published fact."""
    bank = await account(db, test_user.id)
    entry = await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2026, 1, 1),
        balances={bank.id: Decimal("100")},
        currency="SGD",
        base_currency="SGD",
    )
    positions = await list_opening_positions(db, user_id=test_user.id, as_of=date(2026, 1, 1))
    assert positions[0].effective_date == entry.entry_date == date(2026, 1, 1)
    assert positions[0].decision is not None and positions[0].state == "authoritative"


async def test_statement_category_is_pinned(db, test_user):
    """AC-ledger.statement-category.1: statement classification is immutable journal evidence."""
    bank = await account(db, test_user.id)
    await add_reviewed_disposition_rule(
        db, user_id=test_user.id, keyword="synthetic expense", account_type=AccountType.EXPENSE, category="AUDIT"
    )
    seeded = await seed_parsed_statement(
        db,
        test_user.id,
        transactions=[
            {"description": "Synthetic expense", "amount": Decimal("100"), "direction": TransactionDirection.OUT}
        ],
    )
    seeded.statement.account_id = bank.id
    await db.commit()
    with patch.object(statements, "StorageService", DummyStorage):
        await statements.approve_statement_stage1(statement_id=seeded.statement.id, db=db, user_id=test_user.id)
    rows = (
        (
            await db.execute(
                select(JournalLine)
                .join(Account, Account.id == JournalLine.account_id)
                .where(Account.user_id == test_user.id, Account.type == AccountType.EXPENSE)
            )
        )
        .scalars()
        .all()
    )
    assert rows[0].tags["economic_category"] == "AUDIT"


async def test_stale_journal_authority_invalidates_opening(db, test_user):
    """AC-ledger.opening-position.5: a separate stock decision cannot mask a stale journal."""
    from datetime import UTC, datetime

    from src.audit import TraceEmitter, TraceRecord, TraceResult, TraceScope, TraceTargetClass, VersionedTraceRef
    from src.audit.extension.trace_repository import SqlTraceRecordRepository
    from src.ledger import ledger_trace_policy_registry
    from src.ledger.extension.anchored_posting import SystemJournalCommandPolicy

    bank = await account(db, test_user.id)
    entry = await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2026, 1, 1),
        balances={bank.id: Decimal("100")},
        currency="SGD",
        base_currency="SGD",
    )
    repo = SqlTraceRecordRepository(db, ledger_trace_policy_registry())
    scope = TraceScope.tenant(test_user.id)
    previous = await repo.get(scope, entry.decision_anchor_id)
    policy = SystemJournalCommandPolicy()
    now = datetime.now(UTC)
    observation = TraceRecord.observation(
        scope=scope,
        target=previous.target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef("ledger_system_input", "opening-balance", "1"),
        authority=policy.authority,
        result=TraceResult.FAIL,
        execution_id="synthetic-revoked-opening",
        evidence_manifest_digest=previous.target.version,
        occurred_at=now,
        reason_code="synthetic_authority_revoked",
        score=None,
    )
    revoked = TraceRecord.decision(
        scope=scope,
        target=previous.target,
        policy=policy,
        execution_id=observation.execution_id,
        occurred_at=now,
        parents=(observation,),
        supersedes_id=previous.record_id,
    )
    await TraceEmitter(repo).emit_many((observation, revoked))
    positions = await list_opening_positions(db, user_id=test_user.id, as_of=date(2026, 1, 31))
    assert len(positions) == 1 and positions[0].state == "unproven"
    assert positions[0].decision is None


async def test_void_opening_does_not_return_stock(db, test_user):
    """AC-ledger.opening-position.5: a void correction does not resurrect a stock."""
    from src.ledger import void_journal_entry

    bank = await account(db, test_user.id)
    entry = await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2026, 1, 1),
        balances={bank.id: Decimal("100")},
        currency="SGD",
        base_currency="SGD",
    )
    await void_journal_entry(db, entry.id, reason="Synthetic correction", user_id=test_user.id, base_currency="SGD")
    positions = await list_opening_positions(db, user_id=test_user.id, as_of=date(2026, 1, 31))
    assert positions == ()


async def test_foreign_cent_boundaries_round_total_once(db, test_user):
    """AC-ledger.opening-position.4: two half-cent base legs remain a full cent."""
    first = await account(db, test_user.id, "First fractional FX", "USD")
    second = await account(db, test_user.id, "Second fractional FX", "USD")
    entry = await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2026, 1, 1),
        balances={first.id: Decimal("0.01"), second.id: Decimal("0.01")},
        currency="USD",
        base_currency="SGD",
        fx_rates={"USD": Decimal("0.5")},
    )
    await db.commit()
    await db.refresh(entry, ["lines"])
    from src.ledger import validate_journal_balance

    validate_journal_balance(entry.lines, base_currency="SGD")
    assert sum((line.amount for line in entry.lines if line.currency == "SGD"), Decimal("0")) == Decimal("0.01")
    assert len([line for line in entry.lines if line.currency == "USD" and line.fx_rate == Decimal("0.5")]) == 2


async def test_void_latest_opening_does_not_resurrect_earlier_version(db, test_user):
    """AC-ledger.opening-position.5: an old journal is history after stock correction."""
    from src.ledger import JournalEntryStatus, void_journal_entry
    from src.ledger.extension.anchored_posting import submit_system_journal_entry
    from src.ledger.extension.opening_positions import record_opening_position

    bank = await account(db, test_user.id)
    old = await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2026, 1, 1),
        balances={bank.id: Decimal("100")},
        currency="SGD",
        base_currency="SGD",
    )
    # Model the append-only corrected stock evidence. The old journal deliberately
    # remains posted here so the test detects fallback resurrection independently.
    newer = await submit_system_journal_entry(
        db,
        user_id=test_user.id,
        entry_date=date(2026, 1, 1),
        memo="Synthetic corrected stock",
        operation="opening-balance",
        base_currency="SGD",
        lines_data=[
            {"account_id": line.account_id, "direction": line.direction, "amount": Decimal("200"), "currency": "SGD"}
            for line in old.lines
        ],
    )
    await record_opening_position(
        db,
        user_id=test_user.id,
        account_id=bank.id,
        effective_date=date(2026, 1, 1),
        amount=Decimal("200"),
        currency="SGD",
        fx_rate=None,
        journal_entry_id=newer.id,
    )
    assert (await list_opening_positions(db, user_id=test_user.id, as_of=date(2026, 1, 31)))[0].amount == Decimal("200")
    await void_journal_entry(
        db, newer.id, reason="Synthetic correction withdrawn", user_id=test_user.id, base_currency="SGD"
    )
    assert old.status == JournalEntryStatus.POSTED
    assert await list_opening_positions(db, user_id=test_user.id, as_of=date(2026, 1, 31)) == ()


@pytest.mark.parametrize("opening", ["1000", "0"])
async def test_source_opening_retains_pdf_ancestor(db, test_user, opening):
    """AC-ledger.opening-position.8: both monetary and zero stock drill down to source."""
    from datetime import UTC, datetime
    from pathlib import Path
    from unittest.mock import AsyncMock

    from src.audit import SqlTraceRecordRepository, TraceDecisionPolicyRegistry, TraceEmitter, TraceScope
    from src.extraction import DocumentSource, extraction_trace_policy_registry, resolve_statement_contribution
    from src.extraction.extension.extraction_trace import build_extraction_trace_records
    from src.extraction.extension.reviewed_statement_envelope import persist_statement_extraction_result
    from src.extraction.extension.service import ExtractionService
    from src.extraction.extension.statement_posting import try_auto_approve_high_confidence_statement
    from src.ledger import ledger_trace_policy_registry
    from tests.integration.test_statement_opening_balance_auto_post import _attach_reviewed_semantic_dispositions
    from tests.statement_ingestion import parse_and_load_statement_projection, posting_dependencies

    payload = {
        "institution": "GXS",
        "account_last4": "1234",
        "currency": "SGD",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "opening_balance": opening,
        "closing_balance": str(Decimal(opening) + Decimal("100")),
        "transactions": [
            {
                "date": "2026-01-10",
                "description": "Salary credit",
                "amount": "100",
                "direction": "IN",
                "currency": "SGD",
                "balance_after": str(Decimal(opening) + Decimal("100")),
            }
        ],
    }
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(return_value=payload)
    result, statement, transactions = await parse_and_load_statement_projection(
        service,
        db=db,
        source=DocumentSource.resolve(path=Path("synthetic-opening.pdf"), content=b"%PDF-1.7"),
        institution="GXS",
        user_id=test_user.id,
    )
    traces = build_extraction_trace_records(
        result, user_id=test_user.id, execution_id="synthetic-source-opening", occurred_at=datetime.now(UTC)
    )
    await TraceEmitter(SqlTraceRecordRepository(db, extraction_trace_policy_registry())).emit_many(traces)
    await persist_statement_extraction_result(
        db, statement=statement, result=result, source_trace_record_id=traces[0].record_id
    )
    await _attach_reviewed_semantic_dispositions(db, test_user.id, transactions)
    posted = await try_auto_approve_high_confidence_statement(
        db, statement.id, test_user.id, dependencies=posting_dependencies()
    )
    assert posted > 0, statement.validation_error
    source = await resolve_statement_contribution(db, user_id=test_user.id, statement_id=statement.id)
    position = (await list_opening_positions(db, user_id=test_user.id, as_of=date(2026, 1, 31)))[0]
    repository = SqlTraceRecordRepository(
        db,
        TraceDecisionPolicyRegistry(
            (*extraction_trace_policy_registry().policies, *ledger_trace_policy_registry().policies)
        ),
    )
    pending, visited = [position.decision.decision_id], set()
    while pending:
        record_id = pending.pop()
        if record_id in visited:
            continue
        visited.add(record_id)
        record = await repository.get(TraceScope.tenant(test_user.id), record_id)
        pending.extend(record.parent_ids)
    assert source.decision.decision_id in visited
    assert position.source_decision == source.decision
    assert (position.journal_entry_id is None) == (opening == "0")
