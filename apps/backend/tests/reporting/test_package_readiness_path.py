from datetime import date
from decimal import Decimal

import pytest

import src.reporting.extension.package_document as package_document_mod
from src.audit.money import Money
from src.ledger import AccountType, Entry, initialize_opening_positions, post_entry
from src.reporting import PackageAssembler
from src.schemas.reporting import PersonalReportingFrameworkId, PersonalReportPackageReadinessState
from tests.reporting._report_fixtures import seed_accounts, seed_ready_package_state

PERIOD = {
    "framework_id": PersonalReportingFrameworkId.US_GAAP_LIKE,
    "start_date": date(2026, 6, 1),
    "end_date": date(2026, 6, 30),
    "as_of_date": date(2026, 6, 30),
    "currency": "SGD",
}


async def _seed_draft(db, user_id, monkeypatch) -> None:
    pass


async def _seed_blocked(db, user_id, monkeypatch) -> None:
    bank, _sec, inc = await seed_accounts(
        db, user_id, ("DBS", AccountType.ASSET), ("Securities", AccountType.ASSET), ("Salary", AccountType.INCOME)
    )
    await initialize_opening_positions(
        db,
        user_id,
        entry_date=date(2025, 1, 1),
        balances={bank.id: Decimal("10000"), _sec.id: Decimal("0")},
        currency="SGD",
        base_currency="SGD",
    )
    await post_entry(
        db,
        user_id=user_id,
        entry_date=date(2026, 6, 10),
        memo="Salary without a statement",
        entry=Entry.transfer(debit=bank.id, credit=inc.id, money=Money(Decimal("100"), "SGD")),
        base_currency="SGD",
    )
    await db.commit()


SEEDS = {
    "draft": (_seed_draft, PersonalReportPackageReadinessState.DRAFT, []),
    "blocked": (
        _seed_blocked,
        PersonalReportPackageReadinessState.BLOCKED,
        [("cash_balance_input_missing", 1), ("cash_identity_missing", 1)],
    ),
    "ready": (seed_ready_package_state, PersonalReportPackageReadinessState.READY, []),
}


@pytest.mark.parametrize("fixture", sorted(SEEDS))
async def test_AC_reporting_package_document_14_readiness_path_equals_full_assembly(
    db, test_user, monkeypatch, fixture
) -> None:
    seed, expected_state, expected_blockers = SEEDS[fixture]
    await seed(db, test_user.id, monkeypatch)
    real_traceability = package_document_mod.build_personal_report_package_traceability_payload
    trace_calls = 0

    async def counting_trace(**kwargs):
        nonlocal trace_calls
        trace_calls += 1
        return await real_traceability(**kwargs)

    monkeypatch.setattr(package_document_mod, "build_personal_report_package_traceability_payload", counting_trace)
    readiness = await PackageAssembler().evaluate_readiness(db, user_id=test_user.id, **PERIOD)
    assert trace_calls == 0
    doc = await PackageAssembler().assemble(db, user_id=test_user.id, **PERIOD)
    assert trace_calls == 1 and readiness.state is expected_state
    assert sorted((b.code, b.count) for b in readiness.blockers) == expected_blockers
    assert readiness.model_dump(mode="json") == doc.readiness.model_dump(mode="json")
