"""The package preview stays bounded, and its evidence pages equal a frozen snapshot (#2583 S8).

Before #2583 S8, ``GET /reports/package`` returned every traceability detail and every input
manifest entry: 3.9 MB for one year of reviewed statements. The preview now carries per-line
counts. The details and the manifest entries load page by page from two endpoints. The
endpoints read the same contribution set and the same builder as a frozen snapshot.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, insert, inspect as sa_inspect, text
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import ORMExecuteState, Session

from src.audit import (
    JournalEntrySourceType,
    TraceRecord,
    TraceResult,
    TraceScope,
    TraceTargetClass,
    VersionedTraceRef,
)
from src.audit.extension.trace_repository import _row_from_record
from src.audit.orm import TraceRecordParentRow, TraceRecordRow
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryAuthorityState,
    JournalEntryStatus,
    JournalLine,
    initialize_opening_positions,
)
from src.ledger.base.decision_anchor import journal_command_target
from src.ledger.extension.anchored_posting import SystemJournalCommandPolicy
from src.ledger.orm.opening_position import OpeningPositionRecord
from src.pricing import ManualValuationComponentType, ManualValuationLiquidityClass
from src.pricing.orm.manual_valuation import ManualValuationSnapshot
from src.pricing.orm.market_data import StockPrice
from src.reporting import PackageAssembler
from src.reporting.extension.package_document import _traceability_appendix
from src.schemas.reporting import PersonalReportingFrameworkId, PersonalReportPackageTraceabilityAnchorName
from tests.portfolio.test_portfolio_router import _make_atomic_position, _make_managed_position
from tests.reporting.test_package_readiness_path import _seed_ready

YEAR_ENTRY_COUNT = 1000
# The preview of one year of activity must stay below this size (#2583 S8). Before S8 the
# preview of the fixture below was 4.6 MB, and 3.9 MB for the #2583 probe.
PREVIEW_BYTE_BUDGET = 300_000
# SQL statements of ``GET /reports/package`` for the fixture below on main before S8. The preview
# must not issue more statements than that.
PREVIEW_SQL_BUDGET = 86
YEAR = {"start_date": "2026-01-01", "end_date": "2026-12-31", "as_of_date": "2026-12-31", "currency": "SGD"}
JUNE = {"start_date": "2026-06-01", "end_date": "2026-06-30", "as_of_date": "2026-06-30", "currency": "SGD"}
ANCHORS = ("source_anchor", "ledger_anchor")


async def _seed_year_of_anchored_entries(db: AsyncSession, user_id: UUID) -> None:
    """Write one year of system-posted entries, each anchored to its own current decision.

    ``post_entry`` writes the same rows one entry at a time (about 0.3 s per entry). This
    fixture builds the same observation and decision with ``TraceRecord`` and inserts the rows
    in bulk. Half of the entries are income and half are expenses, so the line filters of the
    appendix apply.
    """
    bank = Account(user_id=user_id, name="Bank", code="1001", type=AccountType.ASSET, currency="SGD")
    salary = Account(user_id=user_id, name="Salary", code="4001", type=AccountType.INCOME, currency="SGD")
    groceries = Account(user_id=user_id, name="Groceries", code="5001", type=AccountType.EXPENSE, currency="SGD")
    db.add_all([bank, salary, groceries])
    await db.flush()
    policy = SystemJournalCommandPolicy()
    scope = TraceScope.tenant(user_id)
    now = datetime.now(UTC)
    trace_rows = []
    parent_rows = []
    entry_rows = []
    line_rows = []
    for index in range(YEAR_ENTRY_COUNT):
        entry_date = date(2026, 1, 1) + timedelta(days=index % 365)
        memo = f"year-scale entry {index}"
        income = index % 2 == 0
        amount = Decimal("3000.00") if income else Decimal(f"{index % 90 + 10}.25")
        debit, credit = (bank.id, salary.id) if income else (groceries.id, bank.id)
        lines_data = [
            {"account_id": debit, "direction": Direction.DEBIT, "amount": amount, "currency": "SGD"},
            {"account_id": credit, "direction": Direction.CREDIT, "amount": amount, "currency": "SGD"},
        ]
        target = journal_command_target(
            entry_date=entry_date,
            memo=memo,
            lines_data=lines_data,
            base_currency="SGD",
            source_identity=f"ledger-system:year-scale:{index}",
        )
        observation = TraceRecord.observation(
            scope=scope,
            target=target,
            target_class=TraceTargetClass.FINANCIAL,
            assertion=VersionedTraceRef("ledger_system_input", "year-scale", "1"),
            authority=policy.authority,
            result=TraceResult.PASS,
            execution_id=f"ledger-system:{target.id}:{target.version}",
            evidence_manifest_digest=target.version,
            occurred_at=now,
            score=None,
            reason_code="ledger_system_command_materialized",
        )
        decision = TraceRecord.decision(
            scope=scope,
            target=target,
            policy=policy,
            execution_id=observation.execution_id,
            occurred_at=now,
            parents=(observation,),
        )
        trace_rows.extend((_row_from_record(observation), _row_from_record(decision)))
        parent_rows.append(
            {
                "scope_kind": scope.kind,
                "scope_id": scope.id,
                "record_id": decision.record_id,
                "parent_id": observation.record_id,
            }
        )
        entry_id = uuid4()
        entry_rows.append(
            {
                "id": entry_id,
                "user_id": user_id,
                "entry_date": entry_date,
                "memo": memo,
                "source_type": JournalEntrySourceType.SYSTEM,
                "source_id": None,
                "decision_anchor_id": decision.record_id,
                "decision_authority_state": JournalEntryAuthorityState.ANCHORED,
                "base_currency": "SGD",
                "status": JournalEntryStatus.POSTED,
                "void_reason": None,
                "void_reversal_entry_id": None,
                "created_at": now,
                "updated_at": now,
            }
        )
        for line_no, line in enumerate(lines_data):
            line_rows.append(
                {
                    "id": uuid4(),
                    "journal_entry_id": entry_id,
                    "line_no": line_no,
                    "account_id": line["account_id"],
                    "direction": line["direction"],
                    "amount": line["amount"],
                    "currency": "SGD",
                    "fx_rate": None,
                    "event_type": None,
                    "tags": None,
                    "created_at": now,
                    "updated_at": now,
                }
            )
    # One executemany through the table, without the ORM unit of work. (An ORM-enabled bulk
    # insert of these rows sends one INSERT per row.)
    trace_columns = [
        (attribute.key, attribute.columns[0].name) for attribute in sa_inspect(TraceRecordRow).column_attrs
    ]
    await db.execute(
        insert(TraceRecordRow.__table__),
        [{column: getattr(row, key) for key, column in trace_columns} for row in trace_rows],
    )
    await db.execute(insert(TraceRecordParentRow), parent_rows)
    await db.execute(insert(JournalEntry), entry_rows)
    await db.execute(insert(JournalLine), line_rows)
    # A new test database has no table statistics, so the deferred link triggers that run at
    # commit plan sequential scans: 5.3 s for these 3000 rows instead of 1.3 s. Production
    # tables carry statistics. The fixture gives the planner the same view.
    await db.execute(text("ANALYZE trace_records, trace_record_parents"))
    await db.commit()


async def _seed_reviewed_statement(db: AsyncSession, user_id: UUID, monkeypatch: pytest.MonkeyPatch) -> StockPrice:
    """A reviewed bank statement, opening positions, a manual valuation and a market-priced holding.

    The fixture reaches every detail renderer and the market contribution that the investment
    schedule selects. Return the market price that the schedule renders.
    """
    await _seed_ready(db, user_id, monkeypatch)
    brokerage = Account(user_id=user_id, name="Brokerage", type=AccountType.ASSET, currency="SGD")
    db.add(brokerage)
    await db.flush()
    stock_price = StockPrice(
        symbol="AAPL",
        price=Decimal("125.05"),
        currency="SGD",
        price_date=date(2026, 6, 30),
        source="recorded-provider",
    )
    db.add_all(
        [
            ManualValuationSnapshot(
                user_id=user_id,
                component_type=ManualValuationComponentType.PROPERTY_VALUE,
                liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
                value=Decimal("250000.00"),
                currency="SGD",
                as_of_date=date(2026, 6, 20),
                source="Property appraisal",
            ),
            _make_managed_position(
                user_id,
                brokerage.id,
                "AAPL",
                quantity=Decimal("10"),
                cost_basis=Decimal("1000.00"),
                acquisition_date=date(2026, 6, 2),
            ),
            _make_atomic_position(
                user_id,
                "AAPL",
                broker="Brokerage",
                quantity=Decimal("10"),
                market_value=Decimal("1200.00"),
                snapshot_date=date(2026, 6, 30),
                dedup_hash="s8-aapl-2026-06-30",
            ),
            stock_price,
        ]
    )
    await db.commit()
    return stock_price


@contextmanager
def _counting_statements(db_engine) -> Iterator[dict[str, int]]:
    """Count the SQL statements of the block. The listener is removed after the block."""
    counter = {"statements": 0}

    def _count(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        counter["statements"] += 1

    event.listen(db_engine.sync_engine, "before_cursor_execute", _count)
    try:
        yield counter
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _count)


async def _all_pages(client, path: str, params: dict[str, str], *, limit: int, item_key: str) -> tuple[list, int]:
    """Read every page of one evidence list. Return the items and the total of the first page."""
    items: list = []
    offset = 0
    total = None
    while True:
        response = await client.get(path, params={**params, "limit": limit, "offset": offset})
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["limit"] == limit
        assert page["offset"] == offset
        if total is None:
            total = page["total"]
        assert page["total"] == total
        assert len(page[item_key]) == min(limit, max(total - offset, 0))
        items.extend(page[item_key])
        offset += limit
        if offset >= total:
            return items, total


async def test_AC_reporting_package_traceability_7_year_scale_preview_is_bounded(
    client, db: AsyncSession, db_engine, test_user
) -> None:
    """AC-reporting.package-traceability.7: one year of anchored activity (1000 entries) gives a
    preview below 300 KB, with no more SQL statements than before #2583 S8. The preview has
    per-line counts and no details, identifiers or manifest entries. Its readiness equals the
    readiness of the full document. At the maximum page size, the pages of the largest anchor
    and of the manifest equal the lists of the full document."""
    await _seed_year_of_anchored_entries(db, test_user.id)
    with _counting_statements(db_engine) as counter:
        response = await client.get("/reports/package", params=YEAR)

    assert response.status_code == 200, response.text
    statements = counter["statements"]
    assert len(response.content) < PREVIEW_BYTE_BUDGET, (len(response.content), statements)
    assert statements <= PREVIEW_SQL_BUDGET, statements
    preview = response.json()
    assert preview["lifecycle"] == "preview"
    assert "input_manifest" not in preview
    document = await PackageAssembler().assemble(
        db,
        user_id=test_user.id,
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        as_of_date=date(2026, 12, 31),
        currency="SGD",
    )
    assert preview["readiness"] == document.readiness.model_dump(mode="json")
    # Every entry has its own current decision, so the manifest of the full document is large.
    assert document.readiness.input_coverage.manifest_decision_count == YEAR_ENTRY_COUNT
    assert len(document.input_manifest) == YEAR_ENTRY_COUNT
    full_lines = {line.line_id: line for line in document.sections.traceability_appendix.lines}
    preview_lines = preview["sections"]["traceability_appendix"]["lines"]
    assert [line["line_id"] for line in preview_lines] == list(full_lines)
    detail_total = 0
    for line in preview_lines:
        full_line = full_lines[line["line_id"]]
        assert line["anchor_count"] == full_line.anchor_count
        assert line["blocker_codes"] == full_line.blocker_codes
        for anchor_name in ANCHORS:
            anchor = line[anchor_name]
            assert "details" not in anchor
            assert "identifiers" not in anchor
            full_anchor = getattr(full_line, anchor_name)
            assert anchor["state"] == full_anchor.state
            assert anchor["detail_count"] == len(full_anchor.details) == len(full_anchor.identifiers)
            detail_total += anchor["detail_count"]
    # The full appendix has at least one ledger detail per journal line of the year.
    assert detail_total >= 2 * YEAR_ENTRY_COUNT

    # Each page reads the contribution set once. At year scale the test reads the last page of the
    # largest anchor and of the manifest; the reviewed-statement test below pages every list.
    full_json = document.model_dump(mode="json")
    assets_ledger = next(
        line["ledger_anchor"]["details"]
        for line in full_json["sections"]["traceability_appendix"]["lines"]
        if line["line_id"] == "balance_sheet.total_assets"
    )
    assert len(assets_ledger) == 2 * YEAR_ENTRY_COUNT
    last_details = await client.get(
        "/reports/package/line-details",
        params={
            **YEAR,
            "line_id": "balance_sheet.total_assets",
            "anchor": "ledger_anchor",
            "limit": 500,
            "offset": 1500,
        },
    )
    assert last_details.status_code == 200, last_details.text
    assert last_details.json()["total"] == len(assets_ledger)
    assert last_details.json()["details"] == assets_ledger[1500:]
    last_entries = await client.get("/reports/package/manifest-entries", params={**YEAR, "limit": 500, "offset": 500})
    assert last_entries.status_code == 200, last_entries.text
    assert last_entries.json()["total"] == YEAR_ENTRY_COUNT
    assert last_entries.json()["entries"] == full_json["input_manifest"][500:]


async def test_AC_reporting_package_traceability_8_evidence_pages_equal_snapshot(
    client, db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-reporting.package-traceability.8: the details that ``GET /reports/package/line-details``
    returns page by page equal the details of a frozen snapshot of the same data, in the same
    order. ``GET /reports/package/manifest-entries`` returns the input manifest of that snapshot.
    The preview counts equal the snapshot lists.

    Each page request reads the contribution set again. So the test compares every anchor with
    the builder output that the page slices (one read), and reads through the API the largest
    anchor two details at a time, one anchor per detail kind, and the manifest three at a time."""
    stock_price = await _seed_reviewed_statement(db, test_user.id, monkeypatch)
    market_identifier = f"pricing_observation:{stock_price.id}"
    period = JUNE

    generated = await client.post(
        "/reports/package/generate", json={**period, "framework_id": PersonalReportingFrameworkId.US_GAAP_LIKE.value}
    )
    assert generated.status_code == 200, generated.text
    snapshot = generated.json()["document"]
    preview_response = await client.get("/reports/package", params=period)
    assert preview_response.status_code == 200, preview_response.text
    preview_lines = {
        line["line_id"]: line for line in preview_response.json()["sections"]["traceability_appendix"]["lines"]
    }

    anchors = [
        (line["line_id"], anchor_name, line[anchor_name]["details"])
        for line in snapshot["sections"]["traceability_appendix"]["lines"]
        for anchor_name in ANCHORS
    ]
    # Every anchor: the builder output that the line-details page slices equals the snapshot.
    # Read the rows from the database, as a request does, not from the fixture objects.
    user_id = test_user.id
    db.expire_all()
    evidence = await PackageAssembler()._evidence_contributions(
        db,
        user_id=user_id,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 30),
        as_of_date=date(2026, 6, 30),
        currency="SGD",
    )
    built = {
        line["line_id"]: line for line in (await _traceability_appendix(evidence)).model_dump(mode="json")["lines"]
    }
    for line_id, anchor_name, expected in anchors:
        assert preview_lines[line_id][anchor_name]["detail_count"] == len(expected), (line_id, anchor_name)
        assert built[line_id][anchor_name]["details"] == expected, (line_id, anchor_name)

    # Through the API: the largest anchor two details at a time, and one anchor per detail kind.
    largest = max(anchors, key=lambda item: len(item[2]))
    assert len(largest[2]) > 2
    paged = [largest]
    for kind in sorted({detail["source_kind"] for _, _, details in anchors for detail in details}):
        if not any(detail["source_kind"] == kind for _, _, details in paged for detail in details):
            paged.append(next(item for item in anchors if any(d["source_kind"] == kind for d in item[2])))
    detail_kinds = set()
    for line_id, anchor_name, expected in paged:
        limit = 2 if (line_id, anchor_name) == largest[:2] else 500
        details, total = await _all_pages(
            client,
            "/reports/package/line-details",
            {**period, "line_id": line_id, "anchor": anchor_name},
            limit=limit,
            item_key="details",
        )
        assert total == len(expected), (line_id, anchor_name)
        assert details == expected, (line_id, anchor_name)
        detail_kinds.update(detail["source_kind"] for detail in expected)

    entries, total = await _all_pages(client, "/reports/package/manifest-entries", period, limit=3, item_key="entries")
    assert total == len(snapshot["input_manifest"])
    assert entries == snapshot["input_manifest"]
    assert total > 3
    # The market price that the investment schedule renders is a package contribution.
    market_line = next(
        line
        for line in snapshot["sections"]["traceability_appendix"]["lines"]
        if line["line_id"] == "investment_performance.market_value"
    )
    assert market_identifier in {detail["identifier"] for detail in market_line["source_anchor"]["details"]}
    # The fixture reaches every detail renderer, so the equality covers each of them.
    assert detail_kinds == {
        "journal_line",
        "opening_position",
        "package_contract",
        "pricing_valuation_observation",
        "statement_extraction_result",
    }


async def test_AC_reporting_package_traceability_8_line_details_reject_unknown_lines(
    client, db: AsyncSession, test_user
) -> None:
    """AC-reporting.package-traceability.8: an unknown line is not found, an unknown anchor and a
    page above the shared maximum are invalid."""
    unknown = await client.get(
        "/reports/package/line-details", params={**JUNE, "line_id": "x.y", "anchor": "ledger_anchor"}
    )
    assert unknown.status_code == 404, unknown.text
    bad_anchor = await client.get(
        "/reports/package/line-details",
        params={**JUNE, "line_id": "balance_sheet.total_assets", "anchor": "other_anchor"},
    )
    assert bad_anchor.status_code == 422, bad_anchor.text
    too_big = await client.get("/reports/package/manifest-entries", params={**JUNE, "limit": 501})
    assert too_big.status_code == 422, too_big.text
    static_note = await client.get(
        "/reports/package/line-details",
        params={**JUNE, "line_id": "notes.non_compliance_statement", "anchor": "source_anchor"},
    )
    assert static_note.status_code == 200, static_note.text
    assert static_note.json()["total"] == 1
    assert static_note.json()["details"][0]["source_kind"] == "package_contract"
    past_end = await client.get(
        "/reports/package/line-details",
        params={**JUNE, "line_id": "notes.non_compliance_statement", "anchor": "source_anchor", "offset": 5},
    )
    assert past_end.status_code == 200, past_end.text
    assert past_end.json()["total"] == 1
    assert past_end.json()["details"] == []


def _equal_rank_order(direction: str):
    """Order the opening-position rows that a query ranks equal by their id, ascending or descending.

    A query that sorts its rows completely gives the same result in both directions. A query
    that leaves ties to the database gives a different order (#2583 S8).
    """

    def _hook(state: ORMExecuteState) -> Result | None:
        statement = state.statement
        if not state.is_select or not hasattr(statement, "column_descriptions"):
            return None
        entities = {column.get("entity") for column in statement.column_descriptions}
        if OpeningPositionRecord not in entities:
            return None
        tiebreak = OpeningPositionRecord.id.asc() if direction == "asc" else OpeningPositionRecord.id.desc()
        return state.invoke_statement(statement=statement.order_by(tiebreak))

    return _hook


async def test_AC_reporting_package_traceability_8_detail_order_does_not_depend_on_database_tie_order(
    db: AsyncSession, test_user
) -> None:
    """AC-reporting.package-traceability.8: each evidence page is a new request, so the detail
    order must not depend on the order of rows that the database ranks equal. Four opening
    positions have the same version; their details keep one order."""
    accounts = [
        Account(user_id=test_user.id, name=f"Cash {index}", type=AccountType.ASSET, currency="SGD")
        for index in range(4)
    ]
    db.add_all(accounts)
    await db.flush()
    await initialize_opening_positions(
        db,
        test_user.id,
        entry_date=date(2026, 1, 1),
        balances={account.id: Decimal(f"{index + 1}000.00") for index, account in enumerate(accounts)},
        currency="SGD",
    )
    await db.commit()

    orders = []
    for direction in ("asc", "desc"):
        hook = _equal_rank_order(direction)
        event.listen(Session, "do_orm_execute", hook)
        try:
            details = await PackageAssembler().line_details(
                db,
                user_id=test_user.id,
                start_date=date(2026, 6, 1),
                end_date=date(2026, 6, 30),
                as_of_date=date(2026, 6, 30),
                currency="SGD",
                line_id="balance_sheet.total_assets",
                anchor=PersonalReportPackageTraceabilityAnchorName.LEDGER,
            )
        finally:
            event.remove(Session, "do_orm_execute", hook)
        assert details is not None
        orders.append([detail["identifier"] for detail in details])

    opening = [identifier for identifier in orders[0] if str(identifier).startswith("opening_position:")]
    assert len(opening) == 4, orders[0]
    assert orders[0] == orders[1]
