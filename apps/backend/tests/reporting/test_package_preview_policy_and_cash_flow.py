"""The package preview bounds its framework policy decisions and its cash flow (#2583 S11).

Before S11, ``GET /reports/package`` returned every framework policy decision and every cash
event of the period. A user with one year of reviewed bank statements (960 transactions) got
1,322 KB: 763 KB of decisions (one for each categorized journal line) and 534 KB of cash flow
(one item and one lineage record for each cash event). The S8 fixture had no category tag and
no statement cash account, so it produced neither field at that size.

The preview now carries the decision count, a first page of decisions, and the cash-flow lines
with their event counts. ``GET /reports/package/policy-decisions`` and
``GET /reports/package/cash-flow-events`` return the lists page by page. A frozen snapshot keeps
the complete document.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import event, select
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import ORMExecuteState, Session

from src.ledger import Account, JournalLine
from src.reporting import PackageAssembler, derive_user_framework_policy_result, generate_cash_flow
from src.reporting.base.cash_flow_types import CashFlowResponse
from src.reporting.extension import package_document
from src.schemas.reporting import PersonalReportingFrameworkId, PersonalReportPackageDocument
from tests.reporting.test_package_preview_payload import (
    JUNE,
    YEAR,
    _all_pages,
    _counting_statements,
    _seed_year_of_anchored_entries,
)
from tests.reporting.test_package_readiness_path import _seed_ready

FRAMEWORK = PersonalReportingFrameworkId.US_GAAP_LIKE
EXPENSE_CATEGORIES = ("GROCERIES", "DINING")
PREVIEW_BYTE_BUDGET = 300_000
# SQL statements of ``GET /reports/package`` for the fixture below on main ``aa8fb630``. On main the
# preview of the fixture is 1,386,558 bytes: 850,092 of decisions and 510,767 of cash flow.
MAIN_PREVIEW_SQL_STATEMENTS = 105
# The fixture must reproduce the shape of the staging payload (#2583 S11): 763 KB of decisions and
# 534 KB of cash flow at 960 transactions. A smaller complete document means an empty fixture.
MIN_DECISIONS_BYTES = 700_000
MIN_CASH_FLOW_BYTES = 400_000
SECTIONS = ("operating", "investing", "financing")
FIXED_LINE_IDS = ("unclassified", "opening_stock")


def _json(value) -> object:
    """Normalize a value to its JSON form, as the API returns it."""
    return json.loads(json.dumps(value, default=str))


def _size(value) -> int:
    return len(json.dumps(value, separators=(",", ":"), default=str))


async def _seed_year_of_reviewed_statements(db: AsyncSession, user_id, monkeypatch: pytest.MonkeyPatch) -> Account:
    """One reviewed bank statement, and one year of categorized entries on its cash account.

    The statement makes the bank account a package cash account, as an approved statement does.
    The entries carry the ``economic_category`` tag that a reviewed statement posting writes, so
    each of them is one framework policy decision and one cash event. Return the bank account.
    """
    await _seed_ready(db, user_id, monkeypatch)
    bank = (await db.execute(select(Account).where(Account.user_id == user_id, Account.name == "DBS"))).scalar_one()
    await _seed_year_of_anchored_entries(db, user_id, bank=bank, categories=EXPENSE_CATEGORIES)
    return bank


async def _assemble(db: AsyncSession, user_id, period: dict[str, str]) -> PersonalReportPackageDocument:
    """The complete preview document of a period: what a snapshot stores and what the preview projects."""
    return await PackageAssembler().assemble(
        db,
        user_id=user_id,
        framework_id=FRAMEWORK,
        start_date=date.fromisoformat(period["start_date"]),
        end_date=date.fromisoformat(period["end_date"]),
        as_of_date=date.fromisoformat(period["as_of_date"]),
        currency=period["currency"],
    )


async def _assert_event_pages_equal_lineage(
    client, query: dict[str, str], preview_cash_flow: dict, cash_flow: dict
) -> None:
    """Every lineage record of the complete ``cash_flow`` is on exactly one line, in document order.

    The lines are the lines of the preview, plus the two fixed lines. Each page request reads the
    statement contributions and the cash events again, so the test reads each line with one page.
    """
    lineage = cash_flow["event_lineage"]
    lineage_position = {
        (record["journal_entry_id"], record["reason_code"]): index for index, record in enumerate(lineage)
    }
    paged: list[dict] = []

    async def _line_records(line_id: str) -> list[dict]:
        events, total = await _all_pages(
            client,
            "/reports/package/cash-flow-events",
            {**query, "line_id": line_id},
            limit=500,
            item_key="events",
        )
        assert total == len(events), line_id
        positions = [lineage_position[(item["journal_entry_id"], item["reason_code"])] for item in events]
        assert positions == sorted(positions), line_id
        paged.extend(events)
        return events

    events_by_line: dict[str, list[dict]] = {}
    for section in SECTIONS:
        for line in preview_cash_flow[section]:
            events = events_by_line[line["line_id"]] = await _line_records(line["line_id"])
            assert len(events) == line["event_count"], line["line_id"]
            assert sum((Decimal(item["amount"]) for item in events), Decimal("0")) == Decimal(line["amount"])
            assert {item["activity"] for item in events} == {line["category"]}
    summary = preview_cash_flow["lineage_summary"]
    assert len(await _line_records("unclassified")) == summary["unclassified_event_count"]
    assert len(await _line_records("opening_stock")) == summary["opening_stock_event_count"]

    # Every record is on exactly one line, and the lineage fields are unchanged.
    assert len(paged) == len(lineage) == summary["event_count"]
    lineage_keys = set(lineage[0])
    assert [
        {key: item[key] for key in lineage_keys}
        for item in sorted(
            paged, key=lambda record: lineage_position[(record["journal_entry_id"], record["reason_code"])]
        )
    ] == lineage
    # The amounts of the lines equal the amounts of the items.
    for section in SECTIONS:
        item_amounts = Counter(item["amount"] for item in cash_flow[section])
        page_amounts = Counter(
            item["amount"] for line in preview_cash_flow[section] for item in events_by_line[line["line_id"]]
        )
        assert page_amounts == item_amounts, section


async def test_AC_reporting_package_traceability_9_year_scale_preview_with_categories_is_bounded(
    client, db: AsyncSession, db_engine, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-reporting.package-traceability.9: at one year of categorized statement activity (1000
    entries), GET /reports/package returns less than 300 KB with no more SQL statements than
    before #2583 S11. The framework policy has the decision count and a first page of decisions.
    The cash flow has one line for each activity, direction and counterpart, and the lineage
    counts. The readiness and every other field equal the complete document."""
    await _seed_year_of_reviewed_statements(db, test_user.id, monkeypatch)
    with _counting_statements(db_engine) as counter:
        response = await client.get("/reports/package", params=YEAR)

    assert response.status_code == 200, response.text
    measured = (len(response.content), counter["statements"])
    assert measured[0] < PREVIEW_BYTE_BUDGET and measured[1] <= MAIN_PREVIEW_SQL_STATEMENTS, measured
    preview = response.json()

    full = (await _assemble(db, test_user.id, YEAR)).model_dump(mode="json")
    # The fixture is not empty: the complete document has the size of the staging payload.
    assert _size(full["framework_policy"]["decisions"]) > MIN_DECISIONS_BYTES
    assert _size(full["sections"]["cash_flow"]) > MIN_CASH_FLOW_BYTES
    assert len(full["sections"]["cash_flow"]["event_lineage"]) > 1000

    assert preview["readiness"] == full["readiness"]
    policy = preview["framework_policy"]
    full_policy = full["framework_policy"]
    page_size = package_document.PACKAGE_POLICY_PREVIEW_DECISIONS
    assert policy["decision_count"] == len(full_policy["decisions"]) > page_size
    assert policy["decisions"] == full_policy["decisions"][:page_size]
    assert policy["gaps"] == full_policy["gaps"]
    for key in ("result_id", "framework_id", "matrix_version", "required_statements", "generated_at"):
        assert policy[key] == full_policy[key], key
    references = {
        f"{anchor['anchor_type']}:{anchor['source_id']}"
        for item in [*full_policy["decisions"], *full_policy["gaps"]]
        for anchor in item["evidence_anchors"]
    }
    assert policy["evidence_reference_count"] == len(references) > page_size

    cash_flow = preview["sections"]["cash_flow"]
    full_cash_flow = full["sections"]["cash_flow"]
    assert "event_lineage" not in cash_flow
    for key in ("start_date", "end_date", "currency", "summary", "cash_bridge", "proof_state", "proof_reasons"):
        assert cash_flow[key] == full_cash_flow[key], key
    reasons = Counter(record["reason_code"] for record in full_cash_flow["event_lineage"])
    assert cash_flow["lineage_summary"] == {
        "event_count": len(full_cash_flow["event_lineage"]),
        "classified_event_count": reasons[None],
        "unclassified_event_count": reasons["cash_event_classification_ambiguous"],
        "opening_stock_event_count": reasons["opening_stock"],
    }
    # Each line is the group of document items with one description and counterpart account.
    for section in SECTIONS:
        expected = defaultdict(lambda: [Decimal("0"), 0])
        for item in full_cash_flow[section]:
            group = expected[(item["description"], item["account_id"])]
            group[0] += Decimal(item["amount"])
            group[1] += 1
        assert {
            (line["description"], line["account_id"]): (Decimal(line["amount"]), line["event_count"])
            for line in cash_flow[section]
        } == {key: tuple(value) for key, value in expected.items()}, section
    # The salary receipts form lines, and each expense category forms one.
    assert len(cash_flow["operating"]) >= 1 + len(EXPENSE_CATEGORIES)
    assert sum(line["event_count"] for section in SECTIONS for line in cash_flow[section]) == reasons[None]
    for key in ("balance_sheet", "income_statement", "investment_performance", "annualized_income_long_term", "notes"):
        assert preview["sections"][key] == full["sections"][key], key


async def test_AC_reporting_package_traceability_10_policy_decision_pages_equal_snapshot(
    client, db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-reporting.package-traceability.10: GET /reports/package/policy-decisions returns, page
    by page, the framework policy decisions of the complete document, in the same order. The
    document equals the policy that ``derive_user_framework_policy_result`` returns, which the
    snapshot stores (the small snapshot test below reads a stored snapshot)."""
    await _seed_year_of_reviewed_statements(db, test_user.id, monkeypatch)
    document = (await _assemble(db, test_user.id, YEAR)).model_dump(mode="json")
    policy = await derive_user_framework_policy_result(
        db,
        test_user.id,
        framework_id=FRAMEWORK,
        report_period_start=date(2026, 1, 1),
        report_period_end=date(2026, 12, 31),
        as_of_date=date(2026, 12, 31),
    )
    assert document["framework_policy"] == _json(policy.model_dump(mode="json"))
    expected = document["framework_policy"]["decisions"]
    assert len(expected) > 1000

    query = {"framework_id": FRAMEWORK.value, **{key: YEAR[key] for key in ("start_date", "end_date", "as_of_date")}}
    decisions, total = await _all_pages(
        client, "/reports/package/policy-decisions", query, limit=500, item_key="decisions"
    )
    assert total == len(expected)
    assert decisions == expected
    # A small page follows limit and offset.
    small = await client.get("/reports/package/policy-decisions", params={**query, "limit": 7, "offset": 13})
    assert small.status_code == 200, small.text
    assert small.json()["total"] == len(expected)
    assert small.json()["decisions"] == expected[13:20]
    past_end = await client.get("/reports/package/policy-decisions", params={**query, "offset": len(expected) + 5})
    assert past_end.status_code == 200, past_end.text
    assert past_end.json()["decisions"] == []


async def test_AC_reporting_package_traceability_11_cash_flow_event_pages_equal_snapshot(
    client, db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-reporting.package-traceability.11: GET /reports/package/cash-flow-events returns, page
    by page, every lineage record of the complete cash flow on exactly one line, in document
    order. The ids of the lines are the ids of the preview. The cash flow equals the output of
    ``generate_cash_flow`` for the statement cash accounts of the package."""
    bank = await _seed_year_of_reviewed_statements(db, test_user.id, monkeypatch)
    cash_flow = (await _assemble(db, test_user.id, YEAR)).model_dump(mode="json")["sections"]["cash_flow"]
    oracle = CashFlowResponse.model_validate(
        await generate_cash_flow(
            db,
            test_user.id,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            currency="SGD",
            cash_account_ids=frozenset({bank.id}),
        )
    ).model_dump(mode="json")
    assert cash_flow == oracle
    assert len(cash_flow["event_lineage"]) > 1000

    query = {key: YEAR[key] for key in ("start_date", "end_date", "as_of_date", "currency")}
    preview = (await client.get("/reports/package", params=query)).json()["sections"]["cash_flow"]
    await _assert_event_pages_equal_lineage(client, query, preview, cash_flow)


async def test_AC_reporting_package_traceability_11_snapshot_keeps_the_complete_lists(
    client, db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-reporting.package-traceability.10 and .11: a stored snapshot keeps every policy decision, every
    cash-flow item and every lineage record. The pages of the preview equal the stored lists."""
    await _seed_ready(db, test_user.id, monkeypatch)
    period = {**JUNE, "framework_id": FRAMEWORK.value}
    generated = await client.post("/reports/package/generate", json=period)
    assert generated.status_code == 200, generated.text
    stored = (await client.get(f"/reports/package/snapshots/{generated.json()['id']}")).json()["document"]
    assert stored["lifecycle"] == "frozen"

    decisions = stored["framework_policy"]["decisions"]
    assert len(decisions) > package_document.PACKAGE_POLICY_PREVIEW_DECISIONS // 5
    query = {key: period[key] for key in ("framework_id", "start_date", "end_date", "as_of_date")}
    pages, total = await _all_pages(client, "/reports/package/policy-decisions", query, limit=3, item_key="decisions")
    assert (pages, total) == (decisions, len(decisions))

    cash_flow = stored["sections"]["cash_flow"]
    assert len(cash_flow["event_lineage"]) >= 2
    cash_query = {key: period[key] for key in ("start_date", "end_date", "as_of_date", "currency")}
    preview = (await client.get("/reports/package", params=cash_query)).json()["sections"]["cash_flow"]
    assert sum(line["event_count"] for section in SECTIONS for line in preview[section]) == sum(
        len(cash_flow[section]) for section in SECTIONS
    )
    await _assert_event_pages_equal_lineage(client, cash_query, preview, cash_flow)


async def test_AC_reporting_package_traceability_11_pages_reject_bad_requests(
    client, db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-reporting.package-traceability.11: an unknown cash-flow line is not found, a page above
    the shared maximum is invalid, and a reversed period is a bad request."""
    await _seed_ready(db, test_user.id, monkeypatch)
    unknown = await client.get(
        "/reports/package/cash-flow-events", params={**JUNE, "line_id": "operating-0000000000000000"}
    )
    assert unknown.status_code == 404, unknown.text
    too_big = await client.get(
        "/reports/package/cash-flow-events", params={**JUNE, "line_id": "unclassified", "limit": 501}
    )
    assert too_big.status_code == 422, too_big.text
    no_line = await client.get("/reports/package/cash-flow-events", params=JUNE)
    assert no_line.status_code == 422, no_line.text
    # A fixed line without events is an empty page, not an unknown line.
    fixed = await client.get("/reports/package/cash-flow-events", params={**JUNE, "line_id": "opening_stock"})
    assert fixed.status_code == 200, fixed.text
    assert (fixed.json()["total"], fixed.json()["events"]) == (0, [])
    decisions_too_big = await client.get("/reports/package/policy-decisions", params={**JUNE, "limit": 501})
    assert decisions_too_big.status_code == 422, decisions_too_big.text
    reversed_dates = {"start_date": "2026-07-01", "end_date": "2026-06-01"}
    for path, extra in (
        ("/reports/package", {}),
        ("/reports/package/policy-decisions", {}),
        ("/reports/package/cash-flow-events", {"line_id": "unclassified"}),
    ):
        reversed_period = await client.get(path, params={**JUNE, **reversed_dates, **extra})
        assert reversed_period.status_code == 400, (path, reversed_period.text)
        assert "start_date must be before end_date" in reversed_period.text, path
    june_policy = await client.get(
        "/reports/package/policy-decisions", params={**JUNE, "framework_id": FRAMEWORK.value}
    )
    assert june_policy.status_code == 200, june_policy.text
    assert june_policy.json()["total"] > 0


def _reverse_row_order(direction: str):
    """Order the account and journal-line rows of a query by id, ascending or descending.

    A query result that the code sorts completely gives the same result in both directions
    (#2583 S11). A page that depends on the database row order gives another page.
    """

    def _hook(state: ORMExecuteState) -> Result | None:
        statement = state.statement
        if not state.is_select or not hasattr(statement, "column_descriptions"):
            return None
        entities = {column.get("entity") for column in statement.column_descriptions}
        if not entities & {Account, JournalLine}:
            return None
        sort_entity = JournalLine if JournalLine in entities else Account
        tiebreak = sort_entity.id.asc() if direction == "asc" else sort_entity.id.desc()
        return state.invoke_statement(statement=statement.order_by(tiebreak))

    return _hook


async def test_AC_reporting_package_traceability_10_decision_order_does_not_depend_on_database_order(
    db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-reporting.package-traceability.10: each decision page is a new request, so the order of
    the decisions must not depend on the order in which the database returns accounts and journal
    lines. The decisions of one fixture keep one order in both directions."""
    await _seed_ready(db, test_user.id, monkeypatch)
    orders = []
    for direction in ("asc", "desc"):
        hook = _reverse_row_order(direction)
        event.listen(Session, "do_orm_execute", hook)
        try:
            policy = await derive_user_framework_policy_result(
                db,
                test_user.id,
                framework_id=FRAMEWORK,
                report_period_start=date(2026, 6, 1),
                report_period_end=date(2026, 6, 30),
                as_of_date=date(2026, 6, 30),
            )
        finally:
            event.remove(Session, "do_orm_execute", hook)
        orders.append([anchor.anchor_id for decision in policy.decisions for anchor in decision.evidence_anchors[:1]])

    assert len(orders[0]) > 5, orders[0]
    assert orders[0] == orders[1]
