"""The default report period starts no earlier than the cash coverage start (#2646).

Before #2646 the readiness of the current package always covered the 365 days before today. A user
whose cash accounts have their opening positions inside that window failed the cash-flow coverage
check (``opening_coverage_starts_after_period``), and Home showed "A blocker holds your reports".
The bound is the quantity that the check reads: the latest opening position of a cash account.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

import pytest
from common.testing.trusted_year import TRUSTED_YEAR_SCENARIO
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

import src.reporting.extension.package_document as package_document_mod
from src.config import settings
from src.extraction import BankStatementStatus, RuleType, StatementSummary
from src.extraction.extension import transaction_classification
from src.extraction.extension.transaction_classification import CategoryProposal, TransactionCategory
from src.extraction.orm.layer3 import ClassificationRule
from src.extraction.orm.reviewed_statement_envelope import StatementExtractionResultRecord
from src.identity import User
from src.ledger import Account, AccountType, initialize_opening_positions
from src.reporting import current_package_readiness, generate_cash_flow, report_coverage
from src.routers import reports as reports_router
from tests.integration.test_trusted_year_scenario import _ingest_reviewed_bank_statement

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
    statement that starts earlier, an unapproved bank statement, and the statements and openings of
    another user do not move it. ``GET /reports/coverage`` serves the same date."""
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
