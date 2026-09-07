"""Normal repeated-period package assembly, freeze, and export regression (#2009)."""

from datetime import date
from decimal import Decimal

import pytest

from src.audit.money import Money
from src.config import settings
from src.extraction.extension import transaction_classification
from src.extraction.extension.transaction_classification import CategoryProposal, TransactionCategory
from src.extraction.orm.layer3 import ClassificationRule, RuleType
from src.ledger import Account, AccountType, Entry, post_entry, post_opening_balance_entry
from src.reporting import PackageAssembler
from src.routers.reports import (
    PackageSnapshotExportFormat,
    export_personal_report_package_snapshot,
    generate_personal_report_package_snapshot,
    get_personal_report_package_snapshot,
)
from src.schemas.reporting import (
    PersonalReportingFrameworkId,
    PersonalReportPackageGenerateRequest,
    PersonalReportPackageReadinessState,
    PersonalReportPackageSnapshotStatus,
)
from tests.integration.test_trusted_year_scenario import _ingest_reviewed_bank_statement, _stream_body


@pytest.mark.parametrize("prior_date", [date(2026, 5, 1), date(2025, 12, 1)])
async def test_AC_reporting_package_document_11_prior_period_package_lifecycle(
    db, test_user, monkeypatch, prior_date
) -> None:
    """AC-reporting.package-document.11: monthly/year-boundary income retains its own period."""
    monkeypatch.setattr(settings, "enable_ai_classification", True)

    async def proposer(transactions, _policy):
        categories = {"Salary credit": TransactionCategory.SALARY, "Rent debit": TransactionCategory.HOUSING}
        return [
            CategoryProposal(category=categories[item.description].value, confidence=99, reason="period-fixture")
            for item in transactions
        ]

    monkeypatch.setattr(transaction_classification, "propose_categories", proposer)
    bank = Account(user_id=test_user.id, name="DBS", type=AccountType.ASSET, currency="SGD")
    securities = Account(user_id=test_user.id, name="Securities", type=AccountType.ASSET, currency="SGD")
    income = Account(user_id=test_user.id, name="Prior income", type=AccountType.INCOME, currency="SGD")
    expense = Account(user_id=test_user.id, name="Prior expense", type=AccountType.EXPENSE, currency="SGD")
    db.add_all((bank, securities, income, expense))
    await db.flush()
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
    await post_opening_balance_entry(
        db, test_user.id, entry_date=date(2025, 1, 1), balances={bank.id: Decimal("9930")}, currency="SGD"
    )
    for debit, credit, amount in ((bank, income, "100"), (expense, bank, "30")):
        await post_entry(
            db,
            user_id=test_user.id,
            entry_date=prior_date,
            memo="Generated prior-period activity",
            entry=Entry.transfer(debit=debit.id, credit=credit.id, money=Money(Decimal(amount), "SGD")),
        )
    await _ingest_reviewed_bank_statement(db, user_id=test_user.id, bank=bank, securities_id=securities.id)
    await db.commit()

    async def no_market_refresh(*_args, **_kwargs):
        pass

    monkeypatch.setattr("src.routers.reports._ensure_report_market_data_fresh", no_market_refresh)
    request = PersonalReportPackageGenerateRequest(
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 30),
        as_of_date=date(2026, 6, 30),
        currency="SGD",
    )
    snapshot = await generate_personal_report_package_snapshot(db, user_id=test_user.id, request=request)
    document = snapshot.document
    assert document.sections.balance_sheet.net_income == Decimal("4070.00")
    assert document.sections.income_statement.net_income == Decimal("4000.00")
    assert document.sections.cash_flow.summary.beginning_cash == Decimal("10000.00")
    assert document.sections.cash_flow.summary.ending_cash == Decimal("13000.00")
    assert document.readiness.state is PersonalReportPackageReadinessState.READY, document.readiness.blockers
    assert snapshot.status is PersonalReportPackageSnapshotStatus.TRUSTED
    frozen = document.model_dump(mode="json")
    exported = {}
    for format in (PackageSnapshotExportFormat.JSON, PackageSnapshotExportFormat.CSV):
        response = await export_personal_report_package_snapshot(snapshot.id, db, test_user.id, format)
        exported[format] = await _stream_body(response)
        if format is PackageSnapshotExportFormat.JSON:
            assert "4070.00" in exported[format]
        assert "14000.00" in exported[format]
        assert "4000.00" in exported[format]

    await post_entry(
        db,
        user_id=test_user.id,
        entry_date=date(2026, 7, 1),
        memo="Later live income",
        entry=Entry.transfer(debit=bank.id, credit=income.id, money=Money(Decimal("250"), "SGD")),
    )
    await db.commit()
    reopened = await get_personal_report_package_snapshot(snapshot.id, db, test_user.id)
    assert reopened.document.model_dump(mode="json") == frozen
    for format, original in exported.items():
        response = await export_personal_report_package_snapshot(snapshot.id, db, test_user.id, format)
        assert await _stream_body(response) == original

    real_sections = PackageAssembler._sections
    for section_name in ("balance_sheet", "income_statement"):

        async def inconsistent_sections(self, *args, **kwargs):
            sections = await real_sections(self, *args, **kwargs)
            section = getattr(sections, section_name)
            section.net_income += Decimal("1.00")
            return sections

        monkeypatch.setattr(PackageAssembler, "_sections", inconsistent_sections)
        invalid = await generate_personal_report_package_snapshot(db, user_id=test_user.id, request=request)
        assert invalid.status is PersonalReportPackageSnapshotStatus.DRAFT
        assert "statement_net_income_mismatch" in {blocker.code for blocker in invalid.document.readiness.blockers}
