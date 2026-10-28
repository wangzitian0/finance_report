"""One package evaluation reads the current-authority projection at most twice (#2602).

Before #2602 one ``GET /reports/package`` ran the current-authority projection 8 times: the
three opening-position reads (package contributions, balance-sheet trust signals, cash flow)
ran it twice each, and the journal contributions and the input manifest ran it once each.
At 960 statement transactions the 8 runs returned 14,469 rows; the user had 3,864 current
decisions. The count of runs does not depend on the data volume, so this test uses a small
fixture that reaches every contribution kind.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import TraceScope, current_authoritative_trace_decision_projection
from src.reporting import PackageAssembler, current_package_readiness
from src.schemas.reporting import PersonalReportingFrameworkId
from tests.reporting.test_package_preview_payload import JUNE, _seed_reviewed_statement

PROJECTION_MARKER = "invalid_trace_records"
# The current-authority projection may run at most this many times per package evaluation.
PROJECTION_RUN_BUDGET = 2


@contextmanager
def _projection_reads(db_engine) -> Iterator[list[int]]:
    """Collect the row count of each current-authority projection statement of the block."""
    rows: list[int] = []

    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ARG001
        if PROJECTION_MARKER in statement:
            rows.append(cursor.rowcount)

    event.listen(db_engine.sync_engine, "after_cursor_execute", _record)
    try:
        yield rows
    finally:
        event.remove(db_engine.sync_engine, "after_cursor_execute", _record)


async def test_AC_reporting_package_document_15_one_evaluation_reads_the_authority_projection_at_most_twice(
    client, db: AsyncSession, db_engine, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-reporting.package-document.15: one package evaluation runs the current-authority
    projection at most 2 times. This applies to ``GET /reports/package``,
    ``current_package_readiness``, the two evidence pages and the cash-flow events page. One run returns each current
    decision of the user at most once. The fixture has a reviewed bank statement, opening
    positions, a manual valuation and a market-priced holding. Before #2602 the preview ran
    the projection 8 times."""
    await _seed_reviewed_statement(db, test_user.id, monkeypatch)

    evaluations = {
        "GET /reports/package": lambda: client.get("/reports/package", params=JUNE),
        "GET /reports/package/line-details": lambda: client.get(
            "/reports/package/line-details",
            params={**JUNE, "line_id": "balance_sheet.total_assets", "anchor": "ledger_anchor"},
        ),
        "GET /reports/package/manifest-entries": lambda: client.get("/reports/package/manifest-entries", params=JUNE),
        "GET /reports/package/cash-flow-events": lambda: client.get(
            "/reports/package/cash-flow-events", params={**JUNE, "line_id": "unclassified"}
        ),
    }
    reads: dict[str, list[int]] = {}
    for label, request in evaluations.items():
        with _projection_reads(db_engine) as rows:
            response = await request()
        assert response.status_code == 200, (label, response.text)
        reads[label] = rows
    with _projection_reads(db_engine) as rows:
        readiness = await current_package_readiness(db, user_id=test_user.id, as_of_date=date(2026, 6, 30))
    reads["current_package_readiness"] = rows
    # The first evaluation writes the decision of the selected market price, so count after it.
    projection = current_authoritative_trace_decision_projection(TraceScope.tenant(test_user.id)).subquery()
    decision_count = len((await db.execute(select(projection.c.decision_id))).all())

    # The fixture reaches the manifest, so each path has authority reads to share.
    assert readiness.input_coverage.manifest_decision_count > 0
    for label, rows in reads.items():
        assert 1 <= len(rows) <= PROJECTION_RUN_BUDGET, (label, rows)
        # A run returns each current decision at most once: no row per journal line.
        assert max(rows) <= decision_count, (label, rows, decision_count)


async def test_AC_reporting_package_document_15_first_evaluation_sees_the_decisions_it_writes(
    db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-reporting.package-document.15: the first evaluation after a new market price writes the
    decision of that price selection. Its input manifest and readiness then equal those of the
    next evaluation, so the shared authority read never hides a decision that the evaluation
    writes."""
    await _seed_reviewed_statement(db, test_user.id, monkeypatch)
    projection = current_authoritative_trace_decision_projection(TraceScope.tenant(test_user.id)).subquery()
    before = set((await db.execute(select(projection.c.decision_id))).scalars())

    period = {
        "framework_id": PersonalReportingFrameworkId.US_GAAP_LIKE,
        "start_date": date(2026, 6, 1),
        "end_date": date(2026, 6, 30),
        "as_of_date": date(2026, 6, 30),
        "currency": "SGD",
    }
    first = await PackageAssembler().assemble(db, user_id=test_user.id, **period)
    written = set((await db.execute(select(projection.c.decision_id))).scalars()) - before
    second = await PackageAssembler().assemble(db, user_id=test_user.id, **period)

    assert len(written) == 1, written
    assert written <= {entry.decision_id for entry in first.input_manifest}
    assert [entry.model_dump(mode="json") for entry in first.input_manifest] == [
        entry.model_dump(mode="json") for entry in second.input_manifest
    ]
    assert first.readiness.model_dump(mode="json") == second.readiness.model_dump(mode="json")
