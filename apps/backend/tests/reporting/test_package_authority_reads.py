from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from uuid import UUID

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import TraceScope, current_authoritative_trace_decision_projection
from src.reporting import PackageAssembler, current_package_readiness
from src.schemas.reporting import PersonalReportingFrameworkId
from tests.reporting._report_fixtures import JUNE_PERIOD, seed_reviewed_statement

PROJECTION_MARKER = "invalid_trace_records"
PROJECTION_RUN_BUDGET = 2


@contextmanager
def _projection_reads(db_engine, user_id: UUID) -> Iterator[tuple[list[int], list[tuple[int, str]]]]:
    rows: list[int] = []
    captured: list[tuple[int, str]] = []
    user_token = str(user_id)

    def _record(conn, cursor, statement, parameters, context, executemany):
        if PROJECTION_MARKER in statement:
            param_text = repr(parameters)
            captured.append((cursor.rowcount, param_text[:160]))
            if user_token in param_text:
                rows.append(cursor.rowcount)

    event.listen(db_engine.sync_engine, "after_cursor_execute", _record)
    try:
        yield rows, captured
    finally:
        event.remove(db_engine.sync_engine, "after_cursor_execute", _record)


async def test_AC_reporting_package_document_15_one_evaluation_reads_the_authority_projection_at_most_twice(
    client, db: AsyncSession, db_engine, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed_reviewed_statement(db, test_user.id, monkeypatch)
    reads: dict[str, tuple[list[int], list[tuple[int, str]]]] = {}
    for label, path, extra in (
        ("GET /reports/package", "/reports/package", {}),
        (
            "GET /reports/package/line-details",
            "/reports/package/line-details",
            {"line_id": "balance_sheet.total_assets", "anchor": "ledger_anchor"},
        ),
        ("GET /reports/package/manifest-entries", "/reports/package/manifest-entries", {}),
    ):
        with _projection_reads(db_engine, test_user.id) as pair:
            resp = await client.get(path, params={**JUNE_PERIOD, **extra})
        assert resp.status_code == 200, (label, resp.text)
        reads[label] = pair
    with _projection_reads(db_engine, test_user.id) as pair:
        readiness = await current_package_readiness(
            db, user_id=test_user.id, as_of_date=date(2026, 6, 30), base_currency="SGD"
        )
    reads["current_package_readiness"] = pair
    proj = current_authoritative_trace_decision_projection(TraceScope.tenant(test_user.id)).subquery()
    dec_cnt = len((await db.execute(select(proj.c.decision_id))).all())
    assert readiness.input_coverage.manifest_decision_count > 0
    for label, (rows, captured) in reads.items():
        assert 1 <= len(rows) <= PROJECTION_RUN_BUDGET and max(rows) <= dec_cnt, (label, rows, captured)


async def test_AC_reporting_package_document_15_first_evaluation_sees_the_decisions_it_writes(
    db: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    await seed_reviewed_statement(db, test_user.id, monkeypatch)
    proj = current_authoritative_trace_decision_projection(TraceScope.tenant(test_user.id)).subquery()
    before = set((await db.execute(select(proj.c.decision_id))).scalars())
    period = {
        "framework_id": PersonalReportingFrameworkId.US_GAAP_LIKE,
        "start_date": date(2026, 6, 1),
        "end_date": date(2026, 6, 30),
        "as_of_date": date(2026, 6, 30),
        "currency": "SGD",
    }
    first = await PackageAssembler().assemble(db, user_id=test_user.id, **period)
    written = set((await db.execute(select(proj.c.decision_id))).scalars()) - before
    second = await PackageAssembler().assemble(db, user_id=test_user.id, **period)
    assert len(written) == 1 and written <= {e.decision_id for e in first.input_manifest}
    assert [e.model_dump(mode="json") for e in first.input_manifest] == [
        e.model_dump(mode="json") for e in second.input_manifest
    ]
    assert first.readiness.model_dump(mode="json") == second.readiness.model_dump(mode="json")
