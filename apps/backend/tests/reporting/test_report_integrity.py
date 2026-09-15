"""Business regressions from the generated PDF-to-package audit (EPIC-020)."""

from datetime import date
from decimal import Decimal

import pytest

from src.audit import Money
from src.ledger import Account, AccountType, Entry, post_entry, post_opening_balance_entry
from src.ledger.extension.account_service import update_account
from src.ledger.extension.processing import get_or_create_processing_account
from src.reporting import generate_balance_sheet, generate_cash_flow, generate_income_statement
from src.reporting.base.types import PersonalReportingFrameworkId
from src.reporting.extension.framework_report import (
    assemble_framework_balance_sheet,
    assemble_framework_income_statement,
)
from src.schemas.account import AccountUpdate

START = date(2026, 1, 1)
END = date(2026, 1, 31)


async def _account(db, user_id, name, kind, currency="SGD"):
    account = Account(user_id=user_id, name=name, type=kind, currency=currency)
    db.add(account)
    await db.flush()
    return account


async def _post(db, user_id, debit, credit, amount, *, category=None, on=date(2026, 1, 10), fx_rate=None):
    return await post_entry(
        db,
        user_id=user_id,
        entry_date=on,
        memo="Generated report integrity activity",
        entry=Entry.transfer(
            debit=debit.id,
            credit=credit.id,
            money=Money(Decimal(amount), debit.currency),
            fx_rate=fx_rate,
            tags={"economic_category": category} if category is not None else None,
        ),
    )


@pytest.mark.parametrize("framework", list(PersonalReportingFrameworkId))
async def test_processing_survives_framework_reporting(db, test_user, framework):
    """AC-reporting.report-integrity.1: in-transit money survives every transfer state."""
    bank = await _account(db, test_user.id, "Generated custody", AccountType.ASSET)
    destination = await _account(db, test_user.id, "Generated destination", AccountType.ASSET)
    await post_opening_balance_entry(
        db, test_user.id, entry_date=date(2025, 12, 31), balances={bank.id: Decimal("100")}, currency="SGD"
    )
    processing = await get_or_create_processing_account(db, test_user.id, currency="SGD")
    for step, expected in enumerate((Decimal("0"), Decimal("30"), Decimal("0"))):
        if expected:
            await _post(db, test_user.id, processing, bank, "30")
        elif step == 2:
            await _post(db, test_user.id, destination, processing, "30")
        report = await assemble_framework_balance_sheet(
            db, test_user.id, framework_id=framework, as_of_date=END, currency="SGD"
        )
        transit = next(line for line in report["assets"] if line["line_id"] == "assets.cash_in_transit")
        assert transit["amount"] == expected
        assert report["total_assets"] == Decimal("100")
        assert report["is_balanced"]
        cash = await generate_cash_flow(
            db,
            test_user.id,
            start_date=START,
            end_date=END,
            currency="SGD",
            cash_account_ids=frozenset((bank.id, destination.id)),
        )
        assert cash["cash_bridge"]["classified_activity"] == 0
        assert cash["cash_bridge"]["unclassified_cash"] == 0
        assert cash["summary"]["ending_cash"] == Decimal("100")


@pytest.mark.parametrize("framework", list(PersonalReportingFrameworkId))
async def test_posted_categories_survive_framework_mapping(db, test_user, framework):
    """AC-reporting.report-integrity.4: category belongs to each posted fact, not its account."""
    bank = await _account(db, test_user.id, "Generated custody", AccountType.ASSET)
    income = await _account(db, test_user.id, "All receipts", AccountType.INCOME)
    expense = await _account(db, test_user.id, "All payments", AccountType.EXPENSE)
    for debit, credit, amount, category in (
        (bank, income, "500", "SALARY"),
        (bank, income, "10", "INTEREST"),
        (expense, bank, "100", "HOUSING"),
        (expense, bank, "5", "FEES"),
        (expense, bank, "3", "OTHER_EXPENSE"),
    ):
        await _post(db, test_user.id, debit, credit, amount, category=category)
    result = await assemble_framework_income_statement(
        db, test_user.id, framework_id=framework, start_date=START, end_date=END, currency="SGD"
    )
    amounts = {line["line_id"]: line["amount"] for line in (*result["income"], *result["expenses"])}
    assert amounts["income.salary"] == Decimal("500")
    assert amounts["income.dividends_and_interest"] == Decimal("10")
    assert amounts["expenses.housing"] == Decimal("100")
    assert amounts["expenses.fees"] == Decimal("5")
    assert amounts["expenses.other"] == Decimal("3")
    assert amounts["expenses.investment_fees"] == 0
    assert result["total_income"] == Decimal("510")
    assert result["total_expenses"] == Decimal("108")
    # User account labels cannot rewrite accepted, frozen economic categories.
    await update_account(db, test_user.id, income.id, AccountUpdate(name="Interest"))
    again = await assemble_framework_income_statement(
        db, test_user.id, framework_id=framework, start_date=START, end_date=END, currency="SGD"
    )
    assert again["income"] == result["income"]


async def test_uncategorized_history_is_not_investment_activity(db, test_user):
    """AC-reporting.report-integrity.5: broad types and names confer no investment meaning."""
    bank = await _account(db, test_user.id, "Generated custody", AccountType.ASSET)
    income = await _account(db, test_user.id, "Interest", AccountType.INCOME)
    expense = await _account(db, test_user.id, "Investment fees", AccountType.EXPENSE)
    await _post(db, test_user.id, bank, income, "50")
    await _post(db, test_user.id, expense, bank, "10", category="UNKNOWN_FUTURE_CATEGORY")
    result = await assemble_framework_income_statement(
        db,
        test_user.id,
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        start_date=START,
        end_date=END,
        currency="SGD",
    )
    amounts = {line["line_id"]: line["amount"] for line in (*result["income"], *result["expenses"])}
    assert amounts["income.other"] == Decimal("50")
    assert amounts["expenses.other"] == Decimal("10")
    assert amounts["income.dividends_and_interest"] == 0
    assert amounts["expenses.investment_fees"] == 0


async def test_archiving_preserves_historical_reports(db, test_user):
    """AC-reporting.report-integrity.6: archival changes availability, not financial history."""
    bank = await _account(db, test_user.id, "Generated custody", AccountType.ASSET)
    liability = await _account(db, test_user.id, "Generated liability", AccountType.LIABILITY)
    income = await _account(db, test_user.id, "Generated income", AccountType.INCOME)
    expense = await _account(db, test_user.id, "Generated expense", AccountType.EXPENSE)
    await post_opening_balance_entry(
        db,
        test_user.id,
        entry_date=date(2025, 12, 31),
        balances={bank.id: Decimal("100"), liability.id: Decimal("40")},
        currency="SGD",
    )
    await _post(db, test_user.id, bank, income, "20", category="SALARY")
    await _post(db, test_user.id, expense, bank, "5", category="HOUSING")

    async def reports():
        return (
            await generate_balance_sheet(db, test_user.id, as_of_date=END, currency="SGD"),
            await generate_income_statement(db, test_user.id, start_date=START, end_date=END, currency="SGD"),
            await generate_cash_flow(
                db, test_user.id, start_date=START, end_date=END, currency="SGD", cash_account_ids=frozenset((bank.id,))
            ),
            await assemble_framework_balance_sheet(
                db, test_user.id, framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE, as_of_date=END, currency="SGD"
            ),
        )

    before = await reports()
    for account in (bank, liability, income, expense):
        await update_account(db, test_user.id, account.id, AccountUpdate(is_active=False))
    after = await reports()
    assert after == before


async def test_persisted_package_integrity(db, test_user, monkeypatch):
    """AC-reporting.report-integrity.7: persisted inputs survive package freeze and export."""
    from src.config import settings
    from src.extraction import RuleType
    from src.extraction.extension import transaction_classification
    from src.extraction.extension.transaction_classification import CategoryProposal
    from src.extraction.orm.layer3 import ClassificationRule
    from src.ledger.extension.processing import find_transfer_pairs
    from src.reconciliation import score_description
    from src.routers.reports import (
        PackageSnapshotExportFormat,
        export_personal_report_package_snapshot,
        generate_personal_report_package_snapshot,
        get_personal_report_package_snapshot,
    )
    from src.schemas.reporting import PersonalReportPackageGenerateRequest, PersonalReportPackageSnapshotStatus
    from tests.integration.test_trusted_year_scenario import _ingest_reviewed_bank_statement, _stream_body

    monkeypatch.setattr(settings, "enable_ai_classification", True)

    async def proposer(transactions, _policy):
        categories = {"Salary credit": "SALARY", "Rent debit": "HOUSING"}
        return [
            CategoryProposal(category=categories[item.description], confidence=99, reason="generated")
            for item in transactions
        ]

    async def no_market_refresh(*_args, **_kwargs):
        pass

    monkeypatch.setattr(transaction_classification, "propose_categories", proposer)
    monkeypatch.setattr("src.routers.reports._ensure_report_market_data_fresh", no_market_refresh)
    bank = await _account(db, test_user.id, "DBS", AccountType.ASSET)
    securities = await _account(db, test_user.id, "Generated securities", AccountType.ASSET)
    db.add(
        ClassificationRule(
            user_id=test_user.id,
            created_by=test_user.id,
            version_number=1,
            effective_date=START,
            rule_name="Generated investment",
            rule_type=RuleType.KEYWORD_MATCH,
            rule_config={"keywords": ["Buy security"]},
            tag_mappings={"intent": "transfer"},
            default_account_id=securities.id,
        )
    )
    await post_opening_balance_entry(
        db,
        test_user.id,
        entry_date=date(2025, 12, 31),
        balances={bank.id: Decimal("10000"), securities.id: Decimal("0")},
        currency="SGD",
    )
    await _ingest_reviewed_bank_statement(db, user_id=test_user.id, bank=bank, securities_id=securities.id)
    await find_transfer_pairs(db, test_user.id, currency="SGD", description_scorer=score_description)
    await db.commit()
    request = PersonalReportPackageGenerateRequest(
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 30),
        as_of_date=date(2026, 6, 30),
        currency="SGD",
    )
    snapshot = await generate_personal_report_package_snapshot(db, user_id=test_user.id, request=request)
    assert snapshot.status is PersonalReportPackageSnapshotStatus.TRUSTED, snapshot.document.readiness.model_dump(
        mode="json"
    )
    sections = snapshot.document.sections
    assert sections.balance_sheet.total_assets == Decimal("14000")
    assert sections.income_statement.net_income == Decimal("4000")
    assert sections.cash_flow.summary.beginning_cash == Decimal("10000")
    assert sections.cash_flow.summary.ending_cash == Decimal("13000")
    assert any(line.line_id == "assets.cash_in_transit" for line in sections.balance_sheet.assets)
    frozen = snapshot.document.model_dump(mode="json")
    exports = {}
    for format in (PackageSnapshotExportFormat.JSON, PackageSnapshotExportFormat.CSV):
        exports[format] = await _stream_body(
            await export_personal_report_package_snapshot(snapshot.id, db, test_user.id, format)
        )
    await update_account(db, test_user.id, bank.id, AccountUpdate(is_active=False))
    await db.commit()
    reopened = await get_personal_report_package_snapshot(snapshot.id, db, test_user.id)
    assert reopened.document.model_dump(mode="json") == frozen
    for format, content in exports.items():
        assert (
            await _stream_body(await export_personal_report_package_snapshot(snapshot.id, db, test_user.id, format))
            == content
        )


async def test_category_rounding_preserves_account_total(db, test_user):
    """AC-reporting.report-integrity.4: category splits cannot create an FX rounding penny."""
    from src.pricing.orm.market_data import FxRate

    bank = await _account(db, test_user.id, "Generated USD custody", AccountType.ASSET, "USD")
    income = await _account(db, test_user.id, "Mixed USD income", AccountType.INCOME, "USD")
    db.add(FxRate(base_currency="USD", quote_currency="SGD", rate_date=START, rate=Decimal("1.5"), source="generated"))
    await db.flush()
    for category in ("SALARY", "INTEREST", "OTHER_INCOME"):
        await _post(db, test_user.id, bank, income, "0.01", category=category, fx_rate=Decimal("1.5"))
    raw = await generate_income_statement(db, test_user.id, start_date=START, end_date=END, currency="SGD")
    grouped = await assemble_framework_income_statement(
        db,
        test_user.id,
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        start_date=START,
        end_date=END,
        currency="SGD",
    )
    assert grouped["total_income"] == raw["total_income"]
    assert sum(line["amount"] for line in grouped["income"]) == raw["total_income"]


async def test_archived_foreign_and_portfolio_accounts_keep_valuation(db, test_user):
    """AC-reporting.report-integrity.6: FX gain and security basis survive account archival."""
    from src.extraction.orm.layer3 import CostBasisMethod, ManagedPosition, PositionStatus
    from src.ledger import calculate_unrealized_fx_gains
    from src.pricing.orm.market_data import FxRate, StockPrice
    from src.reporting.extension.portfolio_market import _portfolio_market_basis_by_account

    bank = await _account(db, test_user.id, "Generated USD custody", AccountType.ASSET, "USD")
    equity = await _account(db, test_user.id, "Generated USD equity", AccountType.EQUITY, "USD")
    broker = await _account(db, test_user.id, "Generated broker", AccountType.ASSET)
    db.add_all(
        [
            FxRate(base_currency="USD", quote_currency="SGD", rate_date=START, rate=Decimal("1.2"), source="generated"),
            FxRate(base_currency="USD", quote_currency="SGD", rate_date=END, rate=Decimal("1.3"), source="generated"),
            StockPrice(symbol="AUDIT", price=Decimal("12"), currency="SGD", price_date=END, source="generated"),
            ManagedPosition(
                user_id=test_user.id,
                account_id=broker.id,
                asset_identifier="AUDIT",
                quantity=Decimal("10"),
                cost_basis=Decimal("100"),
                currency="SGD",
                acquisition_date=START,
                status=PositionStatus.ACTIVE,
                cost_basis_method=CostBasisMethod.FIFO,
            ),
        ]
    )
    await db.flush()
    await _post(db, test_user.id, bank, equity, "100", fx_rate=Decimal("1.2"))
    before_fx = await calculate_unrealized_fx_gains(db, test_user.id, END)
    before_basis = await _portfolio_market_basis_by_account(db, test_user.id, as_of_date=END, target_currency="SGD")
    assert before_fx.total_unrealized_gain_loss == Decimal("10")
    assert before_basis[broker.id]["market_value"] == Decimal("120")
    for account in (bank, broker):
        await update_account(db, test_user.id, account.id, AccountUpdate(is_active=False))
    after_fx = await calculate_unrealized_fx_gains(db, test_user.id, END)
    after_basis = await _portfolio_market_basis_by_account(db, test_user.id, as_of_date=END, target_currency="SGD")
    assert after_fx == before_fx
    assert after_basis == before_basis


@pytest.mark.parametrize("opening", [Decimal("0"), Decimal("100")])
@pytest.mark.parametrize("currency", ["SGD", "USD"])
async def test_opening_stock_is_beginning_cash(db, test_user, opening, currency):
    """AC-reporting.report-integrity.2: starting stock is not newly earned cash."""
    from src.pricing.orm.market_data import FxRate

    bank = await _account(db, test_user.id, "Generated custody", AccountType.ASSET, currency)
    income = await _account(db, test_user.id, "Generated salary", AccountType.INCOME, currency)
    rate = Decimal("1") if currency == "SGD" else Decimal("1.25")
    if currency == "USD":
        db.add(FxRate(base_currency="USD", quote_currency="SGD", rate_date=START, rate=rate, source="generated"))
        await db.flush()
    await post_opening_balance_entry(
        db,
        test_user.id,
        entry_date=START,
        balances={bank.id: opening},
        currency=currency,
        base_currency="SGD",
        fx_rates={currency: rate},
    )
    await _post(db, test_user.id, bank, income, "20", category="SALARY", fx_rate=rate)
    report = await generate_cash_flow(
        db, test_user.id, start_date=START, end_date=END, currency="SGD", cash_account_ids=frozenset((bank.id,))
    )
    assert report["proof_state"] == "proven", report["proof_reasons"]
    assert report["summary"]["beginning_cash"] == opening * rate
    assert report["summary"]["ending_cash"] == (opening + Decimal("20")) * rate
    assert report["summary"]["net_cash_flow"] == Decimal("20") * rate
    assert report["cash_bridge"]["unclassified_cash"] == 0
    assert report["cash_bridge"]["opening_stock_adjustment"] == 0


async def test_midperiod_opening_is_explicit_incomplete_coverage(db, test_user):
    """AC-reporting.report-integrity.3: an observed opening cannot establish earlier coverage."""
    bank = await _account(db, test_user.id, "Generated custody", AccountType.ASSET)
    income = await _account(db, test_user.id, "Generated salary", AccountType.INCOME)
    await post_opening_balance_entry(
        db, test_user.id, entry_date=date(2026, 1, 5), balances={bank.id: Decimal("100")}, currency="SGD"
    )
    await _post(db, test_user.id, bank, income, "20", category="SALARY")
    report = await generate_cash_flow(
        db, test_user.id, start_date=START, end_date=END, currency="SGD", cash_account_ids=frozenset((bank.id,))
    )
    assert report["proof_state"] == "unproven"
    assert "opening_coverage_starts_after_period" in report["proof_reasons"]
    assert report["cash_bridge"]["opening_stock_adjustment"] == Decimal("100")
    assert report["cash_bridge"]["unclassified_cash"] == 0
    assert report["cash_bridge"]["cash_delta"] == Decimal("120")
    assert report["summary"]["net_cash_flow"] == Decimal("20")
    assert report["cash_bridge"]["reconciles"]


async def test_opening_like_manual_text_is_not_starting_stock(db, test_user):
    """AC-reporting.report-integrity.3: arbitrary labels confer no opening authority."""
    from src.ledger import Direction
    from src.ledger.base.types.entry import Leg

    bank = await _account(db, test_user.id, "Generated custody", AccountType.ASSET)
    equity = await _account(db, test_user.id, "Opening Balance Equity", AccountType.EQUITY)
    await post_entry(
        db,
        user_id=test_user.id,
        entry_date=START,
        memo="Opening balance",
        entry=Entry.of(
            Leg(bank.id, Direction.DEBIT, Money(Decimal("100"), "SGD"), event_type="opening_balance"),
            Leg(equity.id, Direction.CREDIT, Money(Decimal("100"), "SGD"), event_type="opening_balance"),
        ),
    )
    report = await generate_cash_flow(
        db, test_user.id, start_date=START, end_date=END, currency="SGD", cash_account_ids=frozenset((bank.id,))
    )
    assert report["proof_state"] == "unproven"
    assert report["summary"]["beginning_cash"] == 0
    assert report["cash_bridge"]["unclassified_cash"] == Decimal("100")


async def test_opening_fx_movement_stays_separate(db, test_user):
    """AC-reporting.report-integrity.2: translated opening stock and FX changes do not become receipts."""
    from src.pricing.orm.market_data import FxRate

    bank = await _account(db, test_user.id, "Generated USD custody", AccountType.ASSET, "USD")
    income = await _account(db, test_user.id, "Generated USD salary", AccountType.INCOME, "USD")
    for on, rate in ((START, "1.25"), (END, "1.30")):
        db.add(FxRate(base_currency="USD", quote_currency="SGD", rate_date=on, rate=Decimal(rate), source="generated"))
    await db.flush()
    await post_opening_balance_entry(
        db,
        test_user.id,
        entry_date=START,
        balances={bank.id: Decimal("100")},
        currency="USD",
        base_currency="SGD",
        fx_rates={"USD": Decimal("1.25")},
    )
    await _post(db, test_user.id, bank, income, "20", category="SALARY", on=START, fx_rate=Decimal("1.25"))
    report = await generate_cash_flow(
        db, test_user.id, start_date=START, end_date=END, currency="SGD", cash_account_ids=frozenset((bank.id,))
    )
    assert report["proof_state"] == "proven"
    assert report["summary"]["beginning_cash"] == Decimal("125")
    assert report["summary"]["ending_cash"] == Decimal("156")
    assert report["summary"]["operating_activities"] == Decimal("25")
    assert report["cash_bridge"]["fx_effect"] == Decimal("6")
    assert report["cash_bridge"]["opening_stock_adjustment"] == 0
    assert report["cash_bridge"]["reconciles"]


async def test_zero_opening_decision_reaches_package_manifest(db, test_user):
    """AC-reporting.report-integrity.7: a journal-free opening remains in the authority manifest."""
    from src.ledger import list_opening_positions
    from src.reporting.extension.package_document import PackageAssembler

    bank = await _account(db, test_user.id, "Generated empty custody", AccountType.ASSET)
    entry = await post_opening_balance_entry(
        db, test_user.id, entry_date=START, balances={bank.id: Decimal("0")}, currency="SGD"
    )
    assert entry is None
    positions = await list_opening_positions(db, user_id=test_user.id, as_of=END)
    assert len(positions) == 1 and positions[0].decision is not None
    document = await PackageAssembler().assemble(
        db,
        user_id=test_user.id,
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        start_date=START,
        end_date=END,
        as_of_date=END,
        currency="SGD",
    )
    matching = [item for item in document.input_manifest if f"opening_position:{bank.id}" in item.input_refs]
    assert len(matching) == 1
    assert matching[0].decision_id == positions[0].decision.decision_id


async def test_stale_opening_blocks_cash_flow_proof(db, test_user):
    """AC-reporting.report-integrity.3: a revoked opening cannot authorize report starting cash."""
    from datetime import UTC, datetime

    from src.audit import TraceEmitter, TraceRecord, TraceResult, TraceScope, TraceTargetClass, VersionedTraceRef
    from src.audit.extension.trace_repository import SqlTraceRecordRepository
    from src.ledger import ledger_trace_policy_registry
    from src.ledger.extension.anchored_posting import SystemJournalCommandPolicy

    bank = await _account(db, test_user.id, "Generated custody", AccountType.ASSET)
    entry = await post_opening_balance_entry(
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
    report = await generate_cash_flow(
        db, test_user.id, start_date=START, end_date=END, currency="SGD", cash_account_ids=frozenset((bank.id,))
    )
    assert report["proof_state"] == "unproven"
    assert "opening_position_unproven" in report["proof_reasons"]
    assert report["summary"]["beginning_cash"] == 0


async def test_cash_flow_csv_discloses_opening_adjustment(db, test_user, monkeypatch):
    """AC-reporting.report-integrity.3: exported arithmetic preserves the same coverage warning."""
    import csv
    from io import StringIO

    from src.routers.reports import ExportFormat, ExportReportType, export_report
    from tests.integration.test_trusted_year_scenario import _stream_body

    async def no_market_refresh(*_args, **_kwargs):
        pass

    monkeypatch.setattr("src.routers.reports._ensure_report_market_data_fresh", no_market_refresh)
    bank = await _account(db, test_user.id, "Generated bank", AccountType.ASSET)
    income = await _account(db, test_user.id, "Generated salary", AccountType.INCOME)
    await post_opening_balance_entry(
        db, test_user.id, entry_date=date(2026, 1, 5), balances={bank.id: Decimal("100")}, currency="SGD"
    )
    await _post(db, test_user.id, bank, income, "20", category="SALARY")
    content = await _stream_body(
        await export_report(
            report_type=ExportReportType.CASH_FLOW,
            format=ExportFormat.CSV,
            start_date=START,
            end_date=END,
            currency="SGD",
            db=db,
            user_id=test_user.id,
        )
    )
    rows = {row[0]: row for row in csv.reader(StringIO(content))}
    assert rows["Known Beginning Cash"][2] == "0.00"
    assert rows["Opening balance adjustment"][2] == "100.00"
    assert rows["Net Cash Flow"][2] == "20.00"
    assert rows["Ending Cash"][2] == "120.00"
    assert "unproven" in rows["Verification"][4]
    assert "opening_coverage_starts_after_period" in rows["Verification"][4]
