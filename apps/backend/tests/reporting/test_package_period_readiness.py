from datetime import date
from decimal import Decimal

import pytest

from src.audit.money import Money
from src.config import settings
from src.extraction import RuleType
from src.extraction.extension import transaction_classification
from src.extraction.extension.transaction_classification import CategoryProposal, TransactionCategory
from src.extraction.orm.layer3 import ClassificationRule
from src.ledger import AccountType, Entry, initialize_opening_positions, post_entry
from src.reporting import PackageAssembler
from src.request_context import RequestContext
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
from tests.reporting._report_fixtures import seed_accounts


@pytest.mark.parametrize("prior_date", [date(2026, 5, 1), date(2025, 12, 1)])
async def test_AC_reporting_package_document_11_prior_period_package_lifecycle(
    db, test_user, monkeypatch, prior_date
) -> None:
    monkeypatch.setattr(settings, "enable_ai_classification", True)
    cats = {"Salary credit": TransactionCategory.SALARY, "Rent debit": TransactionCategory.HOUSING}

    async def proposer(txns, _p):
        return [
            CategoryProposal(category=cats[i.description].value, confidence=99, reason="period-fixture") for i in txns
        ]

    monkeypatch.setattr(transaction_classification, "propose_categories", proposer)
    bank, securities, income, expense = await seed_accounts(
        db,
        test_user.id,
        ("DBS", AccountType.ASSET),
        ("Securities", AccountType.ASSET),
        ("Prior income", AccountType.INCOME),
        ("Prior expense", AccountType.EXPENSE),
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
    await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2025, 1, 1),
        balances={bank.id: Decimal("9930"), securities.id: Decimal("0")},
        currency="SGD",
        base_currency="SGD",
    )
    for debit, credit, amt in ((bank, income, "100"), (expense, bank, "30")):
        await post_entry(
            db,
            user_id=test_user.id,
            entry_date=prior_date,
            memo="Prior",
            entry=Entry.transfer(debit=debit.id, credit=credit.id, money=Money(Decimal(amt), "SGD")),
            base_currency="SGD",
        )
    await _ingest_reviewed_bank_statement(db, user_id=test_user.id, bank=bank, securities_id=securities.id)
    await db.commit()

    req = PersonalReportPackageGenerateRequest(
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 30),
        as_of_date=date(2026, 6, 30),
        currency="SGD",
    )
    snap = await generate_personal_report_package_snapshot(RequestContext(db, test_user.id), request=req)
    doc = snap.document
    assert (
        doc.sections.balance_sheet.net_income,
        doc.sections.income_statement.net_income,
        doc.sections.cash_flow.summary.beginning_cash,
        doc.sections.cash_flow.summary.ending_cash,
    ) == (Decimal("4070.00"), Decimal("4000.00"), Decimal("10000.00"), Decimal("13000.00"))
    assert (
        doc.readiness.state is PersonalReportPackageReadinessState.READY
        and snap.status is PersonalReportPackageSnapshotStatus.TRUSTED
    )
    frozen = doc.model_dump(mode="json")
    exported = {}
    for fmt in (PackageSnapshotExportFormat.JSON, PackageSnapshotExportFormat.CSV):
        body = await _stream_body(
            await export_personal_report_package_snapshot(snap.id, RequestContext(db, test_user.id), fmt)
        )
        exported[fmt] = body
        assert (
            ("4070.00" in body if fmt is PackageSnapshotExportFormat.JSON else True)
            and "14000.00" in body
            and "4000.00" in body
        )

    await post_entry(
        db,
        user_id=test_user.id,
        entry_date=date(2026, 7, 1),
        memo="Later",
        entry=Entry.transfer(debit=bank.id, credit=income.id, money=Money(Decimal("250"), "SGD")),
        base_currency="SGD",
    )
    await db.commit()
    assert (await get_personal_report_package_snapshot(snap.id, RequestContext(db, test_user.id))).document.model_dump(
        mode="json"
    ) == frozen
    for fmt, orig in exported.items():
        assert (
            await _stream_body(
                await export_personal_report_package_snapshot(snap.id, RequestContext(db, test_user.id), fmt)
            )
            == orig
        )

    real_sections = PackageAssembler._sections
    for sec_name in ("balance_sheet", "income_statement"):

        async def bad_sections(self, *args, _sn=sec_name, **kwargs):
            secs = await real_sections(self, *args, **kwargs)
            getattr(secs, _sn).net_income += Decimal("1.00")
            return secs

        monkeypatch.setattr(PackageAssembler, "_sections", bad_sections)
        invalid = await generate_personal_report_package_snapshot(RequestContext(db, test_user.id), request=req)
        assert invalid.status is PersonalReportPackageSnapshotStatus.DRAFT and "statement_net_income_mismatch" in {
            b.code for b in invalid.document.readiness.blockers
        }
