from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import src.reporting.extension.package_document as package_document_mod
import tests.integration.test_trusted_year_scenario as trusted_year_mod
from src.audit import SqlTraceRecordRepository, TraceEmitter
from src.database import create_session_maker_from_db
from src.extraction import (
    BankStatementStatus,
    ExtractedTransactionFact,
    ExtractionMethod,
    ParseJob,
    RetireStatementCommand,
    SourceProvenance,
    StatementBalanceFact,
    StatementEvidenceType,
    StatementExtractionResult,
    StatementSourceType,
    StatementSummary,
    coverage_bank_custody_account_ids,
    extraction_trace_policy_registry,
    persist_statement_extraction_result,
    retire_statement,
)
from src.extraction.extension import statement_posting as statement_posting_mod
from src.extraction.extension.extraction_trace import build_extraction_trace_records
from src.extraction.extension.reviewed_statement_envelope import current_reviewed_statement_envelope
from src.extraction.extension.statement_contribution import resolve_statement_contribution
from src.extraction.orm.reviewed_statement_envelope import ReviewedStatementEnvelope, StatementExtractionResultRecord
from src.identity import User
from src.ledger import Account, AccountType, initialize_opening_positions
from src.reporting import current_package_readiness, generate_cash_flow, report_coverage
from src.request_context import RequestContext
from src.routers import reports as reports_router
from tests._support.trusted_year import TRUSTED_YEAR_SCENARIO
from tests.integration.test_trusted_year_scenario import _bank_csv
from tests.reporting._report_fixtures import count_sql_statements, seed_accounts, seed_ready_package_state
from tests.statement_ingestion import execute_statement_ingestion, posting_dependencies, run_for

AS_OF = date(2026, 10, 22)
COVERAGE_QUERY_BUDGET = 6


async def _approved_statement(db: AsyncSession, user_id: UUID, account: Account, period_start: date) -> None:
    db.add(
        StatementSummary(
            user_id=user_id,
            file_hash=sha256(f"{user_id}:{account.id}:{period_start}".encode()).hexdigest(),
            institution="DBS",
            account_id=account.id,
            currency="SGD",
            period_start=period_start,
            period_end=period_start + timedelta(days=27),
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("1200.00"),
            status=BankStatementStatus.APPROVED,
        )
    )
    await db.flush()


async def _statement_with_source(
    db: AsyncSession,
    user_id: UUID,
    account: Account,
    *,
    period_start: date | None,
    period_end: date | None,
    status: BankStatementStatus = BankStatementStatus.APPROVED,
    source_type: StatementSourceType = StatementSourceType.BANK,
    earlier_source_type: StatementSourceType | None = None,
    result_period_start: date | str | None = None,
    envelope_period_start: date | None = None,
    superseded_envelope_period_start: date | None = None,
    earlier_envelope_period_start: date | None = None,
) -> StatementSummary:
    stmt = StatementSummary(
        user_id=user_id,
        file_hash=sha256(f"{user_id}:{account.id}:{period_start}:{status}:{source_type}".encode()).hexdigest(),
        institution="DBS",
        account_id=account.id,
        currency="SGD",
        period_start=period_start,
        period_end=period_end,
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("1200.00"),
        status=status,
    )
    db.add(stmt)
    await db.flush()
    records = []
    for idx, kind in enumerate(([earlier_source_type] if earlier_source_type else []) + [source_type]):
        extra = (
            {}
            if result_period_start is None
            else {
                "period_start": result_period_start
                if isinstance(result_period_start, str)
                else result_period_start.isoformat()
            }
        )
        rec = StatementExtractionResultRecord(
            user_id=user_id,
            statement_id=stmt.id,
            content_digest=sha256(f"result:{stmt.id}:{idx}".encode()).hexdigest(),
            source_content_digest=sha256(f"source:{stmt.id}".encode()).hexdigest(),
            schema_version="2",
            producer_version="coverage-fixture",
            payload={"source_type": kind.value} | extra,
            source_trace_record_id=uuid4(),
            created_at=datetime.now(UTC),
        )
        db.add(rec)
        records.append(rec)
    await db.flush()
    stmt.current_extraction_result_id = records[-1].id
    chains = [(records[-1], (superseded_envelope_period_start, envelope_period_start))] + (
        [(records[0], (earlier_envelope_period_start,))] if earlier_source_type else []
    )
    for rec, starts in chains:
        prev = None
        for idx, env_start in enumerate(s for s in starts if s is not None):
            env = ReviewedStatementEnvelope(
                user_id=user_id,
                statement_id=stmt.id,
                source_result_id=rec.id,
                account_id=account.id,
                currency="SGD",
                period_start=env_start,
                period_end=env_start + timedelta(days=27),
                opening_balance=Decimal("1000.00"),
                closing_balance=Decimal("1200.00"),
                rationale="coverage",
                command_digest=sha256(f"env:{rec.id}:{idx}".encode()).hexdigest(),
                review_trace_record_id=uuid4(),
                supersedes_id=prev.id if prev else None,
                created_at=datetime.now(UTC) + timedelta(seconds=idx),
            )
            db.add(env)
            await db.flush()
            prev = env
    return stmt


async def _seed_first_bank(db: AsyncSession, user_id: UUID, monkeypatch: pytest.MonkeyPatch) -> Account:
    bank, _, _ = await seed_ready_package_state(
        db,
        user_id,
        monkeypatch,
        opening_date=date(2026, 6, 5),
        opening_cash=TRUSTED_YEAR_SCENARIO.opening_cash,
        with_card=True,
    )
    return bank


def _keep_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        trusted_year_mod, "approve_statement_with_transactions", lambda db, sid, _uid: _get_stmt(db, sid)
    )
    monkeypatch.setattr(
        trusted_year_mod,
        "auto_create_posted_entries_for_statement",
        lambda *_a, **_kw: _async_val(SimpleNamespace(review_reasons=(), created_count=2)),
    )


async def _get_stmt(db, sid):
    return await db.get(StatementSummary, sid), []


async def _async_val(v):
    return v


async def _package_cash_and_custody(db: AsyncSession, user_id: UUID, as_of: date) -> tuple[frozenset, frozenset]:
    contribs = await package_document_mod.PackageAssembler()._contributions(
        db, user_id=user_id, start_date=as_of - timedelta(days=365), end_date=as_of, as_of_date=as_of
    )
    return package_document_mod._cash_inputs_from_contributions(
        contribs
    ).account_ids, await coverage_bank_custody_account_ids(db, user_id=user_id, as_of=as_of)


@pytest.mark.parametrize("as_of", [date(2026, 6, 30), date(2026, 6, 12)])
async def test_AC_reporting_2646_first_statement_coverage_and_readiness(
    db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch, as_of: date
) -> None:
    await _seed_first_bank(db, test_user.id, monkeypatch)
    cov = await report_coverage(db, user_id=test_user.id, as_of=as_of)
    assert (cov.start, cov.limiting_account_names) == (date(2026, 6, 5), ("DBS",))
    assert [
        b.code
        for b in (
            await current_package_readiness(db, user_id=test_user.id, as_of_date=as_of, base_currency="SGD")
        ).blockers
    ] == []


@pytest.mark.parametrize(
    ("specs", "expected_names", "with_foreign"),
    [
        (
            [
                ("Approved", {"period_start": date(2026, 5, 1), "period_end": date(2026, 5, 28)}),
                ("Closes later", {"period_start": date(2026, 6, 5), "period_end": date(2026, 6, 15)}),
                (
                    "Retired",
                    {
                        "status": BankStatementStatus.RETIRED,
                        "period_start": date(2026, 5, 1),
                        "period_end": date(2026, 5, 28),
                    },
                ),
                (
                    "Rejected",
                    {
                        "status": BankStatementStatus.REJECTED,
                        "period_start": date(2026, 5, 1),
                        "period_end": date(2026, 5, 28),
                    },
                ),
                (
                    "Parsed",
                    {
                        "status": BankStatementStatus.PARSED,
                        "period_start": date(2026, 5, 1),
                        "period_end": date(2026, 5, 28),
                    },
                ),
                (
                    "Brokerage",
                    {
                        "source_type": StatementSourceType.BROKERAGE,
                        "period_start": date(2026, 5, 1),
                        "period_end": date(2026, 5, 28),
                    },
                ),
                (
                    "Brokerage over bank",
                    {
                        "source_type": StatementSourceType.BROKERAGE,
                        "earlier_source_type": StatementSourceType.BANK,
                        "period_start": date(2026, 5, 1),
                        "period_end": date(2026, 5, 28),
                    },
                ),
                ("Starts later", {"period_start": date(2026, 6, 13), "period_end": date(2026, 7, 10)}),
                ("Starts on the date", {"period_start": date(2026, 6, 12), "period_end": date(2026, 7, 10)}),
            ],
            ["Approved", "Closes later", "Parsed", "Rejected", "Retired", "Starts on the date"],
            True,
        ),
        (
            [
                (
                    "Result start only",
                    {
                        "period_start": None,
                        "period_end": None,
                        "status": BankStatementStatus.PARSED,
                        "result_period_start": date(2026, 5, 1),
                    },
                ),
                ("Summary start only", {"period_start": date(2026, 5, 1), "period_end": date(2026, 5, 28)}),
                (
                    "Envelope moves the start before",
                    {
                        "period_start": date(2026, 6, 20),
                        "period_end": date(2026, 7, 10),
                        "result_period_start": date(2026, 6, 20),
                        "envelope_period_start": date(2026, 5, 1),
                    },
                ),
                (
                    "Envelope moves the start after",
                    {
                        "period_start": date(2026, 5, 1),
                        "period_end": date(2026, 7, 10),
                        "result_period_start": date(2026, 5, 1),
                        "envelope_period_start": date(2026, 6, 20),
                    },
                ),
                (
                    "Newest envelope moves the start before",
                    {
                        "period_start": date(2026, 6, 20),
                        "period_end": date(2026, 7, 10),
                        "result_period_start": date(2026, 6, 20),
                        "superseded_envelope_period_start": date(2026, 6, 20),
                        "envelope_period_start": date(2026, 5, 1),
                    },
                ),
                (
                    "Newest envelope moves the start after",
                    {
                        "period_start": date(2026, 5, 1),
                        "period_end": date(2026, 7, 10),
                        "result_period_start": date(2026, 5, 1),
                        "superseded_envelope_period_start": date(2026, 5, 1),
                        "envelope_period_start": date(2026, 6, 20),
                    },
                ),
                (
                    "Result over summary",
                    {
                        "period_start": date(2026, 5, 1),
                        "period_end": date(2026, 7, 10),
                        "result_period_start": date(2026, 6, 20),
                    },
                ),
                (
                    "Result moves the start before",
                    {
                        "period_start": date(2026, 6, 20),
                        "period_end": date(2026, 7, 10),
                        "result_period_start": date(2026, 5, 1),
                    },
                ),
                (
                    "Envelope on an older result",
                    {
                        "period_start": date(2026, 6, 20),
                        "period_end": date(2026, 7, 10),
                        "earlier_source_type": StatementSourceType.BANK,
                        "result_period_start": date(2026, 6, 20),
                        "earlier_envelope_period_start": date(2026, 5, 1),
                    },
                ),
                (
                    "Empty result start, summary start before",
                    {"period_start": date(2026, 5, 1), "period_end": date(2026, 5, 28), "result_period_start": ""},
                ),
                (
                    "Empty result start, no summary start",
                    {
                        "period_start": None,
                        "period_end": None,
                        "status": BankStatementStatus.PARSED,
                        "result_period_start": "",
                    },
                ),
            ],
            [
                "Empty result start, summary start before",
                "Envelope moves the start before",
                "Newest envelope moves the start before",
                "Result moves the start before",
                "Result start only",
                "Summary start only",
            ],
            False,
        ),
    ],
)
async def test_AC_reporting_2646_2_custody_account_selection_and_precedence(
    db: AsyncSession, test_user, specs: list[tuple], expected_names: list[str], with_foreign: bool
) -> None:
    accounts = await seed_accounts(db, test_user.id, *[(n, AccountType.ASSET) for n, _ in specs])
    for acc, (_, kw) in zip(accounts, specs):
        await _statement_with_source(db, test_user.id, acc, **kw)
    by_id = {acc.id: acc.name for acc in accounts}
    if with_foreign:
        other = User(email="custody-other@example.com", hashed_password="hashed")
        db.add(other)
        await db.flush()
        [other_bank] = await seed_accounts(db, other.id, ("Other Bank", AccountType.ASSET))
        await _statement_with_source(
            db, other.id, other_bank, period_start=date(2026, 5, 1), period_end=date(2026, 5, 28)
        )
        by_id[other_bank.id] = "Other Bank"
    await db.commit()
    selected = await coverage_bank_custody_account_ids(db, user_id=test_user.id, as_of=date(2026, 6, 12))
    assert sorted(by_id[aid] for aid in selected) == expected_names


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("approved", BankStatementStatus.APPROVED),
        ("envelope confirmed, not approved", BankStatementStatus.PARSED),
        ("retired after approval", BankStatementStatus.RETIRED),
    ],
)
async def test_AC_reporting_2646_2_the_custody_set_contains_the_package_cash_set(
    db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch, path: str, status: BankStatementStatus
) -> None:
    as_of = date(2026, 6, 30)
    if status is BankStatementStatus.PARSED:
        _keep_parsed(monkeypatch)
    bank = await _seed_first_bank(db, test_user.id, monkeypatch)
    stmt = (await db.execute(select(StatementSummary).where(StatementSummary.account_id == bank.id))).scalar_one()
    if path == "retired after approval":
        await retire_statement(
            db, RetireStatementCommand(statement_id=stmt.id, user_id=test_user.id), base_currency="SGD"
        )
        await db.commit()
    await db.refresh(stmt)
    assert stmt.status is status
    pkg_cash, custody = await _package_cash_and_custody(db, test_user.id, as_of)
    assert bank.id in pkg_cash and pkg_cash <= custody
    assert (await report_coverage(db, user_id=test_user.id, as_of=as_of)).start == date(2026, 6, 5)
    assert [
        b.code
        for b in (
            await current_package_readiness(db, user_id=test_user.id, as_of_date=as_of, base_currency="SGD")
        ).blockers
    ] == []


async def test_AC_reporting_2646_2_reparse_and_auto_approval_fallback_keep_statement(
    db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id, as_of = test_user.id, date(2026, 6, 30)
    _keep_parsed(monkeypatch)
    bank = await _seed_first_bank(db, user_id, monkeypatch)
    stmt = (await db.execute(select(StatementSummary).where(StatementSummary.account_id == bank.id))).scalar_one()
    res_before = stmt.current_extraction_result_id
    stmt.status, stmt.validation_error = BankStatementStatus.PARSING, None
    await db.commit()
    await execute_statement_ingestion(
        ParseJob(
            statement_id=stmt.id,
            run_id=await run_for(db, stmt.id),
            filename="trusted-year-v0.csv",
            institution="DBS",
            user_id=user_id,
            account_id=bank.id,
            file_hash=stmt.file_hash,
            storage_key="trusted-year/v0.csv",
            model=None,
        ),
        content=_bank_csv(),
        session_maker=create_session_maker_from_db(db),
    )
    db.expire_all()
    reparsed = await db.get(StatementSummary, stmt.id)
    env = await current_reviewed_statement_envelope(db, user_id=user_id, statement_id=stmt.id)
    assert (reparsed.current_extraction_result_id, reparsed.period_start, env.period_start) == (
        res_before,
        date(2026, 6, 5),
        date(2026, 6, 5),
    )
    reparsed.period_start = reparsed.period_end = None
    await db.commit()
    pkg_cash, custody = await _package_cash_and_custody(db, user_id, as_of)
    assert (
        bank.id in pkg_cash
        and pkg_cash <= custody
        and (await report_coverage(db, user_id=user_id, as_of=as_of)).start == date(2026, 6, 5)
    )
    assert "opening_coverage_starts_after_period" not in [
        b.code
        for b in (await current_package_readiness(db, user_id=user_id, as_of_date=as_of, base_currency="SGD")).blockers
    ]

    [fb_bank] = await seed_accounts(db, user_id, ("Fallback DBS", AccountType.ASSET))
    fb_stmt = StatementSummary(
        user_id=user_id,
        file_hash=sha256(b"fb").hexdigest(),
        institution="DBS",
        account_id=fb_bank.id,
        currency="SGD",
        period_start=date(2026, 6, 5),
        period_end=date(2026, 6, 15),
        opening_balance=Decimal("1000"),
        closing_balance=Decimal("1100"),
        status=BankStatementStatus.APPROVED,
        confidence_score=99,
        balance_validated=True,
    )
    db.add(fb_stmt)
    await db.flush()
    src_res = StatementExtractionResult.create(
        producer_version="csv-parser@1",
        source_content_digest="c" * 64,
        source_type=StatementSourceType.BANK,
        evidence_type=StatementEvidenceType.TRANSACTION_LEDGER,
        institution="DBS",
        account_last4="7174",
        period_start=date(2026, 6, 5),
        period_end=date(2026, 6, 15),
        balances=(StatementBalanceFact(currency="SGD", opening=Decimal("1000"), closing=Decimal("1100")),),
        transactions=(
            ExtractedTransactionFact(
                fact_id="r1",
                transaction_date=date(2026, 6, 10),
                description="Salary",
                amount=Decimal("100"),
                direction="IN",
                currency="SGD",
                balance_after=Decimal("1100"),
                confidence=Decimal("0.95"),
            ),
        ),
        positions=(),
        confidence=Decimal("0.95"),
        balance_validated=True,
        warnings=(),
        review_reasons=(),
        provenance=SourceProvenance(
            intake_mode="csv", method=ExtractionMethod.DETERMINISTIC, provider="csv", model="csv@1"
        ),
        statement_currency="SGD",
    )
    traces = build_extraction_trace_records(
        src_res, user_id=user_id, execution_id=f"t:{fb_stmt.id}", occurred_at=datetime.now(UTC)
    )
    await TraceEmitter(SqlTraceRecordRepository(db, extraction_trace_policy_registry())).emit_many(traces)
    await persist_statement_extraction_result(
        db, statement=fb_stmt, result=src_res, source_trace_record_id=traces[0].record_id
    )
    await initialize_opening_positions(
        db,
        user_id,
        entry_date=date(2026, 6, 5),
        balances={fb_bank.id: Decimal("1000")},
        currency="SGD",
        base_currency="SGD",
    )
    await db.commit()

    async def guard_fails(*_a, **_kw):
        raise ValueError("Custody account must be a non-system asset account")

    monkeypatch.setattr(statement_posting_mod, "approve_statement_with_transactions", guard_fails)
    created = await statement_posting_mod.try_auto_approve_high_confidence_statement(
        db, fb_stmt.id, user_id, dependencies=posting_dependencies()
    )
    await db.commit()
    await db.refresh(fb_stmt)
    assert (created, fb_stmt.status) == (0, BankStatementStatus.PARSED) and await current_reviewed_statement_envelope(
        db, user_id=user_id, statement_id=fb_stmt.id
    ) is None
    assert (
        await resolve_statement_contribution(db, user_id=user_id, statement_id=fb_stmt.id)
    ).decision.target.kind == "statement_extraction_result"
    pkg_cash2, custody2 = await _package_cash_and_custody(db, user_id, as_of)
    assert fb_bank.id in pkg_cash2 and pkg_cash2 <= custody2


async def test_AC_reporting_2646_2_bound_checks_latest_opening_and_pre_statement_history(
    db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = test_user.id
    periods: list[tuple[date, date]] = []
    real_eval = package_document_mod.PackageAssembler.evaluate_readiness

    async def rec_eval(self, db, **kw):
        periods.append((kw["start_date"], kw["end_date"]))
        return await real_eval(self, db, **kw)

    monkeypatch.setattr(package_document_mod.PackageAssembler, "evaluate_readiness", rec_eval)
    assert await report_coverage(db, user_id=user_id, as_of=AS_OF) == package_document_mod.CashCoverage(None, ())
    await current_package_readiness(db, user_id=user_id, as_of_date=AS_OF, base_currency="SGD")
    assert periods[-1] == (AS_OF - timedelta(days=365), AS_OF)

    s1, s2, card = await seed_accounts(
        db,
        user_id,
        ("DBS Savings", AccountType.ASSET),
        ("OCBC Bank", AccountType.ASSET),
        ("Visa card", AccountType.LIABILITY),
    )
    await initialize_opening_positions(
        db,
        user_id,
        entry_date=date(2026, 6, 5),
        balances={s1.id: Decimal("1000"), s2.id: Decimal("500")},
        currency="SGD",
        base_currency="SGD",
    )
    await initialize_opening_positions(
        db, user_id, entry_date=date(2026, 3, 1), balances={s2.id: Decimal("500")}, currency="SGD", base_currency="SGD"
    )
    await initialize_opening_positions(
        db,
        user_id,
        entry_date=date(2026, 5, 1),
        balances={card.id: Decimal("-300")},
        currency="SGD",
        base_currency="SGD",
    )
    await _approved_statement(db, user_id, card, date(2026, 5, 1))
    db.add(
        StatementSummary(
            user_id=user_id,
            file_hash="b" * 64,
            institution="DBS",
            account_id=s1.id,
            currency="SGD",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            status=BankStatementStatus.PARSED,
        )
    )
    other = User(email="coverage-other@example.com", hashed_password="hashed")
    db.add(other)
    await db.flush()
    [o_bank] = await seed_accounts(db, other.id, ("Other Bank", AccountType.ASSET))
    await initialize_opening_positions(
        db,
        other.id,
        entry_date=date(2025, 12, 1),
        balances={o_bank.id: Decimal("1000")},
        currency="SGD",
        base_currency="SGD",
    )
    await _approved_statement(db, other.id, o_bank, date(2025, 12, 1))
    await db.commit()

    cash_ids = frozenset({s1.id, s2.id})
    assert (
        "opening_coverage_starts_after_period"
        not in (
            await generate_cash_flow(
                db,
                user_id,
                start_date=date(2026, 6, 5),
                end_date=date(2026, 6, 30),
                currency="SGD",
                cash_account_ids=cash_ids,
            )
        )["proof_reasons"]
    )
    assert (
        "opening_coverage_starts_after_period"
        in (
            await generate_cash_flow(
                db,
                user_id,
                start_date=date(2026, 6, 4),
                end_date=date(2026, 6, 30),
                currency="SGD",
                cash_account_ids=cash_ids,
            )
        )["proof_reasons"]
    )
    cov = await report_coverage(db, user_id=user_id, as_of=AS_OF)
    assert (cov.start, cov.limiting_account_names) == (date(2026, 6, 5), ("DBS Savings", "OCBC Bank"))
    await current_package_readiness(db, user_id=user_id, as_of_date=AS_OF, base_currency="SGD")
    assert periods[-1] == (date(2026, 6, 5), AS_OF)
    await current_package_readiness(db, user_id=user_id, as_of_date=date(2026, 5, 31), base_currency="SGD")
    assert periods[-1] == (date(2026, 3, 1), date(2026, 5, 31))
    resp = await reports_router.report_coverage(as_of_date=AS_OF, ctx=RequestContext(db, user_id))
    assert (resp.as_of_date, resp.coverage_start, resp.limiting_accounts) == (
        AS_OF,
        date(2026, 6, 5),
        ["DBS Savings", "OCBC Bank"],
    )

    await initialize_opening_positions(
        db, user_id, entry_date=date(2026, 1, 1), balances={s1.id: Decimal("100")}, currency="SGD", base_currency="SGD"
    )
    await _approved_statement(db, user_id, s1, date(2026, 6, 5))
    await db.commit()
    assert (await report_coverage(db, user_id=user_id, as_of=AS_OF)).start == date(2026, 3, 1)


async def test_AC_reporting_2646_3_and_2726_1_query_budget_and_latest_approved_end(
    db: AsyncSession, db_engine, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id, as_of = test_user.id, date(2026, 6, 30)
    assert (
        await reports_router.report_coverage(as_of_date=date(2026, 10, 27), ctx=RequestContext(db, user_id))
    ).latest_statement_end is None
    bank = await _seed_first_bank(db, user_id, monkeypatch)
    seeded = (await db.execute(select(StatementSummary).where(StatementSummary.account_id == bank.id))).scalar_one()
    tpl = await db.get(StatementExtractionResultRecord, seeded.current_extraction_result_id)
    for idx in range(35):
        ps = date(2023, 6, 5) + timedelta(days=30 * idx)
        s = StatementSummary(
            user_id=user_id,
            file_hash=sha256(f"ys-{idx}".encode()).hexdigest(),
            institution="DBS",
            account_id=bank.id,
            currency="SGD",
            period_start=ps,
            period_end=ps + timedelta(days=27),
            opening_balance=Decimal("1000"),
            closing_balance=Decimal("1000"),
            status=BankStatementStatus.APPROVED,
        )
        db.add(s)
        await db.flush()
        rec = StatementExtractionResultRecord(
            user_id=user_id,
            statement_id=s.id,
            content_digest=tpl.content_digest,
            source_content_digest=tpl.source_content_digest,
            schema_version=tpl.schema_version,
            producer_version=tpl.producer_version,
            payload=tpl.payload,
            source_trace_record_id=tpl.source_trace_record_id,
            created_at=tpl.created_at,
        )
        db.add(rec)
        await db.flush()
        s.current_extraction_result_id = rec.id
    await db.commit()
    with count_sql_statements(db_engine) as c_cov:
        resp = await reports_router.report_coverage(as_of_date=as_of, ctx=RequestContext(db, user_id))
    assert (resp.coverage_start, resp.latest_statement_end) == (date(2026, 6, 5), date(2026, 6, 30)) and c_cov[
        "count"
    ] <= COVERAGE_QUERY_BUDGET
    await current_package_readiness(db, user_id=user_id, as_of_date=as_of, base_currency="SGD")
    with count_sql_statements(db_engine) as c_b:
        await current_package_readiness(db, user_id=user_id, as_of_date=as_of, base_currency="SGD")
    known = await report_coverage(db, user_id=user_id, as_of=as_of)
    monkeypatch.setattr(package_document_mod, "report_coverage", lambda *_a, **_kw: _async_val(known))
    with count_sql_statements(db_engine) as c_u:
        await current_package_readiness(db, user_id=user_id, as_of_date=as_of, base_currency="SGD")
    assert c_b["count"] - c_u["count"] <= COVERAGE_QUERY_BUDGET
