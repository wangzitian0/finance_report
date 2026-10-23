"""The workflow readiness period starts no earlier than the first approved statement (#2646).

Before #2646 the readiness of the current package always covered the 365 days before today. A
user whose first statement starts inside that window has no opening balance at its start, so the
cash-flow coverage check blocked the package and Home showed "A blocker holds your reports".
"""

from __future__ import annotations

from datetime import date
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
from src.ledger import Account, AccountType, initialize_opening_positions
from src.reporting import current_package_readiness
from src.schemas.reporting import PersonalReportPackageReadinessState
from tests.integration.test_trusted_year_scenario import _ingest_reviewed_bank_statement

AS_OF = date(2026, 10, 22)
FIRST_STATEMENT = date(2026, 7, 1)


async def _statement(
    db: AsyncSession, user_id: UUID, account: Account, period_start: date, status: BankStatementStatus
) -> None:
    db.add(
        StatementSummary(
            user_id=user_id,
            file_hash=sha256(f"{user_id}:{period_start}:{status.value}".encode()).hexdigest(),
            institution="DBS",
            account_id=account.id,
            currency="SGD",
            period_start=period_start,
            period_end=date(period_start.year, period_start.month, 28),
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("1200.00"),
            status=status,
        )
    )
    await db.flush()


async def _bank(db: AsyncSession, user_id: UUID) -> Account:
    bank = Account(user_id=user_id, name="DBS", type=AccountType.ASSET, currency="SGD")
    db.add(bank)
    await db.flush()
    return bank


async def test_AC_reporting_2646_1_readiness_period_starts_at_the_first_approved_statement(
    db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-reporting.2646.1: the readiness period of ``current_package_readiness`` starts on the
    first day of the earliest approved statement when that day is inside the 365-day window. An
    unapproved statement and the statement of another user do not move it."""
    periods: list[tuple[date, date]] = []
    real_evaluate = package_document_mod.PackageAssembler.evaluate_readiness

    async def recording_evaluate(self, db, **kwargs):
        periods.append((kwargs["start_date"], kwargs["end_date"]))
        return await real_evaluate(self, db, **kwargs)

    monkeypatch.setattr(package_document_mod.PackageAssembler, "evaluate_readiness", recording_evaluate)

    # No approved statement: the 365 days before the date.
    await current_package_readiness(db, user_id=test_user.id, as_of_date=AS_OF)
    assert periods[-1] == (date(2025, 10, 22), AS_OF)

    bank = await _bank(db, test_user.id)
    await _statement(db, test_user.id, bank, date(2026, 1, 1), BankStatementStatus.PARSED)
    await _statement(db, test_user.id, bank, date(2026, 8, 1), BankStatementStatus.APPROVED)
    await _statement(db, test_user.id, bank, FIRST_STATEMENT, BankStatementStatus.APPROVED)
    await current_package_readiness(db, user_id=test_user.id, as_of_date=AS_OF)
    assert periods[-1] == (FIRST_STATEMENT, AS_OF)

    # A first statement after the date does not move the start.
    await current_package_readiness(db, user_id=test_user.id, as_of_date=date(2026, 6, 30))
    assert periods[-1] == (date(2025, 6, 30), date(2026, 6, 30))


async def test_AC_reporting_2646_1_first_statement_opening_has_no_coverage_blocker(
    db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-reporting.2646.1: a new user approves one bank statement (2026-06-05 to 2026-06-15). The
    ledger starts with its opening balances on 2026-06-05. The current readiness on 2026-06-30 has
    no ``opening_coverage_starts_after_period`` blocker: before #2646 its period started on 2025-06-30."""
    monkeypatch.setattr(settings, "enable_ai_classification", True)

    async def proposer(transactions, _policy):
        categories = {"Salary credit": TransactionCategory.SALARY, "Rent debit": TransactionCategory.HOUSING}
        return [
            CategoryProposal(
                category=categories[item.description].value, confidence=99, reason="first-statement-fixture"
            )
            for item in transactions
        ]

    monkeypatch.setattr(transaction_classification, "propose_categories", proposer)
    bank = await _bank(db, test_user.id)
    securities = Account(user_id=test_user.id, name="Securities", type=AccountType.ASSET, currency="SGD")
    db.add(securities)
    await db.flush()
    # The ledger starts with the opening balances of the first statement, on its first day.
    await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2026, 6, 5),
        balances={bank.id: TRUSTED_YEAR_SCENARIO.opening_cash, securities.id: Decimal("0")},
        currency="SGD",
    )
    db.add(
        ClassificationRule(
            user_id=test_user.id,
            created_by=test_user.id,
            version_number=1,
            effective_date=date(2026, 1, 1),
            rule_name="Reviewed investment",
            rule_type=RuleType.KEYWORD_MATCH,
            rule_config={"keywords": ["Buy security"]},
            tag_mappings={"intent": "transfer"},
            default_account_id=securities.id,
        )
    )
    await _ingest_reviewed_bank_statement(db, user_id=test_user.id, bank=bank, securities_id=securities.id)
    await db.commit()

    readiness = await current_package_readiness(db, user_id=test_user.id, as_of_date=date(2026, 6, 30))

    codes = [blocker.code for blocker in readiness.blockers]
    # Before #2646 the only blocker was ``opening_coverage_starts_after_period``.
    assert codes == [], codes
    assert readiness.state is PersonalReportPackageReadinessState.READY
