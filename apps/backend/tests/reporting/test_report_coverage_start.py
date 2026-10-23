"""The default report period starts no earlier than the cash coverage start (#2646).

Before #2646 the readiness of the current package always covered the 365 days before today. A user
whose cash accounts have their opening positions inside that window failed the cash-flow coverage
check (``opening_coverage_starts_after_period``), and Home showed "A blocker holds your reports".
The bound is the quantity that the check reads: the latest opening position of a cash account.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

import pytest
from common.testing.trusted_year import TRUSTED_YEAR_SCENARIO
from sqlalchemy.ext.asyncio import AsyncSession

import src.reporting.extension.package_document as package_document_mod
from src.config import settings
from src.extraction import BankStatementStatus, RuleType, StatementSummary
from src.extraction.extension import transaction_classification
from src.extraction.extension.transaction_classification import CategoryProposal, TransactionCategory
from src.extraction.orm.layer3 import ClassificationRule
from src.identity import User
from src.ledger import Account, AccountType, initialize_opening_positions
from src.reporting import current_package_readiness, report_coverage_start
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


async def test_AC_reporting_2646_1_first_statement_opening_has_no_coverage_blocker(
    db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-reporting.2646.1: a new user approves one bank statement (2026-06-05 to 2026-06-15). The
    ledger starts with its opening balances on 2026-06-05. A card statement from May is approved too.
    The current readiness on 2026-06-30 has no blocker: before #2646 its period started on
    2025-06-30, and a bound by the first approved statement (the May card statement) kept the
    ``opening_coverage_starts_after_period`` blocker."""
    user_id = test_user.id
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

    readiness = await current_package_readiness(db, user_id=user_id, as_of_date=date(2026, 6, 30))

    codes = [blocker.code for blocker in readiness.blockers]
    assert "opening_coverage_starts_after_period" not in codes, codes
    assert await report_coverage_start(db, user_id=user_id, as_of=date(2026, 6, 30)) == date(2026, 6, 5)


async def test_AC_reporting_2646_2_coverage_start_is_the_latest_cash_opening(
    db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-reporting.2646.2: the bound is the latest opening position of a cash account. A card
    statement that starts earlier, an unapproved bank statement, and the statements and openings of
    another user do not move it. ``GET /reports/coverage`` serves the same date."""
    user_id = test_user.id
    periods = _record_readiness_periods(monkeypatch)

    # No cash opening position: no bound, the full 365 days.
    assert await report_coverage_start(db, user_id=user_id, as_of=AS_OF) is None
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
    assert await report_coverage_start(db, user_id=user_id, as_of=AS_OF) == date(2026, 6, 5)
    await current_package_readiness(db, user_id=user_id, as_of_date=AS_OF)
    assert periods[-1] == (date(2026, 6, 5), AS_OF)
    # As of 2026-05-31 the savings opening is in the future: the bound is the OCBC opening.
    await current_package_readiness(db, user_id=user_id, as_of_date=date(2026, 5, 31))
    assert periods[-1] == (date(2026, 3, 1), date(2026, 5, 31))

    response = await reports_router.report_coverage(as_of_date=AS_OF, db=db, user_id=user_id)
    assert (response.as_of_date, response.coverage_start) == (AS_OF, date(2026, 6, 5))


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

    assert await report_coverage_start(db, user_id=user_id, as_of=AS_OF) == date(2026, 1, 1)
    await current_package_readiness(db, user_id=user_id, as_of_date=AS_OF)
    assert periods[-1] == (date(2026, 1, 1), AS_OF)
