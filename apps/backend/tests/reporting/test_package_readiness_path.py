"""The readiness-only package path returns the readiness of the full assembly (#2583)."""

from datetime import date
from decimal import Decimal

import pytest

import src.reporting.extension.package_document as package_document_mod
from src.audit.money import Money
from src.config import settings
from src.extraction import RuleType
from src.extraction.extension import transaction_classification
from src.extraction.extension.transaction_classification import CategoryProposal, TransactionCategory
from src.extraction.orm.layer3 import ClassificationRule
from src.ledger import Account, AccountType, Entry, initialize_opening_positions, post_entry
from src.reporting import PackageAssembler
from src.schemas.reporting import PersonalReportingFrameworkId, PersonalReportPackageReadinessState
from tests.integration.test_trusted_year_scenario import _ingest_reviewed_bank_statement

PERIOD = {
    "framework_id": PersonalReportingFrameworkId.US_GAAP_LIKE,
    "start_date": date(2026, 6, 1),
    "end_date": date(2026, 6, 30),
    "as_of_date": date(2026, 6, 30),
    "currency": "SGD",
}


async def _seed_draft(db, user_id, monkeypatch) -> None:
    """No package input: the package is a draft."""


async def _ledger_accounts(db, user_id) -> tuple[Account, Account, Account]:
    bank = Account(user_id=user_id, name="DBS", type=AccountType.ASSET, currency="SGD")
    securities = Account(user_id=user_id, name="Securities", type=AccountType.ASSET, currency="SGD")
    income = Account(user_id=user_id, name="Salary", type=AccountType.INCOME, currency="SGD")
    db.add_all((bank, securities, income))
    await db.flush()
    await initialize_opening_positions(
        db,
        user_id,
        entry_date=date(2025, 1, 1),
        balances={bank.id: Decimal("10000"), securities.id: Decimal("0")},
        currency="SGD",
    )
    return bank, securities, income


async def _seed_blocked(db, user_id, monkeypatch) -> None:
    """Ledger activity without a bank statement: the cash balance has no source input."""
    bank, _securities, income = await _ledger_accounts(db, user_id)
    await post_entry(
        db,
        user_id=user_id,
        entry_date=date(2026, 6, 10),
        memo="Salary without a statement",
        entry=Entry.transfer(debit=bank.id, credit=income.id, money=Money(Decimal("100"), "SGD")),
    )
    await db.commit()


async def _seed_ready(db, user_id, monkeypatch) -> None:
    """A reviewed bank statement covers every cash movement: the package is ready."""
    monkeypatch.setattr(settings, "enable_ai_classification", True)

    async def proposer(transactions, _policy):
        categories = {"Salary credit": TransactionCategory.SALARY, "Rent debit": TransactionCategory.HOUSING}
        return [
            CategoryProposal(category=categories[item.description].value, confidence=99, reason="readiness-fixture")
            for item in transactions
        ]

    monkeypatch.setattr(transaction_classification, "propose_categories", proposer)
    bank, securities, _income = await _ledger_accounts(db, user_id)
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


# fixture -> (seed, expected state, expected blocker codes with counts)
SEEDS = {
    "draft": (_seed_draft, PersonalReportPackageReadinessState.DRAFT, []),
    "blocked": (
        _seed_blocked,
        PersonalReportPackageReadinessState.BLOCKED,
        [("cash_balance_input_missing", 1), ("cash_identity_missing", 1)],
    ),
    "ready": (_seed_ready, PersonalReportPackageReadinessState.READY, []),
}


@pytest.mark.parametrize("fixture", sorted(SEEDS))
async def test_AC_reporting_package_document_14_readiness_path_equals_full_assembly(
    db, test_user, monkeypatch, fixture
) -> None:
    """AC-reporting.package-document.14: evaluate_readiness returns assemble(...).readiness without the appendix."""
    seed, expected_state, expected_blockers = SEEDS[fixture]
    await seed(db, test_user.id, monkeypatch)

    real_traceability = package_document_mod.build_personal_report_package_traceability_payload
    traceability_calls = 0

    async def counting_traceability(**kwargs):
        nonlocal traceability_calls
        traceability_calls += 1
        return await real_traceability(**kwargs)

    monkeypatch.setattr(
        package_document_mod, "build_personal_report_package_traceability_payload", counting_traceability
    )

    readiness = await PackageAssembler().evaluate_readiness(db, user_id=test_user.id, **PERIOD)
    assert traceability_calls == 0

    document = await PackageAssembler().assemble(db, user_id=test_user.id, **PERIOD)
    assert traceability_calls == 1

    # The expected state and blockers pin each readiness rule that the fixture exercises. A
    # mutation of a rule changes the result of at least one fixture, although both paths share it.
    assert readiness.state is expected_state, readiness.blockers
    assert sorted((blocker.code, blocker.count) for blocker in readiness.blockers) == expected_blockers
    assert readiness.model_dump(mode="json") == document.readiness.model_dump(mode="json")
