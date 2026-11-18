from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.advisor import is_write_request
from src.advisor.base.prompt import DISCLAIMER_EN, get_ai_advisor_prompt
from src.audit import JournalEntrySourceType
from src.extraction import BankStatementStatus, TransactionDirection
from src.extraction.base.source_vocabulary import Stage1Status
from src.extraction.base.validation import validate_balance
from src.extraction.data.account_coverage import StatementCoverageRow, _coverage_issues
from src.extraction.extension.deduplication import DeduplicationService
from src.extraction.extension.statement_posting import (
    is_high_confidence_auto_approve_candidate,
    try_auto_post_statement_opening_balance,
)
from src.extraction.extension.statement_workflow import reject_statement_workflow
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import (
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    account_service,
    calculate_account_balance,
    submit_system_journal_entry,
)
from src.ledger.splits import calculate_reconciliation_adjustment
from src.pricing.base.manual_valuation import ManualValuationComponentType, ManualValuationLiquidityClass
from src.reconciliation.extension.anomaly import detect_anomalies
from src.reporting import (
    EquationDiagnosticCategory,
    diagnose_equation_imbalance,
    generate_balance_sheet,
    generate_cash_flow,
    generate_income_statement,
)
from src.request_context import RequestContext
from src.routers.reports import (
    PackageSnapshotExportFormat,
    export_personal_report_package_snapshot,
    generate_personal_report_package_snapshot,
)
from src.schemas import PersonalReportingFrameworkId, PersonalReportPackageGenerateRequest
from src.schemas.extraction import AccountCoverageIssueType
from tests.reporting.test_personal_report_package_contract import _patch_package_snapshot_inputs
from tests.factories import AtomicTransactionFactory, StatementSummaryFactory
from tests.reporting._report_fixtures import (
    make_entry,
    make_pair_entry,
    post_pair,
    seed_accounts,
    seed_fx_rates,
    seed_valuations,
)


def _check_bs(
    bs: dict, assets: str | Decimal | None = None, liab: str | None = None, eq: str | None = None, ni: str | None = None
) -> None:
    for k, v in (("total_assets", assets), ("total_liabilities", liab), ("total_equity", eq), ("net_income", ni)):
        if v is not None:
            assert bs[k] == Decimal(str(v))
    assert bs["is_balanced"] is True and bs["equation_delta"] == Decimal("0.00")


_LEDGER_SCENARIOS = [
    pytest.param(
        [
            ("Husband DBS", AccountType.ASSET, "SGD"),
            ("Wife StanChart", AccountType.ASSET, "SGD"),
            ("Capital", AccountType.EQUITY, "SGD"),
            ("H Income", AccountType.INCOME, "SGD"),
            ("W Income", AccountType.INCOME, "SGD"),
            ("H Exp", AccountType.EXPENSE, "SGD"),
            ("W Exp", AccountType.EXPENSE, "SGD"),
        ],
        [],
        [
            (
                date(2025, 4, 1),
                "Open",
                [(0, Direction.DEBIT, "10000"), (1, Direction.DEBIT, "5000"), (2, Direction.CREDIT, "15000")],
            ),
            (date(2025, 4, 10), "H Sal", (0, 3, "4000")),
            (date(2025, 4, 15), "H Bon", (0, 3, "1000")),
            (date(2025, 4, 20), "H Exp", (5, 0, "2200")),
            (date(2025, 4, 12), "W Sal", (1, 4, "3500")),
            (date(2025, 4, 18), "W Groc", (6, 1, "400")),
        ],
        date(2025, 4, 1),
        date(2025, 4, 30),
        "SGD",
        {"bs": ("20900.00", "0.00", "15000.00", "5900.00"), "is": ("8500.00", "2600.00", "5900.00")},
        id="case2_household",
    ),
    pytest.param(
        [
            ("Operating SGD", AccountType.ASSET, "SGD"),
            ("Overseas USD", AccountType.ASSET, "USD"),
            ("Overseas HKD", AccountType.ASSET, "HKD"),
            ("Capital", AccountType.EQUITY, "SGD"),
            ("Billing USD", AccountType.INCOME, "USD"),
            ("Billing HKD", AccountType.INCOME, "HKD"),
        ],
        [
            ("USD", "SGD", "1.30", date(2025, 1, 1)),
            ("USD", "SGD", "1.30", date(2025, 1, 15)),
            ("USD", "SGD", "1.35", date(2025, 1, 31)),
            ("HKD", "SGD", "0.16", date(2025, 1, 1)),
            ("HKD", "SGD", "0.16", date(2025, 1, 15)),
            ("HKD", "SGD", "0.17", date(2025, 1, 31)),
        ],
        [
            (date(2025, 1, 1), "Cap", (0, 3, "12800")),
            (date(2025, 1, 10), "USD", (1, 4, "5000", "USD", "1.30")),
            (date(2025, 1, 12), "HKD", (2, 5, "20000", "HKD", "0.16")),
        ],
        None,
        date(2025, 1, 31),
        "SGD",
        {"bs_min_assets": "12800.00", "cta_not_none": True},
        id="case4_multicurrency_cta",
    ),
    pytest.param(
        [
            ("DBS SGD", AccountType.ASSET, "SGD"),
            ("SVB USD", AccountType.ASSET, "USD"),
            ("HSBC HKD", AccountType.ASSET, "HKD"),
            ("Opening Eq", AccountType.EQUITY, "SGD"),
            ("Consult USD", AccountType.INCOME, "USD"),
            ("Div HKD", AccountType.INCOME, "HKD"),
        ],
        [
            ("USD", "SGD", "1.343920", date(2025, 4, 1)),
            ("USD", "SGD", "1.343920", date(2025, 4, 15)),
            ("USD", "SGD", "1.305640", date(2025, 4, 30)),
            ("HKD", "SGD", "0.172706", date(2025, 4, 1)),
            ("HKD", "SGD", "0.172706", date(2025, 4, 15)),
            ("HKD", "SGD", "0.169139", date(2025, 4, 30)),
            ("HKD", "USD", "0.129545", date(2025, 4, 30)),
        ],
        [
            (date(2025, 4, 1), "SGD", (0, 3, "10000")),
            (
                date(2025, 4, 1),
                "USD",
                [(1, Direction.DEBIT, "5000", "USD", "1.343920"), (3, Direction.CREDIT, "6719.60", "SGD", "1.343920")],
            ),
            (
                date(2025, 4, 1),
                "HKD",
                [(2, Direction.DEBIT, "20000", "HKD", "0.172706"), (3, Direction.CREDIT, "3454.12", "SGD", "0.172706")],
            ),
            (date(2025, 4, 10), "Cons", (1, 4, "1800", "USD", "1.319330")),
            (date(2025, 4, 12), "Div", (2, 5, "4000", "HKD", "0.170200")),
        ],
        None,
        date(2025, 4, 30),
        "SGD",
        {"bs": (), "alt_bs": ("USD", "SGD", "0.05")},
        id="case4_opening_equity_usd_view",
    ),
    pytest.param(
        [
            ("Checking", AccountType.ASSET, "SGD"),
            ("Equity", AccountType.EQUITY, "SGD"),
            ("Salary", AccountType.INCOME, "SGD"),
            ("Util", AccountType.EXPENSE, "SGD"),
        ],
        [],
        [
            (date(2025, 1, 1), "Open", (0, 1, "10000")),
            (date(2025, 1, 10), "In", (0, 2, "4500")),
            (date(2025, 1, 20), "Out", (3, 0, "2350.25")),
        ],
        None,
        date(2025, 1, 31),
        "SGD",
        {"bs": ("12149.75",)},
        id="flow1",
    ),
    pytest.param(
        [("Cash", AccountType.ASSET, "SGD"), ("Rev", AccountType.INCOME, "SGD"), ("Cloud", AccountType.EXPENSE, "SGD")],
        [],
        [(date(2025, 2, 1), "Retainer", (0, 1, "3200.00")), (date(2025, 2, 5), "Hosting", (2, 0, "180.50"))],
        None,
        date(2025, 2, 28),
        "SGD",
        {"bs": ("3019.50",)},
        id="flow3",
    ),
    pytest.param(
        [
            ("Condo", AccountType.ASSET, "SGD"),
            ("Equity", AccountType.EQUITY, "SGD"),
            ("Gain", AccountType.EQUITY, "SGD"),
        ],
        [],
        [(date(2025, 1, 1), "Cost", (0, 1, "500000")), (date(2025, 3, 31), "Uplift", (0, 2, "50000"))],
        None,
        date(2025, 3, 31),
        "SGD",
        {"bs": ("550000.00", None, "550000.00")},
        id="flow5",
    ),
    pytest.param(
        [
            ("Bank", AccountType.ASSET, "SGD"),
            ("Suspense", AccountType.EXPENSE, "SGD"),
            ("Groceries", AccountType.EXPENSE, "SGD"),
        ],
        [],
        [(date(2025, 2, 10), "Supermarket", (1, 0, "150")), (date(2025, 2, 10), "Reallocate", (2, 1, "150"))],
        None,
        date(2025, 2, 28),
        "SGD",
        {"bs": ()},
        id="flow11",
    ),
    pytest.param(
        [("Checking", AccountType.ASSET, "SGD"), ("Transport", AccountType.EXPENSE, "SGD")],
        [],
        [
            (date(2025, 2, d), f"GRAB {i}", (1, 0, amt))
            for i, (d, amt) in enumerate([(1, "24.50"), (5, "18.00"), (9, "32.50")], 1)
        ],
        None,
        date(2025, 2, 28),
        "SGD",
        {"bs": ()},
        id="flow12",
    ),
    pytest.param(
        [("Bank", AccountType.ASSET, "SGD"), ("SaaS", AccountType.EXPENSE, "SGD")],
        [],
        [(date(2025, 3, 1), "GitHub", (1, 0, "42.00"))],
        None,
        date(2025, 3, 31),
        "SGD",
        {"bs": ()},
        id="flow13",
    ),
    pytest.param(
        [
            ("Checking", AccountType.ASSET, "SGD"),
            ("Gross Sal", AccountType.EXPENSE, "SGD"),
            ("Tax Pay", AccountType.LIABILITY, "SGD"),
            ("CPF Pay", AccountType.LIABILITY, "SGD"),
        ],
        [],
        [
            (
                date(2025, 3, 25),
                "Payroll",
                [
                    (1, Direction.DEBIT, "6000"),
                    (2, Direction.CREDIT, "900"),
                    (3, Direction.CREDIT, "1200"),
                    (0, Direction.CREDIT, "3900"),
                ],
            )
        ],
        None,
        date(2025, 3, 31),
        "SGD",
        {"bs": ()},
        id="flow14_payroll",
    ),
    pytest.param(
        [
            ("DBS", AccountType.ASSET, "SGD"),
            ("OCBC", AccountType.ASSET, "SGD"),
            ("Clearing", AccountType.ASSET, "SGD"),
            ("Capital", AccountType.EQUITY, "SGD"),
        ],
        [],
        [
            (date(2025, 1, 1), "Cap", (0, 3, "5000")),
            (date(2025, 1, 15), "Out", (2, 0, "2000")),
            (date(2025, 1, 15), "In", (1, 2, "2000")),
        ],
        None,
        date(2025, 1, 31),
        "SGD",
        {"bs": ("5000.00", None, None, "0.00")},
        id="flow15",
    ),
    pytest.param(
        [
            ("Bank", AccountType.ASSET, "SGD"),
            ("Card", AccountType.LIABILITY, "SGD"),
            ("Dining", AccountType.EXPENSE, "SGD"),
            ("Capital", AccountType.EQUITY, "SGD"),
        ],
        [],
        [
            (date(2025, 2, 5), "Dining", (2, 1, "800")),
            (date(2025, 2, 1), "Cap", (0, 3, "2000")),
            (date(2025, 2, 20), "Pay", (1, 0, "800")),
        ],
        None,
        date(2025, 2, 28),
        "SGD",
        {"bs": (None, "0.00", None, "-800.00")},
        id="flow16",
    ),
    pytest.param(
        [
            ("USD Cash", AccountType.ASSET, "USD"),
            ("SGD Cash", AccountType.ASSET, "SGD"),
            ("FX Loss", AccountType.EXPENSE, "SGD"),
            ("Capital", AccountType.EQUITY, "SGD"),
        ],
        [],
        [
            (date(2025, 3, 1), "Cap", (1, 3, "1350")),
            (
                date(2025, 3, 10),
                "FX Conv",
                [
                    (1, Direction.DEBIT, "1320", "SGD"),
                    (2, Direction.DEBIT, "30", "SGD"),
                    (1, Direction.CREDIT, "1350", "SGD"),
                ],
            ),
        ],
        None,
        date(2025, 3, 31),
        "SGD",
        {"bs": ()},
        id="flow17_fx",
    ),
    pytest.param(
        [
            ("IBKR", AccountType.ASSET, "USD"),
            ("VT ETF", AccountType.ASSET, "USD"),
            ("Capital", AccountType.EQUITY, "USD"),
        ],
        [],
        [(date(2025, 1, 1), "Fund", (0, 2, "10000", "USD")), (date(2025, 1, 15), "Buy VT", (1, 0, "5000", "USD"))],
        None,
        date(2025, 1, 31),
        "USD",
        {"bs": ("10000.00",)},
        id="flow19",
    ),
    pytest.param(
        [
            ("Broker Cash", AccountType.ASSET, "USD"),
            ("Div Inc", AccountType.INCOME, "USD"),
            ("WHT Exp", AccountType.EXPENSE, "USD"),
        ],
        [],
        [
            (
                date(2025, 2, 1),
                "WHT",
                [
                    (0, Direction.DEBIT, "840", "USD"),
                    (2, Direction.DEBIT, "360", "USD"),
                    (1, Direction.CREDIT, "1200", "USD"),
                ],
            )
        ],
        None,
        date(2025, 2, 28),
        "USD",
        {"bs": ("840.00", None, None, "840.00")},
        id="flow20_div",
    ),
    pytest.param(
        [
            ("AAPL", AccountType.ASSET, "USD"),
            ("Capital", AccountType.EQUITY, "USD"),
            ("Gain", AccountType.EQUITY, "USD"),
        ],
        [],
        [(date(2025, 1, 1), "Acq", (0, 1, "15000", "USD")), (date(2025, 2, 28), "MtM", (0, 2, "2500", "USD"))],
        None,
        date(2025, 2, 28),
        "USD",
        {"bs": ("17500.00", None, "17500.00")},
        id="flow21",
    ),
    pytest.param(
        [
            ("Checking", AccountType.ASSET, "SGD"),
            ("Capital", AccountType.EQUITY, "SGD"),
            ("Mortgage", AccountType.LIABILITY, "SGD"),
            ("Interest", AccountType.EXPENSE, "SGD"),
        ],
        [],
        [
            (date(2025, 1, 1), "Init", (0, 1, "10000")),
            (
                date(2025, 1, 30),
                "Mtg",
                [(2, Direction.DEBIT, "2000"), (3, Direction.DEBIT, "1500"), (0, Direction.CREDIT, "3500")],
            ),
        ],
        None,
        date(2025, 1, 31),
        "SGD",
        {"bs": ()},
        id="flow22_mortgage",
    ),
    pytest.param(
        [
            ("Checking", AccountType.ASSET, "SGD"),
            ("Capital", AccountType.EQUITY, "SGD"),
            ("Consulting", AccountType.INCOME, "SGD"),
            ("Supplies", AccountType.EXPENSE, "SGD"),
        ],
        [],
        [
            (date(2025, 1, 1), "Open", (0, 1, "5000")),
            (date(2025, 1, 15), "Rev", (0, 2, "3000")),
            (date(2025, 1, 20), "Exp", (3, 0, "1200")),
        ],
        None,
        date(2025, 1, 31),
        "SGD",
        {"bs": ("6800.00", None, "5000.00", "1800.00")},
        id="flow23",
    ),
    pytest.param(
        [
            ("Primary Cash Account", AccountType.ASSET, "SGD"),
            ("Capital", AccountType.EQUITY, "SGD"),
            ("Op Rev", AccountType.INCOME, "SGD"),
            ("Op Exp", AccountType.EXPENSE, "SGD"),
        ],
        [],
        [
            (date(2025, 1, 1), "Dep", (0, 1, "10000")),
            (date(2025, 1, 15), "Rev", (0, 2, "4000")),
            (date(2025, 1, 20), "Exp", (3, 0, "1500")),
        ],
        date(2025, 1, 1),
        date(2025, 1, 31),
        "SGD",
        {"cf": ("12500.00", "12500.00")},
        id="flow26",
    ),
]


@pytest.mark.parametrize(
    ("acct_specs", "fx_specs", "entries", "start_date", "as_of_date", "currency", "expected"), _LEDGER_SCENARIOS
)
async def test_bench_ledger_articulation_scenarios(
    db: AsyncSession, test_user_id, acct_specs, fx_specs, entries, start_date, as_of_date, currency, expected
) -> None:
    accs = await seed_accounts(db, test_user_id, *acct_specs)
    if fx_specs:
        await seed_fx_rates(db, *fx_specs, commit=False)
    for dt, memo, spec in entries:
        db.add(
            make_entry(test_user_id, dt, memo, [(accs[i], d, a, *rest) for i, d, a, *rest in spec])
            if isinstance(spec, list)
            else make_pair_entry(
                test_user_id,
                dt,
                memo,
                accs[spec[0]],
                accs[spec[1]],
                spec[2],
                currency=spec[3] if len(spec) > 3 else currency,
                fx_rate=Decimal(spec[4]) if len(spec) > 4 else None,
            )
        )
    await db.commit()
    if any(k in expected for k in ("bs", "bs_min_assets", "cta_not_none")):
        bs = await generate_balance_sheet(db, test_user_id, as_of_date=as_of_date, currency=currency)
        _check_bs(bs, *expected.get("bs", ()))
        if "bs_min_assets" in expected:
            assert bs["total_assets"] > Decimal(expected["bs_min_assets"])
        if expected.get("cta_not_none"):
            assert bs["cta_adjustment"] is not None
    if "alt_bs" in expected:
        alt_ccy, alt_base, tol = expected["alt_bs"]
        alt_bs = await generate_balance_sheet(
            db, test_user_id, as_of_date=as_of_date, currency=alt_ccy, base_currency=alt_base
        )
        assert alt_bs["is_balanced"] is True and abs(alt_bs["equation_delta"]) < Decimal(tol)
    if "is" in expected:
        inc = await generate_income_statement(
            db, test_user_id, start_date=start_date, end_date=as_of_date, currency=currency
        )
        assert (inc["total_income"], inc["total_expenses"], inc["net_income"]) == tuple(
            Decimal(x) for x in expected["is"]
        )
    if "cf" in expected:
        cf = await generate_cash_flow(db, test_user_id, start_date=start_date, end_date=as_of_date, currency=currency)
        assert (cf["summary"]["net_cash_flow"], cf["summary"]["ending_cash"], cf["cash_bridge"]["reconciles"]) == (
            Decimal(expected["cf"][0]),
            Decimal(expected["cf"][1]),
            True,
        )


async def test_bench_cases_1_3_5_6_multistep_rollforwards(db: AsyncSession, test_user_id) -> None:
    cash, eq, sal, bon, exp, card, art, gain, tax = await seed_accounts(
        db,
        test_user_id,
        ("Cash", AccountType.ASSET),
        ("Equity", AccountType.EQUITY),
        ("Salary", AccountType.INCOME),
        ("Bonus", AccountType.INCOME),
        ("Expenses", AccountType.EXPENSE),
        ("Card", AccountType.LIABILITY),
        ("Art", AccountType.ASSET),
        ("Gain", AccountType.INCOME),
        ("Tax", AccountType.EXPENSE),
    )
    for dt, memo, d_acc, c_acc, amt in (
        (date(2025, 1, 1), "Open", cash, eq, "15450.75"),
        (date(2025, 1, 15), "Sal", cash, sal, "5000.00"),
        (date(2025, 1, 20), "Exp", exp, cash, "5179.52"),
        (date(2025, 2, 15), "Sal", cash, sal, "5000.00"),
        (date(2025, 2, 20), "Bon", cash, bon, "1000.00"),
        (date(2025, 2, 25), "Exp", exp, cash, "3021.23"),
        (date(2025, 3, 15), "Sal", cash, sal, "5000.00"),
        (date(2025, 3, 25), "Exp", exp, cash, "1950.00"),
    ):
        db.add(make_pair_entry(test_user_id, dt, memo, d_acc, c_acc, amt))
    await db.commit()
    bs_q1 = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 3, 31), currency="SGD")
    _check_bs(bs_q1, "21300.00", "0.00", "15450.75", "5849.25")
    is_q1 = await generate_income_statement(
        db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 3, 31), currency="SGD"
    )
    assert (is_q1["total_income"], is_q1["total_expenses"], is_q1["net_income"]) == (
        Decimal("16000.00"),
        Decimal("10150.75"),
        bs_q1["net_income"],
    )
    cf_q1 = await generate_cash_flow(
        db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 3, 31), currency="SGD"
    )
    assert (cf_q1["summary"]["net_cash_flow"], cf_q1["summary"]["ending_cash"], cf_q1["cash_bridge"]["reconciles"]) == (
        Decimal("21300.00"),
        Decimal("21300.00"),
        True,
    )

    await post_pair(db, test_user_id, date(2025, 4, 15), "Apr Sal", cash, sal, "5000.00")
    await post_pair(db, test_user_id, date(2025, 4, 25), "Apr Exp", exp, cash, "2100.00", commit=True)
    _check_bs(
        await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 4, 30), currency="SGD"),
        "24200.00",
        "0.00",
        "15450.75",
        "8749.25",
    )

    await seed_fx_rates(db, ("USD", "SGD", "1.35", date(2025, 4, 30)), commit=False)
    await seed_valuations(
        db,
        test_user_id,
        (
            ManualValuationComponentType.PROPERTY_VALUE,
            ManualValuationLiquidityClass.ILLIQUID,
            "350000.00",
            "USD",
            date(2025, 4, 30),
            "DocuBench",
        ),
    )
    db.add(
        make_entry(
            test_user_id,
            date(2025, 4, 15),
            "Payroll",
            [(cash, Direction.DEBIT, "8000"), (tax, Direction.DEBIT, "2000"), (sal, Direction.CREDIT, "10000")],
        )
    )
    await db.commit()
    _check_bs(
        await generate_balance_sheet(
            db, test_user_id, as_of_date=date(2025, 4, 30), currency="SGD", include_restricted=False
        ),
        "32200.00",
    )
    bs_comp = await generate_balance_sheet(
        db, test_user_id, as_of_date=date(2025, 4, 30), currency="SGD", include_restricted=True
    )
    assert bs_comp["net_worth_adjustment_gain_loss"] == Decimal("350000.00") * Decimal("1.35")

    await post_pair(db, test_user_id, date(2025, 5, 10), "Card dining", exp, card, "1200.00")
    await post_pair(db, test_user_id, date(2025, 5, 5), "Overdraft", exp, cash, "40000.00", commit=True)
    assert (
        await generate_balance_sheet(
            db, test_user_id, as_of_date=date(2025, 5, 15), currency="SGD", include_restricted=False
        )
    )["total_assets"] < 0
    await post_pair(db, test_user_id, date(2025, 5, 25), "Pay card", card, cash, "1200.00")
    await post_pair(db, test_user_id, date(2025, 5, 25), "Buy Art", art, cash, "4000.00")
    db.add(
        make_entry(
            test_user_id,
            date(2025, 5, 25),
            "Sell Art",
            [(cash, Direction.DEBIT, "6500"), (art, Direction.CREDIT, "4000"), (gain, Direction.CREDIT, "2500")],
        )
    )
    await db.commit()
    _check_bs(
        await generate_balance_sheet(
            db, test_user_id, as_of_date=date(2025, 5, 31), currency="SGD", include_restricted=False
        ),
        None,
        "0.00",
    )


async def test_flow_2_batch_multimonth_continuity_and_gap_detection(db: AsyncSession, test_user_id) -> None:
    acc_id, now = uuid4(), datetime.now(UTC)
    s1 = StatementCoverageRow(
        id=uuid4(),
        account_id=acc_id,
        currency="SGD",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        opening_balance=Decimal("10000.00"),
        closing_balance=Decimal("15271.23"),
        updated_at=now,
    )
    s_zero = StatementCoverageRow(
        id=uuid4(),
        account_id=acc_id,
        currency="SGD",
        period_start=date(2025, 4, 1),
        period_end=date(2025, 4, 30),
        opening_balance=Decimal("15271.23"),
        closing_balance=Decimal("18500.00"),
        updated_at=now,
    )
    s_gap = StatementCoverageRow(
        id=uuid4(),
        account_id=acc_id,
        currency="SGD",
        period_start=date(2025, 4, 1),
        period_end=date(2025, 4, 30),
        opening_balance=Decimal("16000.00"),
        closing_balance=Decimal("18500.00"),
        updated_at=now,
    )
    assert _coverage_issues([s1, s_zero], "SGD") == [] and any(
        i.type == AccountCoverageIssueType.GAP and i.delta == Decimal("728.77")
        for i in _coverage_issues([s1, s_gap], "SGD")
    )

    cash, salary = await seed_accounts(
        db, test_user_id, ("DBS Checking", AccountType.ASSET), ("Salary Income", AccountType.INCOME)
    )
    for ps, pe, ob, cb, ed, amt, op in (
        (date(2025, 6, 1), date(2025, 6, 30), "15000", "18000", date(2025, 6, 15), "3000", "jun"),
        (date(2025, 1, 1), date(2025, 1, 31), "10000", "12000", date(2025, 1, 15), "2000", "jan"),
    ):
        stmt = StatementSummaryFactory.build(
            user_id=test_user_id,
            account_id=cash.id,
            institution="DBS",
            currency="SGD",
            period_start=ps,
            period_end=pe,
            opening_balance=Decimal(ob),
            closing_balance=Decimal(cb),
            status=BankStatementStatus.APPROVED,
        )
        db.add(stmt)
        await db.flush()
        await submit_system_journal_entry(
            db,
            user_id=test_user_id,
            entry_date=ed,
            memo=op,
            lines_data=[
                {"account_id": cash.id, "direction": Direction.DEBIT, "amount": Decimal(amt), "currency": "SGD"},
                {"account_id": salary.id, "direction": Direction.CREDIT, "amount": Decimal(amt), "currency": "SGD"},
            ],
            base_currency="SGD",
            operation=f"bench-flow2-{op}",
        )
        await try_auto_post_statement_opening_balance(db, stmt, test_user_id, base_currency="SGD")
    gap_eq = await account_service.get_or_create_unexplained_gap_equity_account(db, test_user_id, "SGD")
    assert await calculate_account_balance(db, gap_eq.id, test_user_id) == Decimal("3000.00")
    _check_bs(
        await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 6, 30), currency="SGD"),
        "18000.00",
        "0.00",
        "13000.00",
        "5000.00",
    )
    stmt_mid = StatementSummaryFactory.build(
        user_id=test_user_id,
        account_id=cash.id,
        institution="DBS",
        currency="SGD",
        period_start=date(2025, 2, 1),
        period_end=date(2025, 5, 31),
        opening_balance=Decimal("12000"),
        closing_balance=Decimal("15000"),
        status=BankStatementStatus.APPROVED,
    )
    db.add(stmt_mid)
    await db.flush()
    await submit_system_journal_entry(
        db,
        user_id=test_user_id,
        entry_date=date(2025, 3, 15),
        memo="mid",
        lines_data=[
            {"account_id": cash.id, "direction": Direction.DEBIT, "amount": Decimal("3000"), "currency": "SGD"},
            {"account_id": salary.id, "direction": Direction.CREDIT, "amount": Decimal("3000"), "currency": "SGD"},
        ],
        base_currency="SGD",
        operation="bench-flow2-mid",
    )
    await try_auto_post_statement_opening_balance(db, stmt_mid, test_user_id, base_currency="SGD")
    assert await calculate_account_balance(db, gap_eq.id, test_user_id) == Decimal("0.00")
    _check_bs(
        await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 6, 30), currency="SGD"),
        "18000.00",
        "0.00",
        "10000.00",
        "8000.00",
    )


async def test_flow_4_6_7_8_9_10_18_24_25_27_29_30_triage_and_audit(db: AsyncSession, test_user_id) -> None:
    cash, eq, sal, exp = await seed_accounts(
        db,
        test_user_id,
        ("Cash", AccountType.ASSET),
        ("Capital", AccountType.EQUITY),
        ("Salary", AccountType.INCOME),
        ("Rent", AccountType.EXPENSE),
    )
    digest = hashlib.sha256(b"RECEIPT_OCR_CONTENT").hexdigest()
    draft = make_pair_entry(
        test_user_id,
        date(2025, 3, 1),
        "Draft",
        cash,
        eq,
        "1200",
        status=JournalEntryStatus.DRAFT,
        source_type=JournalEntrySourceType.AUTO_PARSED,
    )
    db.add(draft)
    await db.commit()
    _check_bs(await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 3, 1), currency="SGD"), "0.00")
    draft.status = JournalEntryStatus.POSTED
    await post_pair(
        db, test_user_id, date(2025, 3, 2), f"Receipt [sha256:{digest}] [stmt_772]", exp, cash, "8.50", commit=True
    )
    assert (await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 3, 2), currency="SGD"))[
        "total_assets"
    ] == Decimal("1191.50")
    assert (
        calculate_reconciliation_adjustment(bank_balance=Decimal("2500.02"), book_balance=Decimal("2500.00")).is_gain
        is True
    )
    await post_pair(db, test_user_id, date(2025, 1, 15), "Jan Sal", cash, sal, "5000")
    await post_pair(db, test_user_id, date(2025, 1, 25), "Jan Rent", exp, cash, "2000")
    await post_pair(db, test_user_id, date(2025, 2, 15), "Feb Sal", cash, sal, "5000")
    await post_pair(db, test_user_id, date(2025, 2, 25), "Feb Rent", exp, cash, "2200", commit=True)
    assert (
        await generate_income_statement(
            db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
        )
    )["net_income"] == Decimal("3000.00")
    assert (
        await generate_income_statement(
            db, test_user_id, start_date=date(2025, 2, 1), end_date=date(2025, 2, 28), currency="SGD"
        )
    )["net_income"] == Decimal("2800.00")
    assert any(
        "stmt_772" in entry.memo
        for _l, entry in (
            await db.execute(
                select(JournalLine, JournalEntry)
                .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
                .where(JournalLine.account_id == cash.id)
            )
        ).all()
    )

    assert not validate_balance(
        {
            "opening_balance": "5000.00",
            "closing_balance": "4600.00",
            "transactions": [{"amount": "200.00", "direction": "OUT"}],
        }
    )["balance_valid"]
    stmt = StatementSummary(
        user_id=test_user_id,
        account_id=cash.id,
        institution="DBS",
        file_hash="quarantine_flow9",
        currency="SGD",
        status=BankStatementStatus.PARSED,
        balance_validated=False,
        confidence_score=35,
    )
    db.add(stmt)
    await db.commit()
    assert is_high_confidence_auto_approve_candidate(stmt) is False
    rej = await reject_statement_workflow(
        db, stmt.id, test_user_id, reason="OCR_RESOLUTION_BELOW_THRESHOLD", base_currency="SGD"
    )
    assert (rej.status, rej.stage1_status, is_high_confidence_auto_approve_candidate(rej)) == (
        BankStatementStatus.REJECTED,
        Stage1Status.REJECTED,
        False,
    )
    kw = dict(
        user_id=uuid4(),
        txn_date=date(2025, 3, 15),
        amount=Decimal("250.00"),
        direction=TransactionDirection.OUT,
        description="OFFICE",
        balance_after=Decimal("8000.00"),
        occurrence_index=0,
    )
    assert DeduplicationService.calculate_transaction_hash(**kw) == DeduplicationService.calculate_transaction_hash(
        **kw
    )
    prompt = get_ai_advisor_prompt(
        {
            "advisor_context": "Statement stmt_2025_03_carson: Carson Bank",
            "total_assets": "12500.00 USD",
            "total_liabilities": "0.00 USD",
            "equity": "12500.00 USD",
        },
        language="en",
    )
    assert all(
        s in prompt
        for s in (
            "Statement stmt_2025_03_carson: Carson Bank",
            "12500.00 USD",
            DISCLAIMER_EN,
            "You can only read the user's financial data",
        )
    )
    assert diagnose_equation_imbalance(Decimal("0.00")).primary_category == EquationDiagnosticCategory.BALANCED
    assert (
        diagnose_equation_imbalance(Decimal("450.00"), unposted_draft_count=1).primary_category
        == EquationDiagnosticCategory.UNPOSTED_DRAFT
    )
    assert all(
        is_write_request(p) for p in ("create a journal entry", "delete journal entry 123", "post a journal entry")
    ) and not any(
        is_write_request(p)
        for p in ("What is my current balance sheet equation delta?", "Summarize my income statement for Q1")
    )

    for i in range(30):
        await AtomicTransactionFactory.create_async(
            db,
            user_id=test_user_id,
            amount=Decimal("1.00"),
            direction=TransactionDirection.OUT,
            txn_date=date.today() - timedelta(days=i % 28 + 1),
            description="STREAMING SUB",
        )
    spike = await AtomicTransactionFactory.create_async(
        db,
        user_id=test_user_id,
        amount=Decimal("5000.00"),
        direction=TransactionDirection.OUT,
        txn_date=date.today(),
        description="STREAMING SUB",
    )
    await db.commit()
    assert any(a.anomaly_type == "LARGE_AMOUNT" for a in await detect_anomalies(db, spike, user_id=test_user_id))


async def test_flow_28_annual_tax_package_zip_export_manifest_integrity(
    db: AsyncSession, test_user_id, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _patch_package_snapshot_inputs(
        monkeypatch, readiness_state="ready", blocking_count=0, section_label="Bench Annual Audit 2025"
    )
    snap = await generate_personal_report_package_snapshot(
        RequestContext(db, test_user_id),
        request=PersonalReportPackageGenerateRequest(
            framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            as_of_date=date(2025, 12, 31),
            currency="SGD",
        ),
    )
    zip_resp = await export_personal_report_package_snapshot(
        snapshot_id=snap.id, format=PackageSnapshotExportFormat.ZIP, ctx=RequestContext(db, test_user_id)
    )
    assert zip_resp.media_type == "application/zip"
    chunks = [c.encode("utf-8") if isinstance(c, str) else c async for c in zip_resp.body_iterator]
    with zipfile.ZipFile(BytesIO(b"".join(chunks)), "r") as zf:
        names = zf.namelist()
        assert {"manifest.json", "balance_sheet.csv", "income_statement.csv", "cash_flow.csv"} <= set(names)
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert (manifest["package_id"], manifest["reporting_currency"]) == (str(snap.id), "SGD") and manifest["files"]
        for entry in manifest["files"]:
            assert hashlib.sha256(zf.read(entry["filename"])).hexdigest() == entry["sha256"]
