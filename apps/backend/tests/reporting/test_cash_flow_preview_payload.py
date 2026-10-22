"""Bounded cash-flow preview and paged line events (#2583 S10).

``GET /reports/cash-flow`` returns one statement line for each activity, flow direction and
counterpart, with its event count. The events of a line load page by page from
``GET /reports/cash-flow/line-events``. ``generate_cash_flow`` still returns the complete
document: the CSV export and the package snapshot read it.
"""

import json
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType, Money
from src.ledger import (
    Account,
    AccountType,
    Direction,
    Entry,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    initialize_opening_positions,
    post_entry,
    submit_system_journal_entry,
)
from src.ledger.base.types.entry import Leg
from src.reporting import generate_cash_flow
from src.reporting.base.cash_flow_types import CashFlowBridge
from src.reporting.extension.cash_flow import _load_cash_events
from tests.factories import seed_year_of_journal_entries

YEAR_START = date(2025, 1, 1)
YEAR_END = date(2025, 12, 31)
#: The response bound of AC-reporting.cash-flow.6. On main ``56bb9eca`` the response of the
#: year-scale fixture is 454,845 bytes: one item and one lineage record for each event.
PREVIEW_BYTE_BUDGET = 100_000
#: The SQL statements of the route on main ``56bb9eca`` for the year-scale fixture.
MAIN_ROUTE_SQL_STATEMENTS = 11
PERIOD = {"start_date": "2026-01-01", "end_date": "2026-01-31", "currency": "SGD"}
SECTIONS = ("operating", "investing", "financing")
UNCLASSIFIED_LINE_ID = "unclassified"
OPENING_STOCK_LINE_ID = "opening_stock"


@contextmanager
def _count_statements(db_engine):
    statements = {"count": 0}

    def _count(conn, cursor, statement, parameters, context, executemany):
        statements["count"] += 1

    event.listen(db_engine.sync_engine, "before_cursor_execute", _count)
    try:
        yield statements
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _count)


def _json(value):
    """Normalize a document value to its JSON form, as the API returns it."""
    return json.loads(json.dumps(value, default=str))


async def test_AC_reporting_cash_flow_6_year_scale_preview_is_bounded(
    client, db: AsyncSession, db_engine, test_user
) -> None:
    """AC-reporting.cash-flow.6: at one year of activity (1000 entries), GET /reports/cash-flow
    returns less than 100 KB with no more SQL statements than before #2583 S10. Each line has an
    event count. The response has no per-event lineage, and its totals equal the document."""
    await seed_year_of_journal_entries(db, test_user.id, first_day=YEAR_START, entry_count=1000)
    params = {"start_date": YEAR_START.isoformat(), "end_date": YEAR_END.isoformat(), "currency": "SGD"}
    document = await generate_cash_flow(db, test_user.id, start_date=YEAR_START, end_date=YEAR_END, currency="SGD")

    warm_up = await client.get("/reports/cash-flow", params=params)
    assert warm_up.status_code == 200, warm_up.text
    with _count_statements(db_engine) as statements:
        response = await client.get("/reports/cash-flow", params=params)
    assert response.status_code == 200, response.text

    preview = response.json()
    measured = (len(response.content), statements["count"])
    assert measured[0] < PREVIEW_BYTE_BUDGET and measured[1] <= MAIN_ROUTE_SQL_STATEMENTS, measured
    assert "event_lineage" not in preview
    assert preview["summary"] == _json(document["summary"])
    # The bridge omits a zero opening-stock adjustment, as before #2583 S10.
    assert preview["cash_bridge"] == CashFlowBridge.model_validate(document["cash_bridge"]).model_dump(mode="json")
    assert "opening_stock_adjustment" not in preview["cash_bridge"]
    assert (preview["proof_state"], preview["proof_reasons"]) == (document["proof_state"], document["proof_reasons"])
    # 800 salary receipts form one operating line; 200 card settlements stay unclassified.
    assert [(line["subcategory"], line["amount"], line["event_count"]) for line in preview["operating"]] == [
        ("Salary", "80000.00", 800)
    ]
    assert preview["investing"] == preview["financing"] == []
    assert preview["lineage_summary"] == {
        "event_count": 1000,
        "classified_event_count": 800,
        "unclassified_event_count": 200,
        "opening_stock_event_count": 0,
    }
    assert len(document["operating"]) == 800
    assert len(document["event_lineage"]) == 1000


async def _account(db: AsyncSession, user_id, name: str, account_type: AccountType) -> Account:
    account = Account(user_id=user_id, name=name, type=account_type, currency="SGD")
    db.add(account)
    await db.flush()
    return account


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


async def _manual(db, user_id, memo: str, on: date, lines) -> JournalEntry:
    entry = JournalEntry(user_id=user_id, entry_date=on, memo=memo, status=JournalEntryStatus.POSTED)
    db.add(entry)
    await db.flush()
    db.add_all(
        JournalLine(
            journal_entry_id=entry.id,
            account_id=account.id,
            direction=direction,
            amount=Decimal(amount),
            currency="SGD",
        )
        for account, direction, amount in lines
    )
    await db.flush()
    return entry


async def _seed_every_line_kind(db: AsyncSession, user_id) -> None:
    """One month with every kind of cash-flow lineage record.

    Operating receipts and payments on one account (several events on a line), a refund on
    the same account (its own line), a split payment with two counterparts (no account id),
    an investing purchase, a financing repayment, an unclassified card settlement and a
    mid-period opening position.
    """
    bank = await _account(db, user_id, "Main Bank", AccountType.ASSET)
    salary = await _account(db, user_id, "Salary", AccountType.INCOME)
    groceries = await _account(db, user_id, "Groceries", AccountType.EXPENSE)
    dining = await _account(db, user_id, "Dining", AccountType.EXPENSE)
    equipment = await _account(db, user_id, "Equipment", AccountType.ASSET)
    loans = await _account(db, user_id, "Loans Payable", AccountType.LIABILITY)
    card = await _account(db, user_id, "Card", AccountType.LIABILITY)

    await initialize_opening_positions(
        db, user_id, entry_date=date(2026, 1, 5), balances={bank.id: Decimal("100")}, currency="SGD"
    )
    for day in (2, 16, 30):
        await _transfer(db, user_id, bank, salary, "3000", date(2026, 1, day), f"salary-{day}")
    for day, amount in ((3, "40"), (9, "25"), (12, "25")):
        await _transfer(db, user_id, groceries, bank, amount, date(2026, 1, day), f"groceries-{day}")
    await _manual(
        db,
        user_id,
        "groceries-manual",
        date(2026, 1, 20),
        [(groceries, Direction.DEBIT, "15"), (bank, Direction.CREDIT, "15")],
    )
    await _transfer(db, user_id, bank, groceries, "10", date(2026, 1, 21), "groceries-refund")
    await post_entry(
        db,
        user_id=user_id,
        entry_date=date(2026, 1, 22),
        memo="split-dinner",
        entry=Entry.of(
            Leg(groceries.id, Direction.DEBIT, Money(Decimal("30"), "SGD")),
            Leg(dining.id, Direction.DEBIT, Money(Decimal("20"), "SGD")),
            Leg(bank.id, Direction.CREDIT, Money(Decimal("50"), "SGD")),
        ),
        base_currency="SGD",
        operation="cash-flow-preview-split-dinner",
    )
    await _transfer(
        db, user_id, equipment, bank, "100", date(2026, 1, 14), "equipment-buy", event_type="investment_buy"
    )
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
    await _manual(
        db,
        user_id,
        "card-settlement",
        date(2026, 1, 25),
        [(card, Direction.DEBIT, "60"), (bank, Direction.CREDIT, "60")],
    )
    await db.commit()


async def _all_pages(client, line_id: str) -> tuple[int, list[dict]]:
    events: list[dict] = []
    offset = 0
    total = None
    while total is None or offset < total:
        response = await client.get(
            "/reports/cash-flow/line-events", params={**PERIOD, "line_id": line_id, "limit": 2, "offset": offset}
        )
        assert response.status_code == 200, response.text
        page = response.json()
        assert (page["line_id"], page["limit"], page["offset"]) == (line_id, 2, offset)
        assert len(page["events"]) == min(2, page["total"] - offset)
        total = page["total"]
        events.extend(page["events"])
        offset += 2
    return total, events


async def test_AC_reporting_cash_flow_7_line_events_pages_equal_document(client, db: AsyncSession, test_user) -> None:
    """AC-reporting.cash-flow.7: the preview lines and the paged line events equal the complete
    document of the same data. The document equals the output of main ``56bb9eca``."""
    await _seed_every_line_kind(db, test_user.id)
    document = await generate_cash_flow(
        db, test_user.id, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31), currency="SGD"
    )

    # The complete document, frozen from main 56bb9eca on this fixture.
    assert _json(document["summary"]) == {
        "operating_activities": "8855.00",
        "investing_activities": "-100.00",
        "financing_activities": "-400.00",
        "net_cash_flow": "8295.00",
        "beginning_cash": "0.00",
        "ending_cash": "8395.00",
    }
    assert _json(document["cash_bridge"]) == {
        "classified_activity": "8355.00",
        "unclassified_cash": "-60.00",
        "fx_effect": "0.00",
        "opening_stock_adjustment": "100.00",
        "cash_delta": "8395.00",
        "discrepancy": "0.00",
        "reconciles": True,
    }
    assert document["proof_reasons"] == [
        "cash_event_classification_ambiguous",
        "cash_event_decision_unproven",
        "cash_identity_compatibility_fallback",
        "opening_coverage_starts_after_period",
    ]
    assert {
        section: [
            (
                item["category"],
                item["subcategory"],
                item["description"],
                _json(item["amount"]),
                item["account_id"] is None,
            )
            for item in document[section]
        ]
        for section in SECTIONS
    } == {
        "operating": [
            ("Operating", "Salary", "Inflow - Salary", "3000.00", False),
            ("Operating", "Salary", "Inflow - Salary", "3000.00", False),
            ("Operating", "Salary", "Inflow - Salary", "3000.00", False),
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
    anchored = ("system", "anchored", False)
    manual = ("manual", "legacy_unproven", True)
    assert [
        (
            item["activity"],
            item["reason_code"],
            item["source_type"],
            item["decision_authority_state"],
            item["decision_anchor_id"] is None,
            item["source_id"],
            item["event_types"],
            len(item["journal_line_ids"]),
        )
        for item in document["event_lineage"]
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

    response = await client.get("/reports/cash-flow", params=PERIOD)
    assert response.status_code == 200, response.text
    preview = response.json()
    for key in ("start_date", "end_date", "currency", "summary", "cash_bridge", "proof_state", "proof_reasons"):
        assert preview[key] == _json(document[key]), key
    assert preview["lineage_summary"] == {
        "event_count": 13,
        "classified_event_count": 11,
        "unclassified_event_count": 1,
        "opening_stock_event_count": 1,
    }

    # Each preview line is the group of document items with one category, description and account.
    for section in SECTIONS:
        expected = defaultdict(lambda: [Decimal("0"), 0])
        for item in document[section]:
            group = expected[(item["description"], _json(item["account_id"]))]
            group[0] += item["amount"]
            group[1] += 1
        lines = preview[section]
        assert {
            (line["description"], line["account_id"]): (Decimal(line["amount"]), line["event_count"]) for line in lines
        } == {key: tuple(value) for key, value in expected.items()}, section
        assert len({line["line_id"] for line in lines}) == len(lines)
        assert [abs(Decimal(line["amount"])) for line in lines] == sorted(
            (abs(Decimal(line["amount"])) for line in lines), reverse=True
        )
        assert sum((Decimal(line["amount"]) for line in lines), Decimal("0")) == Decimal(
            preview["summary"][f"{section}_activities"]
        )
    assert [(line["subcategory"], line["account_id"] is None) for line in preview["operating"]] == [
        ("Salary", False),
        ("Groceries", False),
        ("Dining, Groceries", True),
        ("Groceries", False),
    ]

    # Every lineage record of the document is on exactly one line, in document order.
    lineage_position = {
        (record["journal_entry_id"], record["reason_code"]): index
        for index, record in enumerate(_json(document["event_lineage"]))
    }
    memo_by_entry = {
        str(entry.id): (entry.memo, entry.entry_date.isoformat())
        for entry in (await db.execute(select(JournalEntry).where(JournalEntry.user_id == test_user.id))).scalars()
    }
    paged: list[dict] = []

    async def _line_records(line_id: str) -> list[dict]:
        total, events = await _all_pages(client, line_id)
        assert total == len(events)
        positions = [lineage_position[(item["journal_entry_id"], item["reason_code"])] for item in events]
        assert positions == sorted(positions), line_id
        for item in events:
            assert (item["memo"], item["entry_date"]) == memo_by_entry[item["journal_entry_id"]]
        paged.extend(events)
        return events

    for line in [line for section in SECTIONS for line in preview[section]]:
        events = await _line_records(line["line_id"])
        group_amounts = Counter(
            _json(item["amount"])
            for item in document[line["category"].lower()]
            if (item["description"], _json(item["account_id"])) == (line["description"], line["account_id"])
        )
        assert len(events) == line["event_count"]
        assert Counter(item["amount"] for item in events) == group_amounts, line["line_id"]
        assert sum((Decimal(item["amount"]) for item in events), Decimal("0")) == Decimal(line["amount"])
        assert {item["activity"] for item in events} == {line["category"]}
    unclassified = await _line_records(UNCLASSIFIED_LINE_ID)
    opening = await _line_records(OPENING_STOCK_LINE_ID)
    assert [(item["memo"], item["amount"], item["reason_code"]) for item in unclassified] == [
        ("card-settlement", "-60.00", "cash_event_classification_ambiguous")
    ]
    assert [(item["amount"], item["reason_code"]) for item in opening] == [("100.00", "opening_stock")]

    lineage_keys = set(document["event_lineage"][0])
    assert sorted(
        ({key: item[key] for key in lineage_keys} for item in paged),
        key=lambda record: lineage_position[(record["journal_entry_id"], record["reason_code"])],
    ) == _json(document["event_lineage"])

    missing = await client.get(
        "/reports/cash-flow/line-events", params={**PERIOD, "line_id": "operating-0000000000000000"}
    )
    assert missing.status_code == 404, missing.text
    too_large = await client.get(
        "/reports/cash-flow/line-events", params={**PERIOD, "line_id": UNCLASSIFIED_LINE_ID, "limit": 501}
    )
    assert too_large.status_code == 422
    reversed_period = await client.get(
        "/reports/cash-flow/line-events",
        params={"start_date": "2026-02-01", "end_date": "2026-01-01", "line_id": UNCLASSIFIED_LINE_ID},
    )
    assert reversed_period.status_code == 400, reversed_period.text
    assert "start_date must be before end_date" in reversed_period.text


async def test_cash_event_read_resolves_an_account_that_the_caller_did_not_load(db: AsyncSession, test_user) -> None:
    """The column read of the cash events adds a tenant account that is not in the caller's map.

    A concurrent request can create an account between the account read and the event read.
    """
    bank = await _account(db, test_user.id, "Main Bank", AccountType.ASSET)
    salary = await _account(db, test_user.id, "Salary", AccountType.INCOME)
    await _transfer(db, test_user.id, bank, salary, "30", date(2026, 1, 2), "salary-concurrent")
    account_by_id = {bank.id: bank}

    events = await _load_cash_events(
        db, test_user.id, end_date=date(2026, 1, 31), cash_account_ids=frozenset({bank.id}), account_by_id=account_by_id
    )

    assert [(event.cash_lines[0][1].id, event.counterpart_lines[0][1].id) for event in events] == [(bank.id, salary.id)]
    assert set(account_by_id) == {bank.id, salary.id}
