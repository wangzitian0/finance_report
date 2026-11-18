from datetime import date
from decimal import Decimal

import pytest

from src.audit import Money
from src.ledger import AccountType, Direction, Entry, initialize_opening_positions, post_entry
from src.ledger.base.types.entry import Leg
from src.ledger.extension.account_service import update_account
from src.ledger.extension.processing import find_transfer_pairs, get_or_create_processing_account
from src.pricing.orm.market_data import FxRate
from src.reconciliation import score_description
from src.reporting import (
    generate_balance_sheet,
    generate_cash_flow,
    generate_income_statement,
    render_cash_flow_csv,
    render_income_statement_csv,
)
from src.reporting.base.types import PersonalReportingFrameworkId
from src.reporting.extension.framework_report import (
    assemble_framework_balance_sheet,
    assemble_framework_income_statement,
)
from src.request_context import RequestContext
from src.routers.reports import (
    ExportFormat,
    ExportReportType,
    PackageSnapshotExportFormat,
    export_personal_report_package_snapshot,
    export_report,
    generate_personal_report_package_snapshot,
    get_personal_report_package_snapshot,
)
from src.schemas import IncomeStatementResponse
from src.schemas.account import AccountUpdate
from src.schemas.reporting import PersonalReportPackageGenerateRequest, PersonalReportPackageSnapshotStatus
from tests.integration.test_trusted_year_scenario import _stream_body
from tests.reporting._report_fixtures import seed_accounts, seed_ready_package_state

START = date(2026, 1, 1)
END = date(2026, 1, 31)


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
            tags={"economic_category": category} if category else None,
        ),
        base_currency="SGD",
    )


@pytest.mark.parametrize("framework", list(PersonalReportingFrameworkId))
async def test_processing_and_categories_survive_framework_reporting(db, test_user, framework) -> None:
    bank, dest, income, expense = await seed_accounts(
        db,
        test_user.id,
        ("Generated custody", AccountType.ASSET),
        ("Generated dest", AccountType.ASSET),
        ("All receipts", AccountType.INCOME),
        ("All payments", AccountType.EXPENSE),
    )
    await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2025, 12, 31),
        balances={bank.id: Decimal("100")},
        currency="SGD",
        base_currency="SGD",
    )
    proc = await get_or_create_processing_account(db, test_user.id, currency="SGD")
    for step, exp in enumerate((Decimal("0"), Decimal("30"), Decimal("0"))):
        if exp:
            await _post(db, test_user.id, proc, bank, "30")
        elif step == 2:
            await _post(db, test_user.id, dest, proc, "30")
        rep = await assemble_framework_balance_sheet(
            db, test_user.id, framework_id=framework, as_of_date=END, currency="SGD", base_currency="SGD"
        )
        assert (
            next(line["amount"] for line in rep["assets"] if line["line_id"] == "assets.cash_in_transit"),
            rep["total_assets"],
            rep["is_balanced"],
        ) == (exp, Decimal("100"), True)
        cf = await generate_cash_flow(
            db,
            test_user.id,
            start_date=START,
            end_date=END,
            currency="SGD",
            cash_account_ids=frozenset((bank.id, dest.id)),
        )
        assert (
            cf["cash_bridge"]["classified_activity"],
            cf["cash_bridge"]["unclassified_cash"],
            cf["summary"]["ending_cash"],
        ) == (0, 0, Decimal("100"))

    for d, c, amt, cat in (
        (bank, income, "500", "SALARY"),
        (bank, income, "10", "INTEREST"),
        (expense, bank, "100", "HOUSING"),
        (expense, bank, "5", "FEES"),
        (expense, bank, "3", "OTHER_EXPENSE"),
    ):
        await _post(db, test_user.id, d, c, amt, category=cat)
    res = await assemble_framework_income_statement(
        db, test_user.id, framework_id=framework, start_date=START, end_date=END, currency="SGD", base_currency="SGD"
    )
    amts = {line["line_id"]: line["amount"] for line in (*res["income"], *res["expenses"])}
    assert (
        amts["income.salary"],
        amts["income.dividends_and_interest"],
        amts["expenses.housing"],
        amts["expenses.fees"],
        amts["expenses.other"],
        amts["expenses.investment_fees"],
        res["total_income"],
        res["total_expenses"],
    ) == (Decimal("500"), Decimal("10"), Decimal("100"), Decimal("5"), Decimal("3"), 0, Decimal("510"), Decimal("108"))
    await update_account(db, test_user.id, income.id, AccountUpdate(name="Interest"))
    assert (
        await assemble_framework_income_statement(
            db,
            test_user.id,
            framework_id=framework,
            start_date=START,
            end_date=END,
            currency="SGD",
            base_currency="SGD",
        )
    )["income"] == res["income"]


async def test_uncategorized_history_archiving_and_category_rounding(db, test_user) -> None:
    bank, liab, income, expense, usd_bank, usd_inc = await seed_accounts(
        db,
        test_user.id,
        ("Custody", AccountType.ASSET),
        ("Liab", AccountType.LIABILITY),
        ("Interest", AccountType.INCOME),
        ("Inv fees", AccountType.EXPENSE),
        ("USD custody", AccountType.ASSET, "USD"),
        ("Mixed USD", AccountType.INCOME, "USD"),
    )
    await _post(db, test_user.id, bank, income, "50")
    await _post(db, test_user.id, expense, bank, "10", category="UNKNOWN_FUTURE_CATEGORY")
    uncat = await assemble_framework_income_statement(
        db,
        test_user.id,
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        start_date=START,
        end_date=END,
        currency="SGD",
        base_currency="SGD",
    )
    amts = {line["line_id"]: line["amount"] for line in (*uncat["income"], *uncat["expenses"])}
    assert (
        amts["income.other"],
        amts["expenses.other"],
        amts["income.dividends_and_interest"],
        amts["expenses.investment_fees"],
    ) == (Decimal("50"), Decimal("10"), 0, 0)

    db.add(FxRate(base_currency="USD", quote_currency="SGD", rate_date=START, rate=Decimal("1.5"), source="generated"))
    await db.flush()
    for cat in ("SALARY", "INTEREST", "OTHER_INCOME"):
        await _post(db, test_user.id, usd_bank, usd_inc, "0.01", category=cat, fx_rate=Decimal("1.5"))
    raw = await generate_income_statement(db, test_user.id, start_date=START, end_date=END, currency="SGD")
    grouped = await assemble_framework_income_statement(
        db,
        test_user.id,
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        start_date=START,
        end_date=END,
        currency="SGD",
        base_currency="SGD",
    )
    assert (
        grouped["total_income"] == raw["total_income"]
        and sum(line["amount"] for line in grouped["income"]) == raw["total_income"]
    )

    await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2025, 12, 31),
        balances={bank.id: Decimal("100"), liab.id: Decimal("40")},
        currency="SGD",
        base_currency="SGD",
    )
    await _post(db, test_user.id, bank, income, "20", category="SALARY")
    await _post(db, test_user.id, expense, bank, "5", category="HOUSING")

    async def snap():
        return (
            await generate_balance_sheet(db, test_user.id, as_of_date=END, currency="SGD"),
            await generate_income_statement(db, test_user.id, start_date=START, end_date=END, currency="SGD"),
            await generate_cash_flow(
                db, test_user.id, start_date=START, end_date=END, currency="SGD", cash_account_ids=frozenset((bank.id,))
            ),
            await assemble_framework_balance_sheet(
                db,
                test_user.id,
                framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
                as_of_date=END,
                currency="SGD",
                base_currency="SGD",
            ),
        )

    before = await snap()
    for acc in (bank, liab, income, expense):
        await update_account(db, test_user.id, acc.id, AccountUpdate(is_active=False))
    assert await snap() == before


async def test_persisted_package_integrity(db, test_user, monkeypatch) -> None:
    bank, _, _ = await seed_ready_package_state(db, test_user.id, monkeypatch, opening_date=date(2025, 12, 31))
    await find_transfer_pairs(db, test_user.id, currency="SGD", description_scorer=score_description)
    await db.commit()
    snapshot = await generate_personal_report_package_snapshot(
        RequestContext(db, test_user.id),
        request=PersonalReportPackageGenerateRequest(
            framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 30),
            as_of_date=date(2026, 6, 30),
            currency="SGD",
        ),
    )
    assert snapshot.status is PersonalReportPackageSnapshotStatus.TRUSTED
    sec = snapshot.document.sections
    assert (
        sec.balance_sheet.total_assets,
        sec.income_statement.net_income,
        sec.cash_flow.summary.beginning_cash,
        sec.cash_flow.summary.ending_cash,
    ) == (Decimal("14000"), Decimal("4000"), Decimal("10000"), Decimal("13000"))
    assert any(line.line_id == "assets.cash_in_transit" for line in sec.balance_sheet.assets)
    frozen = snapshot.document.model_dump(mode="json")
    exports = {
        fmt: await _stream_body(
            await export_personal_report_package_snapshot(snapshot.id, RequestContext(db, test_user.id), fmt)
        )
        for fmt in (PackageSnapshotExportFormat.JSON, PackageSnapshotExportFormat.CSV)
    }
    await update_account(db, test_user.id, bank.id, AccountUpdate(is_active=False))
    await db.commit()
    assert (
        await get_personal_report_package_snapshot(snapshot.id, RequestContext(db, test_user.id))
    ).document.model_dump(mode="json") == frozen
    for fmt, content in exports.items():
        assert (
            await _stream_body(
                await export_personal_report_package_snapshot(snapshot.id, RequestContext(db, test_user.id), fmt)
            )
            == content
        )


async def test_archived_foreign_and_portfolio_accounts_keep_valuation(db, test_user) -> None:
    from src.portfolio.orm.portfolio import CostBasisMethod, ManagedPosition, PositionStatus
    from src.ledger import calculate_unrealized_fx_gains
    from src.pricing.orm.market_data import StockPrice
    from src.reporting.extension.portfolio_market import _portfolio_market_basis_by_account

    bank, equity, broker = await seed_accounts(
        db,
        test_user.id,
        ("USD custody", AccountType.ASSET, "USD"),
        ("USD equity", AccountType.EQUITY, "USD"),
        ("Broker", AccountType.ASSET),
    )
    db.add_all(
        [
            FxRate(base_currency="USD", quote_currency="SGD", rate_date=START, rate=Decimal("1.2"), source="gen"),
            FxRate(base_currency="USD", quote_currency="SGD", rate_date=END, rate=Decimal("1.3"), source="gen"),
            StockPrice(symbol="AUDIT", price=Decimal("12"), currency="SGD", price_date=END, source="gen"),
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
    before = (
        await calculate_unrealized_fx_gains(db, test_user.id, END, base_currency="SGD"),
        await _portfolio_market_basis_by_account(db, test_user.id, as_of_date=END, target_currency="SGD"),
    )
    assert (before[0].total_unrealized_gain_loss, before[1][broker.id]["market_value"]) == (
        Decimal("10"),
        Decimal("120"),
    )
    for acc in (bank, broker):
        await update_account(db, test_user.id, acc.id, AccountUpdate(is_active=False))
    assert (
        await calculate_unrealized_fx_gains(db, test_user.id, END, base_currency="SGD"),
        await _portfolio_market_basis_by_account(db, test_user.id, as_of_date=END, target_currency="SGD"),
    ) == before


@pytest.mark.parametrize("opening", [Decimal("0"), Decimal("100")])
@pytest.mark.parametrize("currency", ["SGD", "USD"])
async def test_opening_stock_is_beginning_cash(db, test_user, opening, currency) -> None:
    bank, income = await seed_accounts(
        db, test_user.id, ("Custody", AccountType.ASSET, currency), ("Salary", AccountType.INCOME, currency)
    )
    rate = Decimal("1") if currency == "SGD" else Decimal("1.25")
    if currency == "USD":
        db.add(FxRate(base_currency="USD", quote_currency="SGD", rate_date=START, rate=rate, source="gen"))
        await db.flush()
    await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=START,
        balances={bank.id: opening},
        currency=currency,
        base_currency="SGD",
        fx_rates={currency: rate},
    )
    await _post(db, test_user.id, bank, income, "20", category="SALARY", fx_rate=rate)
    rep = await generate_cash_flow(
        db, test_user.id, start_date=START, end_date=END, currency="SGD", cash_account_ids=frozenset((bank.id,))
    )
    assert (
        rep["proof_state"],
        rep["summary"]["beginning_cash"],
        rep["summary"]["ending_cash"],
        rep["summary"]["net_cash_flow"],
        rep["cash_bridge"]["unclassified_cash"],
        rep["cash_bridge"]["opening_stock_adjustment"],
    ) == ("proven", opening * rate, (opening + Decimal("20")) * rate, Decimal("20") * rate, 0, 0)


async def test_opening_cash_flow_edge_cases_and_csv_disclosure(db, test_user) -> None:
    import csv
    from io import StringIO
    from src.ledger import list_opening_positions
    from src.reporting.extension.package_document import PackageAssembler

    bank, income, equity, usd_bank, usd_inc, empty_bank, mid_bank, mid_inc = await seed_accounts(
        db,
        test_user.id,
        ("Custody", AccountType.ASSET),
        ("Salary", AccountType.INCOME),
        ("Opening Eq", AccountType.EQUITY),
        ("USD custody", AccountType.ASSET, "USD"),
        ("USD sal", AccountType.INCOME, "USD"),
        ("Empty", AccountType.ASSET),
        ("Mid bank", AccountType.ASSET),
        ("Mid sal", AccountType.INCOME),
    )
    await post_entry(
        db,
        user_id=test_user.id,
        entry_date=START,
        memo="Opening balance",
        entry=Entry.of(
            Leg(bank.id, Direction.DEBIT, Money(Decimal("100"), "SGD"), event_type="opening_balance"),
            Leg(equity.id, Direction.CREDIT, Money(Decimal("100"), "SGD"), event_type="opening_balance"),
        ),
        base_currency="SGD",
    )
    unclass = await generate_cash_flow(
        db, test_user.id, start_date=START, end_date=END, currency="SGD", cash_account_ids=frozenset((bank.id,))
    )
    assert (
        unclass["proof_state"],
        unclass["summary"]["beginning_cash"],
        unclass["cash_bridge"]["unclassified_cash"],
    ) == ("unproven", 0, Decimal("100"))

    [
        db.add(FxRate(base_currency="USD", quote_currency="SGD", rate_date=on, rate=Decimal(r), source="gen"))
        for on, r in ((START, "1.25"), (END, "1.30"))
    ]
    await db.flush()
    await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=START,
        balances={usd_bank.id: Decimal("100")},
        currency="USD",
        base_currency="SGD",
        fx_rates={"USD": Decimal("1.25")},
    )
    await _post(db, test_user.id, usd_bank, usd_inc, "20", category="SALARY", on=START, fx_rate=Decimal("1.25"))
    fx_rep = await generate_cash_flow(
        db, test_user.id, start_date=START, end_date=END, currency="SGD", cash_account_ids=frozenset((usd_bank.id,))
    )
    assert (
        fx_rep["proof_state"],
        fx_rep["summary"]["beginning_cash"],
        fx_rep["summary"]["ending_cash"],
        fx_rep["summary"]["operating_activities"],
        fx_rep["cash_bridge"]["fx_effect"],
        fx_rep["cash_bridge"]["reconciles"],
    ) == ("proven", Decimal("125"), Decimal("156"), Decimal("25"), Decimal("6"), True)

    assert (
        await initialize_opening_positions(
            db,
            test_user.id,
            entry_date=START,
            balances={empty_bank.id: Decimal("0")},
            currency="SGD",
            base_currency="SGD",
        )
        is None
    )
    pos = await list_opening_positions(db, user_id=test_user.id, as_of=END)
    doc = await PackageAssembler().assemble(
        db,
        user_id=test_user.id,
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        start_date=START,
        end_date=END,
        as_of_date=END,
        currency="SGD",
    )
    assert any(
        f"opening_position:{empty_bank.id}" in i.input_refs
        and i.decision_id == next(p.decision.decision_id for p in pos if p.account_id == empty_bank.id)
        for i in doc.input_manifest
    )

    await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2026, 1, 5),
        balances={mid_bank.id: Decimal("100")},
        currency="SGD",
        base_currency="SGD",
    )
    await _post(db, test_user.id, mid_bank, mid_inc, "20", category="SALARY")
    mid_rep = await generate_cash_flow(
        db, test_user.id, start_date=START, end_date=END, currency="SGD", cash_account_ids=frozenset((mid_bank.id,))
    )
    assert (
        mid_rep["proof_state"],
        mid_rep["cash_bridge"]["opening_stock_adjustment"],
        mid_rep["cash_bridge"]["cash_delta"],
        mid_rep["summary"]["net_cash_flow"],
        mid_rep["cash_bridge"]["reconciles"],
    ) == ("unproven", Decimal("100"), Decimal("120"), Decimal("20"), True)
    assert "opening_coverage_starts_after_period" in mid_rep["proof_reasons"]

    content = await _stream_body(
        await export_report(
            report_type=ExportReportType.CASH_FLOW,
            format=ExportFormat.CSV,
            start_date=START,
            end_date=END,
            currency="SGD",
            ctx=RequestContext(db, test_user.id),
        )
    )
    rows = {r[0]: r for r in csv.reader(StringIO(content))}
    assert (rows["Known Beginning Cash"][2], rows["Opening balance adjustment"][2], rows["Net Cash Flow"][2]) == (
        "0.00",
        "100.00",
        "20.00",
    )
    assert "unproven" in rows["Verification"][4] and "opening_coverage_starts_after_period" in rows["Verification"][4]
    assert "Opening balance adjustment" in render_cash_flow_csv(
        {
            "currency": "SGD",
            "operating": [{"subcategory": "Salary", "amount": Decimal("20.00"), "description": "Pay"}],
            "investing": [],
            "financing": [],
            "summary": {
                "operating_activities": Decimal("20.00"),
                "investing_activities": Decimal("0.00"),
                "financing_activities": Decimal("0.00"),
                "net_cash_flow": Decimal("20.00"),
                "beginning_cash": Decimal("0.00"),
                "ending_cash": Decimal("120.00"),
            },
            "proof_state": "unproven",
            "proof_reasons": ["opening_coverage_starts_after_period"],
            "cash_bridge": {"opening_stock_adjustment": Decimal("100.00")},
        }
    )
    is_dict = {
        "currency": "SGD",
        "income": [{"name": "Salary", "amount": Decimal("20.00")}],
        "expenses": [],
        "total_income": Decimal("20.00"),
        "total_expenses": Decimal("0.00"),
        "net_income": Decimal("20.00"),
    }
    is_model = IncomeStatementResponse(
        start_date=START,
        end_date=END,
        currency="SGD",
        income=[{"account_id": mid_bank.id, "name": "Salary", "type": "INCOME", "amount": Decimal("20.00")}],
        expenses=[],
        total_income=Decimal("20.00"),
        total_expenses=Decimal("0.00"),
        net_income=Decimal("20.00"),
        savings_rate=Decimal("100.00"),
        trends=[],
    )
    assert render_income_statement_csv(is_dict) == render_income_statement_csv(is_model)


async def test_stale_opening_blocks_cash_flow_proof(db, test_user) -> None:
    from datetime import UTC, datetime
    from src.audit import TraceEmitter, TraceRecord, TraceResult, TraceScope, TraceTargetClass, VersionedTraceRef
    from src.audit.extension.trace_repository import SqlTraceRecordRepository
    from src.ledger import ledger_trace_policy_registry
    from src.ledger.extension.anchored_posting import SystemJournalCommandPolicy

    [bank] = await seed_accounts(db, test_user.id, ("Custody", AccountType.ASSET))
    entry = await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2026, 1, 1),
        balances={bank.id: Decimal("100")},
        currency="SGD",
        base_currency="SGD",
    )
    repo, scope, policy, now = (
        SqlTraceRecordRepository(db, ledger_trace_policy_registry()),
        TraceScope.tenant(test_user.id),
        SystemJournalCommandPolicy(),
        datetime.now(UTC),
    )
    prev = await repo.get(scope, entry.decision_anchor_id)
    obs = TraceRecord.observation(
        scope=scope,
        target=prev.target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef("ledger_system_input", "opening-balance", "1"),
        authority=policy.authority,
        result=TraceResult.FAIL,
        execution_id="synthetic-revoked-opening",
        evidence_manifest_digest=prev.target.version,
        occurred_at=now,
        reason_code="synthetic_authority_revoked",
        score=None,
    )
    await TraceEmitter(repo).emit_many(
        (
            obs,
            TraceRecord.decision(
                scope=scope,
                target=prev.target,
                policy=policy,
                execution_id=obs.execution_id,
                occurred_at=now,
                parents=(obs,),
                supersedes_id=prev.record_id,
            ),
        )
    )
    rep = await generate_cash_flow(
        db, test_user.id, start_date=START, end_date=END, currency="SGD", cash_account_ids=frozenset((bank.id,))
    )
    assert (rep["proof_state"], rep["summary"]["beginning_cash"]) == (
        "unproven",
        0,
    ) and "opening_position_unproven" in rep["proof_reasons"]
