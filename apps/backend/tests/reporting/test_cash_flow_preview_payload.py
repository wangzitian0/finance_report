import json
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType, Money
from src.ledger import (
    Account,
    AccountType,
    Direction,
    Entry,
    JournalEntry,
    initialize_opening_positions,
    post_entry,
    submit_system_journal_entry,
)
from src.ledger.base.types.entry import Leg
from src.reporting import generate_cash_flow
from src.reporting.base.cash_flow_types import CashFlowBridge
from src.reporting.extension.cash_flow import _load_cash_events
from tests.factories import seed_year_of_journal_entries
from tests.reporting._report_fixtures import all_pages, count_sql_statements, post_lines, seed_accounts

YEAR_START = date(2025, 1, 1)
YEAR_END = date(2025, 12, 31)
PREVIEW_BYTE_BUDGET = 100000
MAIN_ROUTE_SQL_STATEMENTS = 11
PERIOD = {"start_date": "2026-01-01", "end_date": "2026-01-31", "currency": "SGD"}
SECTIONS = ("operating", "investing", "financing")
UNCLASSIFIED_LINE_ID = "unclassified"
OPENING_STOCK_LINE_ID = "opening_stock"

_json = lambda v: json.loads(json.dumps(v, default=str))


async def test_AC_reporting_cash_flow_6_year_scale_preview_is_bounded(
    client, db: AsyncSession, db_engine, test_user
) -> None:
    await seed_year_of_journal_entries(db, test_user.id, first_day=YEAR_START, entry_count=1000)
    params = {"start_date": YEAR_START.isoformat(), "end_date": YEAR_END.isoformat(), "currency": "SGD"}
    doc = await generate_cash_flow(db, test_user.id, start_date=YEAR_START, end_date=YEAR_END, currency="SGD")
    assert (await client.get("/reports/cash-flow", params=params)).status_code == 200
    with count_sql_statements(db_engine) as stmts:
        resp = await client.get("/reports/cash-flow", params=params)
    assert (
        resp.status_code == 200
        and len(resp.content) < PREVIEW_BYTE_BUDGET
        and stmts["count"] <= MAIN_ROUTE_SQL_STATEMENTS
    )
    preview = resp.json()
    assert "event_lineage" not in preview and preview["summary"] == _json(doc["summary"])
    assert preview["cash_bridge"] == CashFlowBridge.model_validate(doc["cash_bridge"]).model_dump(mode="json")
    assert "opening_stock_adjustment" not in preview["cash_bridge"]
    assert (preview["proof_state"], preview["proof_reasons"]) == (doc["proof_state"], doc["proof_reasons"])
    assert [(item["subcategory"], item["amount"], item["event_count"]) for item in preview["operating"]] == [
        ("Salary", "80000.00", 800)
    ]
    assert preview["investing"] == preview["financing"] == []
    assert preview["lineage_summary"] == {
        "event_count": 1000,
        "classified_event_count": 800,
        "unclassified_event_count": 200,
        "opening_stock_event_count": 0,
    }
    assert (len(doc["operating"]), len(doc["event_lineage"])) == (800, 1000)


async def _transfer(db, user_id, debit: Account, credit: Account, amount: str, on: date, memo: str, **legs):
    return await post_entry(
        db,
        user_id=user_id,
        entry_date=on,
        memo=memo,
        entry=Entry.transfer(debit=debit.id, credit=credit.id, money=Money(Decimal(amount), "SGD"), **legs),
        base_currency="SGD",
        operation=f"cash-flow-preview-{memo}",
    )


async def _seed_every_line_kind(db: AsyncSession, user_id) -> None:
    bank, salary, groc, dining, equip, loans, card = await seed_accounts(
        db,
        user_id,
        ("Main Bank", AccountType.ASSET),
        ("Salary", AccountType.INCOME),
        ("Groceries", AccountType.EXPENSE),
        ("Dining", AccountType.EXPENSE),
        ("Equipment", AccountType.ASSET),
        ("Loans Payable", AccountType.LIABILITY),
        ("Card", AccountType.LIABILITY),
    )
    await initialize_opening_positions(
        db,
        user_id,
        entry_date=date(2026, 1, 5),
        balances={bank.id: Decimal("100")},
        currency="SGD",
        base_currency="SGD",
    )
    for day in (2, 16, 30):
        await _transfer(db, user_id, bank, salary, "3000", date(2026, 1, day), f"salary-{day}")
    for day, amt in ((3, "40"), (9, "25"), (12, "25")):
        await _transfer(db, user_id, groc, bank, amt, date(2026, 1, day), f"groceries-{day}")
    await post_lines(
        db,
        user_id,
        date(2026, 1, 20),
        "groceries-manual",
        [(groc, Direction.DEBIT, "15"), (bank, Direction.CREDIT, "15")],
    )
    await _transfer(db, user_id, bank, groc, "10", date(2026, 1, 21), "groceries-refund")
    await post_entry(
        db,
        user_id=user_id,
        entry_date=date(2026, 1, 22),
        memo="split-dinner",
        entry=Entry.of(
            Leg(groc.id, Direction.DEBIT, Money(Decimal("30"), "SGD")),
            Leg(dining.id, Direction.DEBIT, Money(Decimal("20"), "SGD")),
            Leg(bank.id, Direction.CREDIT, Money(Decimal("50"), "SGD")),
        ),
        base_currency="SGD",
        operation="cash-flow-preview-split-dinner",
    )
    await _transfer(db, user_id, equip, bank, "100", date(2026, 1, 14), "equipment-buy", event_type="investment_buy")
    await submit_system_journal_entry(
        db,
        user_id=user_id,
        entry_date=date(2026, 1, 10),
        memo="loan-repayment",
        lines_data=[
            {
                "account_id": loans.id,
                "direction": Direction.DEBIT,
                "amount": Decimal("400.00"),
                "currency": "SGD",
                "event_type": "bank_txn",
                "tags": {"economic_category": "LOAN_PRINCIPAL"},
            },
            {
                "account_id": bank.id,
                "direction": Direction.CREDIT,
                "amount": Decimal("400.00"),
                "currency": "SGD",
                "event_type": "bank_txn",
                "tags": None,
            },
        ],
        base_currency="SGD",
        operation="cash-flow-preview-loan-repayment",
        source_type=JournalEntrySourceType.AUTO_PARSED,
    )
    await post_lines(
        db,
        user_id,
        date(2026, 1, 25),
        "card-settlement",
        [(card, Direction.DEBIT, "60"), (bank, Direction.CREDIT, "60")],
        commit=True,
    )


async def test_AC_reporting_cash_flow_7_line_events_pages_equal_document(client, db: AsyncSession, test_user) -> None:
    await _seed_every_line_kind(db, test_user.id)
    doc = await generate_cash_flow(
        db, test_user.id, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31), currency="SGD"
    )
    assert _json(doc["summary"]) == {
        "operating_activities": "8855.00",
        "investing_activities": "-100.00",
        "financing_activities": "-400.00",
        "net_cash_flow": "8295.00",
        "beginning_cash": "0.00",
        "ending_cash": "8395.00",
    }
    assert _json(doc["cash_bridge"]) == {
        "classified_activity": "8355.00",
        "unclassified_cash": "-60.00",
        "fx_effect": "0.00",
        "opening_stock_adjustment": "100.00",
        "cash_delta": "8395.00",
        "discrepancy": "0.00",
        "reconciles": True,
    }
    assert doc["proof_reasons"] == [
        "cash_event_classification_ambiguous",
        "cash_event_decision_unproven",
        "cash_identity_compatibility_fallback",
        "opening_coverage_starts_after_period",
    ]
    assert {
        s: [
            (i["category"], i["subcategory"], i["description"], _json(i["amount"]), i["account_id"] is None)
            for i in doc[s]
        ]
        for s in SECTIONS
    } == {
        "operating": [("Operating", "Salary", "Inflow - Salary", "3000.00", False)] * 3
        + [
            ("Operating", "Dining, Groceries", "Outflow - Dining, Groceries", "-50.00", True),
            ("Operating", "Groceries", "Outflow - Groceries", "-40.00", False),
            ("Operating", "Groceries", "Outflow - Groceries", "-25.00", False),
            ("Operating", "Groceries", "Outflow - Groceries", "-25.00", False),
            ("Operating", "Groceries", "Outflow - Groceries", "-15.00", False),
            ("Operating", "Groceries", "Inflow - Groceries", "10.00", False),
        ],
        "investing": [("Investing", "Equipment", "Outflow - Equipment", "-100.00", False)],
        "financing": [("Financing", "Loans Payable", "Outflow - Loans Payable", "-400.00", False)],
    }
    anchored, manual = ("system", "anchored", False), ("manual", "legacy_unproven", True)
    assert [
        (
            i["activity"],
            i["reason_code"],
            i["source_type"],
            i["decision_authority_state"],
            i["decision_anchor_id"] is None,
            i["source_id"],
            i["event_types"],
            len(i["journal_line_ids"]),
        )
        for i in doc["event_lineage"]
    ] == [
        ("Operating", None, *anchored, None, [], 2),
        ("Operating", None, *anchored, None, [], 2),
        (None, "opening_stock", *anchored, None, [], 2),
        ("Operating", None, *anchored, None, [], 2),
        ("Financing", None, "auto_parsed", "anchored", False, None, ["bank_txn"], 2),
        ("Operating", None, *anchored, None, [], 2),
        ("Investing", None, *anchored, None, ["investment_buy"], 2),
        ("Operating", None, *anchored, None, [], 2),
        ("Operating", None, *manual, None, [], 2),
        ("Operating", None, *anchored, None, [], 2),
        ("Operating", None, *anchored, None, [], 3),
        (None, "cash_event_classification_ambiguous", *manual, None, [], 2),
        ("Operating", None, *anchored, None, [], 2),
    ]
    preview = (await client.get("/reports/cash-flow", params=PERIOD)).json()
    assert all(
        preview[k] == _json(doc[k])
        for k in ("start_date", "end_date", "currency", "summary", "cash_bridge", "proof_state", "proof_reasons")
    )
    assert preview["lineage_summary"] == {
        "event_count": 13,
        "classified_event_count": 11,
        "unclassified_event_count": 1,
        "opening_stock_event_count": 1,
    }
    for sec in SECTIONS:
        expected = defaultdict(lambda: [Decimal("0"), 0])
        for item in doc[sec]:
            g = expected[item["description"], _json(item["account_id"])]
            g[0] += item["amount"]
            g[1] += 1
        lines = preview[sec]
        assert {
            (item["description"], item["account_id"]): (Decimal(item["amount"]), item["event_count"]) for item in lines
        } == {k: tuple(v) for k, v in expected.items()}
        assert len({item["line_id"] for item in lines}) == len(lines) and [
            abs(Decimal(item["amount"])) for item in lines
        ] == sorted((abs(Decimal(item["amount"])) for item in lines), reverse=True)
        assert sum((Decimal(item["amount"]) for item in lines), Decimal("0")) == Decimal(
            preview["summary"][f"{sec}_activities"]
        )
    assert [(item["subcategory"], item["account_id"] is None) for item in preview["operating"]] == [
        ("Salary", False),
        ("Groceries", False),
        ("Dining, Groceries", True),
        ("Groceries", False),
    ]

    lineage_pos = {(r["journal_entry_id"], r["reason_code"]): idx for idx, r in enumerate(_json(doc["event_lineage"]))}
    memo_by_entry = {
        str(e.id): (e.memo, e.entry_date.isoformat())
        for e in (await db.execute(select(JournalEntry).where(JournalEntry.user_id == test_user.id))).scalars()
    }
    paged: list[dict] = []

    async def _line_records(line_id: str) -> list[dict]:
        events, total = await all_pages(
            client, "/reports/cash-flow/line-events", {**PERIOD, "line_id": line_id}, limit=2, item_key="events"
        )
        assert total == len(events)
        positions = [lineage_pos[i["journal_entry_id"], i["reason_code"]] for i in events]
        assert positions == sorted(positions) and all(
            (i["memo"], i["entry_date"]) == memo_by_entry[i["journal_entry_id"]] for i in events
        )
        paged.extend(events)
        return events

    for line in [item for s in SECTIONS for item in preview[s]]:
        events = await _line_records(line["line_id"])
        group_amts = Counter(
            _json(i["amount"])
            for i in doc[line["category"].lower()]
            if (i["description"], _json(i["account_id"])) == (line["description"], line["account_id"])
        )
        assert (
            len(events) == line["event_count"]
            and Counter(i["amount"] for i in events) == group_amts
            and sum((Decimal(i["amount"]) for i in events), Decimal("0")) == Decimal(line["amount"])
            and {i["activity"] for i in events} == {line["category"]}
        )
    assert [(i["memo"], i["amount"], i["reason_code"]) for i in await _line_records(UNCLASSIFIED_LINE_ID)] == [
        ("card-settlement", "-60.00", "cash_event_classification_ambiguous")
    ]
    assert [(i["amount"], i["reason_code"]) for i in await _line_records(OPENING_STOCK_LINE_ID)] == [
        ("100.00", "opening_stock")
    ]
    keys = set(doc["event_lineage"][0])
    assert sorted(
        ({k: i[k] for k in keys} for i in paged), key=lambda r: lineage_pos[r["journal_entry_id"], r["reason_code"]]
    ) == _json(doc["event_lineage"])
    assert (
        await client.get("/reports/cash-flow/line-events", params={**PERIOD, "line_id": "operating-0000000000000000"})
    ).status_code == 404
    assert (
        await client.get(
            "/reports/cash-flow/line-events", params={**PERIOD, "line_id": UNCLASSIFIED_LINE_ID, "limit": 501}
        )
    ).status_code == 422
    rev = await client.get(
        "/reports/cash-flow/line-events",
        params={"start_date": "2026-02-01", "end_date": "2026-01-01", "line_id": UNCLASSIFIED_LINE_ID},
    )
    assert rev.status_code == 400 and "start_date must be before end_date" in rev.text


async def test_cash_event_read_resolves_an_account_that_the_caller_did_not_load(db: AsyncSession, test_user) -> None:
    bank, salary = await seed_accounts(
        db, test_user.id, ("Main Bank", AccountType.ASSET), ("Salary", AccountType.INCOME)
    )
    await _transfer(db, test_user.id, bank, salary, "30", date(2026, 1, 2), "salary-concurrent")
    acc_by_id = {bank.id: bank}
    events = await _load_cash_events(
        db, test_user.id, end_date=date(2026, 1, 31), cash_account_ids=frozenset({bank.id}), account_by_id=acc_by_id
    )
    assert [(e.cash_lines[0][1].id, e.counterpart_lines[0][1].id) for e in events] == [(bank.id, salary.id)] and set(
        acc_by_id
    ) == {bank.id, salary.id}
