"""The default report period starts no earlier than the cash coverage start (#2646).

Before #2646 the readiness of the current package always covered the 365 days before today. A user
whose cash accounts have their opening positions inside that window failed the cash-flow coverage
check (``opening_coverage_starts_after_period``), and Home showed "A blocker holds your reports".
The bound is the quantity that the check reads: the latest opening position of a cash account.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from common.testing.trusted_year import TRUSTED_YEAR_SCENARIO
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

import src.reporting.extension.package_document as package_document_mod
import tests.integration.test_trusted_year_scenario as trusted_year_mod
from src.audit import SqlTraceRecordRepository, TraceEmitter
from src.config import settings
from src.database import create_session_maker_from_db
from src.extraction import (
    BankStatementStatus,
    ExtractedTransactionFact,
    ExtractionMethod,
    ParseJob,
    RetireStatementCommand,
    RuleType,
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
from src.extraction.extension import statement_posting as statement_posting_mod, transaction_classification
from src.extraction.extension.extraction_trace import build_extraction_trace_records
from src.extraction.extension.reviewed_statement_envelope import current_reviewed_statement_envelope
from src.extraction.extension.statement_contribution import resolve_statement_contribution
from src.extraction.extension.transaction_classification import CategoryProposal, TransactionCategory
from src.extraction.orm.layer3 import ClassificationRule
from src.extraction.orm.reviewed_statement_envelope import StatementExtractionResultRecord
from src.identity import User
from src.ledger import Account, AccountType, initialize_opening_positions
from src.reporting import current_package_readiness, generate_cash_flow, report_coverage
from src.routers import reports as reports_router
from tests.integration.test_trusted_year_scenario import _bank_csv, _ingest_reviewed_bank_statement
from tests.statement_ingestion import (
    execute_statement_ingestion,
    posting_dependencies,
)

AS_OF = date(2026, 10, 22)


async def _approved_statement(db: AsyncSession, user_id: UUID, account: Account, period_start: date) -> None:
    """An approved statement envelope without a source result: it posts no opening position."""
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
    period_start: date,
    period_end: date,
    status: BankStatementStatus = BankStatementStatus.APPROVED,
    source_type: StatementSourceType = StatementSourceType.BANK,
    earlier_source_type: StatementSourceType | None = None,
) -> StatementSummary:
    """A statement with a current source result of ``source_type``, so the custody query reaches it.

    ``earlier_source_type`` adds an older result that is not current. Only the custody query reads
    these results: their payload holds the source type, no facts.
    """
    statement = StatementSummary(
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
    db.add(statement)
    await db.flush()
    records = []
    for index, kind in enumerate(([earlier_source_type] if earlier_source_type else []) + [source_type]):
        record = StatementExtractionResultRecord(
            user_id=user_id,
            statement_id=statement.id,
            content_digest=sha256(f"result:{statement.id}:{index}".encode()).hexdigest(),
            source_content_digest=sha256(f"source:{statement.id}".encode()).hexdigest(),
            schema_version="2",
            producer_version="coverage-fixture",
            payload={"source_type": kind.value},
            source_trace_record_id=uuid4(),
            created_at=datetime.now(UTC),
        )
        db.add(record)
        records.append(record)
    await db.flush()
    statement.current_extraction_result_id = records[-1].id
    await db.flush()
    return statement


async def _account(
    db: AsyncSession, user_id: UUID, name: str, account_type: AccountType = AccountType.ASSET
) -> Account:
    account = Account(user_id=user_id, name=name, type=account_type, currency="SGD")
    db.add(account)
    await db.flush()
    return account


async def _open(db: AsyncSession, user_id: UUID, account: Account, on: date, amount: str = "1000") -> None:
    await initialize_opening_positions(
        db, user_id, entry_date=on, balances={account.id: Decimal(amount)}, currency="SGD"
    )


def _record_readiness_periods(monkeypatch: pytest.MonkeyPatch) -> list[tuple[date, date]]:
    periods: list[tuple[date, date]] = []
    real_evaluate = package_document_mod.PackageAssembler.evaluate_readiness

    async def recording_evaluate(self, db, **kwargs):
        periods.append((kwargs["start_date"], kwargs["end_date"]))
        return await real_evaluate(self, db, **kwargs)

    monkeypatch.setattr(package_document_mod.PackageAssembler, "evaluate_readiness", recording_evaluate)
    return periods


async def _seed_first_bank_statement(db: AsyncSession, user_id: UUID, monkeypatch: pytest.MonkeyPatch) -> Account:
    """A new user: opening balances on 2026-06-05, one reviewed bank statement from 2026-06-05 to
    2026-06-15, and an approved card statement from May. Return the bank account."""
    monkeypatch.setattr(settings, "enable_ai_classification", True)

    async def proposer(transactions, _policy):
        categories = {"Salary credit": TransactionCategory.SALARY, "Rent debit": TransactionCategory.HOUSING}
        return [
            CategoryProposal(category=categories[item.description].value, confidence=99, reason="coverage-fixture")
            for item in transactions
        ]

    monkeypatch.setattr(transaction_classification, "propose_categories", proposer)
    # "DBS" matches no cash keyword: only the bank custody path of the package makes it cash.
    bank = await _account(db, user_id, "DBS")
    securities = await _account(db, user_id, "Securities")
    card = await _account(db, user_id, "Visa card", AccountType.LIABILITY)
    await initialize_opening_positions(
        db,
        user_id,
        entry_date=date(2026, 6, 5),
        balances={bank.id: TRUSTED_YEAR_SCENARIO.opening_cash, securities.id: Decimal("0")},
        currency="SGD",
    )
    await _approved_statement(db, user_id, card, date(2026, 5, 1))
    db.add(
        ClassificationRule(
            user_id=user_id,
            created_by=user_id,
            version_number=1,
            effective_date=date(2026, 1, 1),
            rule_name="Reviewed investment",
            rule_type=RuleType.KEYWORD_MATCH,
            rule_config={"keywords": ["Buy security"]},
            tag_mappings={"intent": "transfer"},
            default_account_id=securities.id,
        )
    )
    await _ingest_reviewed_bank_statement(db, user_id=user_id, bank=bank, securities_id=securities.id)
    await db.commit()
    return bank


async def test_AC_reporting_2646_1_first_statement_opening_has_no_coverage_blocker(
    db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-reporting.2646.1: a new user approves one bank statement (2026-06-05 to 2026-06-15). The
    ledger starts with its opening balances on 2026-06-05. A card statement from May is approved too.
    The current readiness on 2026-06-30 has no blocker at all: before #2646 its period started on
    2025-06-30, and a bound by the first approved statement (the May card statement) kept the
    ``opening_coverage_starts_after_period`` blocker."""
    user_id = test_user.id
    await _seed_first_bank_statement(db, user_id, monkeypatch)

    readiness = await current_package_readiness(db, user_id=user_id, as_of_date=date(2026, 6, 30))

    # Only the first sorted proof reason becomes a blocker code: assert that no blocker exists.
    assert [blocker.code for blocker in readiness.blockers] == []
    coverage = await report_coverage(db, user_id=user_id, as_of=date(2026, 6, 30))
    assert (coverage.start, coverage.limiting_account_names) == (date(2026, 6, 5), ("DBS",))


async def test_AC_reporting_2646_2_a_statement_that_closes_after_the_date_bounds_the_period(
    db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-reporting.2646.2: the bank statement of 2026-06-05 to 2026-06-15 closes after the date
    2026-06-12, and the package reads its movement before that date. Its custody account bounds the
    period, so the readiness on 2026-06-12 has no ``opening_coverage_starts_after_period``. A bound
    that kept only statements that close on or before the date had no start and this blocker."""
    user_id = test_user.id
    await _seed_first_bank_statement(db, user_id, monkeypatch)
    as_of = date(2026, 6, 12)

    coverage = await report_coverage(db, user_id=user_id, as_of=as_of)
    assert (coverage.start, coverage.limiting_account_names) == (date(2026, 6, 5), ("DBS",))
    readiness = await current_package_readiness(db, user_id=user_id, as_of_date=as_of)
    # Only the first sorted proof reason becomes a blocker code: assert that no blocker exists.
    assert [blocker.code for blocker in readiness.blockers] == []


async def test_AC_reporting_2646_2_custody_accounts_are_the_bank_statements_of_the_user_in_any_status(
    db: AsyncSession, test_user
) -> None:
    """AC-reporting.2646.2: ``coverage_bank_custody_account_ids`` keeps the custody account of a
    bank statement of the user in any status that starts on or before the date, also when it closes
    after it. Each negative control has a current source result, so only its own predicate removes
    it: a brokerage current result (also over an earlier bank result), a statement that starts after
    the date, and another user's statement."""
    user_id = test_user.id
    as_of = date(2026, 6, 12)
    names = (
        "Approved",
        "Closes later",
        "Retired",
        "Rejected",
        "Parsed",
        "Brokerage",
        "Brokerage over bank",
        "Starts later",
        "Starts on the date",
    )
    accounts = {name: await _account(db, user_id, name) for name in names}
    window = {"period_start": date(2026, 5, 1), "period_end": date(2026, 5, 28)}
    await _statement_with_source(db, user_id, accounts["Approved"], **window)
    await _statement_with_source(
        db, user_id, accounts["Closes later"], period_start=date(2026, 6, 5), period_end=date(2026, 6, 15)
    )
    await _statement_with_source(db, user_id, accounts["Retired"], status=BankStatementStatus.RETIRED, **window)
    await _statement_with_source(db, user_id, accounts["Rejected"], status=BankStatementStatus.REJECTED, **window)
    await _statement_with_source(db, user_id, accounts["Parsed"], status=BankStatementStatus.PARSED, **window)
    await _statement_with_source(
        db, user_id, accounts["Brokerage"], source_type=StatementSourceType.BROKERAGE, **window
    )
    # The current result is brokerage; an earlier result was bank. A join to any result keeps it.
    await _statement_with_source(
        db,
        user_id,
        accounts["Brokerage over bank"],
        source_type=StatementSourceType.BROKERAGE,
        earlier_source_type=StatementSourceType.BANK,
        **window,
    )
    await _statement_with_source(
        db, user_id, accounts["Starts later"], period_start=date(2026, 6, 13), period_end=date(2026, 7, 10)
    )
    # A statement that starts on the date counts: the filter is "on or before", not "before".
    await _statement_with_source(
        db, user_id, accounts["Starts on the date"], period_start=as_of, period_end=date(2026, 7, 10)
    )
    other = User(email="custody-other@example.com", hashed_password="hashed")
    db.add(other)
    await db.flush()
    other_bank = await _account(db, other.id, "Other Bank")
    await _statement_with_source(db, other.id, other_bank, **window)
    await db.commit()

    selected = await coverage_bank_custody_account_ids(db, user_id=user_id, as_of=as_of)
    by_id = {account.id: name for name, account in accounts.items()} | {other_bank.id: "Other Bank"}
    assert sorted(by_id[account_id] for account_id in selected) == [
        "Approved",
        "Closes later",
        "Parsed",
        "Rejected",
        "Retired",
        "Starts on the date",
    ]


def _keep_the_statement_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The seed confirms the reviewed envelope but does not approve: the statement stays parsed with
    an authoritative envelope decision, as before a user approves it."""

    async def not_approved(db, statement_id, _user_id):
        return await db.get(StatementSummary, statement_id)

    async def no_posting(*_args, **_kwargs):
        return SimpleNamespace(review_reasons=(), created_count=2)

    monkeypatch.setattr(trusted_year_mod, "approve_statement", not_approved)
    monkeypatch.setattr(trusted_year_mod, "auto_create_posted_entries_for_statement", no_posting)


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
    """AC-reporting.2646.2: the package keeps a bank statement by its trace decision, not by its
    status. On each real path the package cash account ids are a subset of
    ``coverage_bank_custody_account_ids``, and the readiness on 2026-06-30 has no blocker. A status
    filter dropped the parsed statement: the bound had no start and the readiness had
    ``opening_coverage_starts_after_period`` (the review probe)."""
    user_id = test_user.id
    if status is BankStatementStatus.PARSED:
        _keep_the_statement_parsed(monkeypatch)
    bank = await _seed_first_bank_statement(db, user_id, monkeypatch)
    statement = (await db.execute(select(StatementSummary).where(StatementSummary.account_id == bank.id))).scalar_one()
    if path == "retired after approval":
        await retire_statement(db, RetireStatementCommand(statement_id=statement.id, user_id=user_id))
        await db.commit()
    await db.refresh(statement)
    assert statement.status is status

    as_of = date(2026, 6, 30)
    contributions = await package_document_mod.PackageAssembler()._contributions(
        db, user_id=user_id, start_date=as_of - timedelta(days=365), end_date=as_of, as_of_date=as_of
    )
    package_cash = package_document_mod._cash_inputs_from_contributions(contributions).account_ids
    custody = await coverage_bank_custody_account_ids(db, user_id=user_id, as_of=as_of)
    assert bank.id in package_cash
    assert package_cash <= custody
    coverage = await report_coverage(db, user_id=user_id, as_of=as_of)
    assert (coverage.start, coverage.limiting_account_names) == (date(2026, 6, 5), ("DBS",))
    readiness = await current_package_readiness(db, user_id=user_id, as_of_date=as_of)
    assert [blocker.code for blocker in readiness.blockers] == []


async def _package_cash_and_custody(db: AsyncSession, user_id: UUID, as_of: date) -> tuple[frozenset, frozenset]:
    contributions = await package_document_mod.PackageAssembler()._contributions(
        db, user_id=user_id, start_date=as_of - timedelta(days=365), end_date=as_of, as_of_date=as_of
    )
    package_cash = package_document_mod._cash_inputs_from_contributions(contributions).account_ids
    return package_cash, await coverage_bank_custody_account_ids(db, user_id=user_id, as_of=as_of)


async def test_AC_reporting_2646_2_a_reparse_that_clears_the_summary_period_keeps_the_statement(
    db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-reporting.2646.2: a confirmed envelope, not approved, then a retry of the same source
    (``POST /statements/{id}/retry``). The source has no period, so the re-parse writes no period
    to the summary, but the result record and the envelope stay current and the package keeps the
    statement. The custody query reads the envelope period, so the custody set still holds the
    account and the readiness has no coverage blocker (the review probe of #2717)."""
    user_id = test_user.id
    _keep_the_statement_parsed(monkeypatch)
    bank = await _seed_first_bank_statement(db, user_id, monkeypatch)
    bank_id = bank.id  # expire_all below expires the fixture rows
    statement = (await db.execute(select(StatementSummary).where(StatementSummary.account_id == bank_id))).scalar_one()
    statement_id, file_hash, result_before = statement.id, statement.file_hash, statement.current_extraction_result_id
    as_of = date(2026, 6, 30)

    # POST /statements/{id}/retry: status parsing, commit, then the same parse job again.
    statement.status = BankStatementStatus.PARSING
    statement.validation_error = None
    await db.commit()
    await execute_statement_ingestion(
        ParseJob(
            statement_id=statement_id,
            filename="trusted-year-v0.csv",
            institution="DBS",
            user_id=user_id,
            account_id=bank_id,
            file_hash=file_hash,
            storage_key="trusted-year/v0.csv",
            model=None,
        ),
        content=_bank_csv(),
        session_maker=create_session_maker_from_db(db),
    )
    db.expire_all()
    reparsed = await db.get(StatementSummary, statement_id)
    assert reparsed is not None
    envelope = await current_reviewed_statement_envelope(db, user_id=user_id, statement_id=statement_id)
    # The preconditions of the probe: same result, no summary period, a current envelope period.
    assert (reparsed.current_extraction_result_id, reparsed.period_start) == (result_before, None)
    assert envelope is not None
    assert envelope.period_start == date(2026, 6, 5)

    package_cash, custody = await _package_cash_and_custody(db, user_id, as_of)
    assert bank_id in package_cash
    assert package_cash <= custody
    coverage = await report_coverage(db, user_id=user_id, as_of=as_of)
    assert (coverage.start, coverage.limiting_account_names) == (date(2026, 6, 5), ("DBS",))
    readiness = await current_package_readiness(db, user_id=user_id, as_of_date=as_of)
    assert "opening_coverage_starts_after_period" not in [blocker.code for blocker in readiness.blockers]


#: The guard message of the auto-approval fallback that the next test forces.
_GUARD_MESSAGE = "Custody account must be a non-system asset account"


async def test_AC_reporting_2646_2_an_auto_approval_that_falls_back_keeps_the_statement(
    db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-reporting.2646.2: a high-confidence source result with no envelope: the promotion decision
    of the parse is authoritative. The auto-approval guard fails, so the statement goes back to parsed with
    the guard message (not the lock-failure branch, which writes no message). The package keeps the
    statement as cash, and the custody set contains the package cash set."""
    user_id = test_user.id
    bank = await _account(db, user_id, "DBS")
    # A complete, balance-validated source result at 0.95 confidence: the parse decides
    # "extraction_promoted" (authoritative) and the statement is an auto-approval candidate.
    statement = StatementSummary(
        user_id=user_id,
        file_hash=sha256(b"coverage-auto-approval-fallback").hexdigest(),
        institution="DBS",
        account_id=bank.id,
        currency="SGD",
        period_start=date(2026, 6, 5),
        period_end=date(2026, 6, 15),
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("1100.00"),
        status=BankStatementStatus.APPROVED,
        confidence_score=99,
        balance_validated=True,
    )
    db.add(statement)
    await db.flush()
    source_result = StatementExtractionResult.create(
        producer_version="csv-parser@1",
        source_content_digest="c" * 64,
        source_type=StatementSourceType.BANK,
        evidence_type=StatementEvidenceType.TRANSACTION_LEDGER,
        institution="DBS",
        account_last4="7174",
        period_start=date(2026, 6, 5),
        period_end=date(2026, 6, 15),
        balances=(StatementBalanceFact(currency="SGD", opening=Decimal("1000.00"), closing=Decimal("1100.00")),),
        transactions=(
            ExtractedTransactionFact(
                fact_id="row-1",
                transaction_date=date(2026, 6, 10),
                description="Salary credit",
                amount=Decimal("100.00"),
                direction="IN",
                currency="SGD",
                balance_after=Decimal("1100.00"),
                confidence=Decimal("0.95"),
            ),
        ),
        positions=(),
        confidence=Decimal("0.95"),
        balance_validated=True,
        warnings=(),
        review_reasons=(),
        provenance=SourceProvenance(
            intake_mode="csv", method=ExtractionMethod.DETERMINISTIC, provider="csv-parser", model="csv-parser@1"
        ),
        statement_currency="SGD",
    )
    trace_records = build_extraction_trace_records(
        source_result,
        user_id=user_id,
        execution_id=f"test:{statement.id}:result:{source_result.result_id}",
        occurred_at=datetime.now(UTC),
    )
    await TraceEmitter(SqlTraceRecordRepository(db, extraction_trace_policy_registry())).emit_many(trace_records)
    await persist_statement_extraction_result(
        db, statement=statement, result=source_result, source_trace_record_id=trace_records[0].record_id
    )
    await initialize_opening_positions(
        db, user_id, entry_date=date(2026, 6, 5), balances={bank.id: Decimal("1000.00")}, currency="SGD"
    )
    await db.commit()

    async def guard_fails(*_args, **_kwargs):
        raise ValueError(_GUARD_MESSAGE)

    monkeypatch.setattr(statement_posting_mod, "approve_statement_with_transactions", guard_fails)
    created = await statement_posting_mod.try_auto_approve_high_confidence_statement(
        db, statement.id, user_id, dependencies=posting_dependencies()
    )
    await db.commit()
    await db.refresh(statement)
    assert (created, statement.status, statement.validation_error) == (0, BankStatementStatus.PARSED, _GUARD_MESSAGE)
    assert await current_reviewed_statement_envelope(db, user_id=user_id, statement_id=statement.id) is None
    contribution = await resolve_statement_contribution(db, user_id=user_id, statement_id=statement.id)
    assert contribution.state == "authoritative", contribution.reason_code
    assert contribution.decision is not None
    assert contribution.decision.target.kind == "statement_extraction_result"

    as_of = date(2026, 6, 30)
    package_cash, custody = await _package_cash_and_custody(db, user_id, as_of)
    assert bank.id in package_cash
    assert package_cash <= custody
    coverage = await report_coverage(db, user_id=user_id, as_of=as_of)
    assert (coverage.start, coverage.limiting_account_names) == (date(2026, 6, 5), ("DBS",))


async def test_AC_reporting_2646_2_two_cash_accounts_opened_on_the_bound_pass_the_check(
    db: AsyncSession, test_user
) -> None:
    """AC-reporting.2646.2: two cash accounts both open on 2026-06-05. A cash flow that starts on
    that day has no ``opening_coverage_starts_after_period``; one that starts a day earlier has it.
    The check and the bound read the same ``opening_coverage_start``."""
    user_id = test_user.id
    first = await _account(db, user_id, "DBS Savings")
    second = await _account(db, user_id, "OCBC Bank")
    await initialize_opening_positions(
        db,
        user_id,
        entry_date=date(2026, 6, 5),
        balances={first.id: Decimal("1000"), second.id: Decimal("500")},
        currency="SGD",
    )
    await db.commit()
    cash_ids = frozenset({first.id, second.id})

    coverage = await report_coverage(db, user_id=user_id, as_of=date(2026, 6, 30))
    assert (coverage.start, coverage.limiting_account_names) == (date(2026, 6, 5), ("DBS Savings", "OCBC Bank"))
    on_bound = await generate_cash_flow(
        db, user_id, start_date=date(2026, 6, 5), end_date=date(2026, 6, 30), currency="SGD", cash_account_ids=cash_ids
    )
    assert "opening_coverage_starts_after_period" not in on_bound["proof_reasons"]
    before_bound = await generate_cash_flow(
        db, user_id, start_date=date(2026, 6, 4), end_date=date(2026, 6, 30), currency="SGD", cash_account_ids=cash_ids
    )
    assert "opening_coverage_starts_after_period" in before_bound["proof_reasons"]


async def test_AC_reporting_2646_2_coverage_start_is_the_latest_cash_opening(
    db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-reporting.2646.2: the bound is the latest opening position of a cash account. A card
    statement that starts earlier and the statements and openings of another user do not move it.
    ``GET /reports/coverage`` serves the same date. The accounts here are cash by name;
    ``..._custody_accounts_are_the_bank_statements_of_the_user_in_any_status`` proves each predicate
    of the custody path with controls that have a current source result."""
    user_id = test_user.id
    periods = _record_readiness_periods(monkeypatch)

    # No cash opening position: no bound, the full 365 days.
    assert await report_coverage(db, user_id=user_id, as_of=AS_OF) == package_document_mod.CashCoverage(None, ())
    await current_package_readiness(db, user_id=user_id, as_of_date=AS_OF)
    assert periods[-1] == (AS_OF - timedelta(days=365), AS_OF)

    savings = await _account(db, user_id, "DBS Savings")
    second_bank = await _account(db, user_id, "OCBC Bank")
    card = await _account(db, user_id, "Visa card", AccountType.LIABILITY)
    await _open(db, user_id, savings, date(2026, 6, 5))
    await _open(db, user_id, second_bank, date(2026, 3, 1))
    await _open(db, user_id, card, date(2026, 5, 1), amount="-300")
    await _approved_statement(db, user_id, card, date(2026, 5, 1))
    db.add(
        StatementSummary(
            user_id=user_id,
            file_hash="b" * 64,
            institution="DBS",
            account_id=savings.id,
            currency="SGD",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            status=BankStatementStatus.PARSED,
        )
    )
    other = User(email="coverage-other@example.com", hashed_password="hashed")
    db.add(other)
    await db.flush()
    other_bank = await _account(db, other.id, "Other Bank")
    await _open(db, other.id, other_bank, date(2025, 12, 1))
    await _approved_statement(db, other.id, other_bank, date(2025, 12, 1))
    await db.commit()

    # The card is a liability, not a cash account: its May opening does not count. The latest cash
    # opening is the savings account on 2026-06-05.
    coverage = await report_coverage(db, user_id=user_id, as_of=AS_OF)
    assert (coverage.start, coverage.limiting_account_names) == (date(2026, 6, 5), ("DBS Savings",))
    await current_package_readiness(db, user_id=user_id, as_of_date=AS_OF)
    assert periods[-1] == (date(2026, 6, 5), AS_OF)
    # As of 2026-05-31 the savings opening is in the future: the bound is the OCBC opening.
    await current_package_readiness(db, user_id=user_id, as_of_date=date(2026, 5, 31))
    assert periods[-1] == (date(2026, 3, 1), date(2026, 5, 31))

    response = await reports_router.report_coverage(as_of_date=AS_OF, db=db, user_id=user_id)
    assert (response.as_of_date, response.coverage_start, response.limiting_accounts) == (
        AS_OF,
        date(2026, 6, 5),
        ["DBS Savings"],
    )


async def test_AC_reporting_2646_2_an_opening_balance_before_the_first_statement_keeps_its_history(
    db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-reporting.2646.2: a guided opening balance on 2026-01-01 and a first approved statement
    on 2026-06-05. The bound is 2026-01-01: the period keeps the history before the statement."""
    user_id = test_user.id
    periods = _record_readiness_periods(monkeypatch)
    savings = await _account(db, user_id, "DBS Savings")
    await _open(db, user_id, savings, date(2026, 1, 1))
    await _approved_statement(db, user_id, savings, date(2026, 6, 5))
    await db.commit()

    assert (await report_coverage(db, user_id=user_id, as_of=AS_OF)).start == date(2026, 1, 1)
    await current_package_readiness(db, user_id=user_id, as_of_date=AS_OF)
    assert periods[-1] == (date(2026, 1, 1), AS_OF)


@contextmanager
def _count_statements(db_engine) -> Iterator[list[str]]:
    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        statements.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _record)


#: The SQL budget of ``GET /reports/coverage``: the accounts, the bank custody accounts, and the
#: opening positions with their entries. It does not grow with the number of statements.
COVERAGE_QUERY_BUDGET = 6
YEAR_SCALE_STATEMENTS = 36


async def test_AC_reporting_2646_3_coverage_reads_a_fixed_number_of_queries_at_year_scale(
    db: AsyncSession, db_engine, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-reporting.2646.3: with 36 approved bank statements, ``GET /reports/coverage`` runs at most
    ``COVERAGE_QUERY_BUDGET`` SQL statements, and the bound adds at most that many to
    ``current_package_readiness``. Resolving each statement ran about 23 statements per statement."""
    user_id = test_user.id
    bank = await _seed_first_bank_statement(db, user_id, monkeypatch)
    bank_id = bank.id
    seeded = (await db.execute(select(StatementSummary).where(StatementSummary.account_id == bank_id))).scalar_one()
    template = await db.get(StatementExtractionResultRecord, seeded.current_extraction_result_id)
    assert template is not None
    for index in range(YEAR_SCALE_STATEMENTS - 1):
        period_start = date(2023, 6, 5) + timedelta(days=30 * index)
        summary = StatementSummary(
            user_id=user_id,
            file_hash=sha256(f"year-scale-{index}".encode()).hexdigest(),
            institution="DBS",
            account_id=bank_id,
            currency="SGD",
            period_start=period_start,
            period_end=period_start + timedelta(days=27),
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("1000.00"),
            status=BankStatementStatus.APPROVED,
        )
        db.add(summary)
        await db.flush()
        record = StatementExtractionResultRecord(
            user_id=user_id,
            statement_id=summary.id,
            content_digest=template.content_digest,
            source_content_digest=template.source_content_digest,
            schema_version=template.schema_version,
            producer_version=template.producer_version,
            payload=template.payload,
            source_trace_record_id=template.source_trace_record_id,
            created_at=template.created_at,
        )
        db.add(record)
        await db.flush()
        summary.current_extraction_result_id = record.id
    await db.commit()
    as_of = date(2026, 6, 30)

    with _count_statements(db_engine) as statements:
        response = await reports_router.report_coverage(as_of_date=as_of, db=db, user_id=user_id)
    assert response.coverage_start == date(2026, 6, 5)
    assert len(statements) <= COVERAGE_QUERY_BUDGET, statements

    # The first evaluation of a session fills caches: measure the warm evaluations only.
    await current_package_readiness(db, user_id=user_id, as_of_date=as_of)
    with _count_statements(db_engine) as bounded:
        await current_package_readiness(db, user_id=user_id, as_of_date=as_of)

    # The same evaluation with the bound handed in: the difference is the cost of the bound alone.
    known = await report_coverage(db, user_id=user_id, as_of=as_of)

    async def known_bound(db, *, user_id, as_of):  # noqa: ARG001
        return known

    monkeypatch.setattr(package_document_mod, "report_coverage", known_bound)
    with _count_statements(db_engine) as without_bound:
        await current_package_readiness(db, user_id=user_id, as_of_date=as_of)
    assert len(bounded) - len(without_bound) <= COVERAGE_QUERY_BUDGET, (len(bounded), len(without_bound))


async def test_AC_reporting_2726_1_coverage_exposes_latest_approved_statement_end(db: AsyncSession, test_user) -> None:
    """AC-reporting.2726.1: ``GET /reports/coverage`` exposes ``latest_statement_end`` as the latest
    approved statement period end on or before ``as_of_date``, ignoring parsed statements, statements
    ending after ``as_of_date``, and other users' statements."""
    user_id = test_user.id
    as_of = date(2026, 10, 27)
    assert (await reports_router.report_coverage(as_of_date=as_of, db=db, user_id=user_id)).latest_statement_end is None

    bank = await _account(db, user_id, "DBS Savings")
    await _open(db, user_id, bank, date(2025, 1, 1))
    await _approved_statement(db, user_id, bank, date(2025, 1, 1))
    await _approved_statement(db, user_id, bank, date(2025, 3, 1))
    # Unapproved statement and future statement do not move latest_statement_end.
    db.add(
        StatementSummary(
            user_id=user_id,
            file_hash="c" * 64,
            institution="DBS",
            account_id=bank.id,
            currency="SGD",
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
            status=BankStatementStatus.PARSED,
        )
    )
    await _approved_statement(db, user_id, bank, date(2026, 11, 1))
    other = User(email="latest-stmt-other@example.com", hashed_password="hashed")
    db.add(other)
    await db.flush()
    other_bank = await _account(db, other.id, "Other Bank")
    await _approved_statement(db, other.id, other_bank, date(2026, 9, 1))
    await db.commit()

    response = await reports_router.report_coverage(as_of_date=as_of, db=db, user_id=user_id)
    assert response.coverage_start == date(2025, 1, 1)
    assert response.latest_statement_end == date(2025, 3, 28)
    assert (await report_coverage(db, user_id=user_id, as_of=as_of)).latest_statement_end == date(2025, 3, 28)
