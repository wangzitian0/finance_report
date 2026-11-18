from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.extraction import resolve_statement_contribution
from src.extraction.base.result import ExtractedPositionFact
from src.reporting.extension.package_document import PackageAssembler, _statement_section_contribution
from src.reporting.extension.report_traceability import build_personal_report_package_traceability_payload
from tests.integration.test_pdf_report_checkpoint import uploaded_pdf  # noqa: F401


@pytest.mark.parametrize(("day", "ending", "expense"), [(7, "1500", "0"), (19, "1400", "100"), (31, "1400", "100")])
async def test_midperiod_source_lineage_preserves_cutoff(
    uploaded_pdf, client, db, day: int, ending: str, expense: str
) -> None:
    cutoff = date(2026, 1, day)
    source = await resolve_statement_contribution(
        db, user_id=uploaded_pdf.user_id, statement_id=uploaded_pdf.statement_id
    )
    assert source.is_authoritative and source.effective_period_end == date(2026, 1, 31)
    period = {
        "start_date": "2026-01-01",
        "end_date": cutoff.isoformat(),
        "as_of_date": cutoff.isoformat(),
        "currency": "SGD",
    }
    doc = (await client.get("/reports/package", params=period)).json()
    secs = doc["sections"]
    assert (
        Decimal(secs["income_statement"]["total_income"]),
        Decimal(secs["income_statement"]["total_expenses"]),
        Decimal(secs["balance_sheet"]["total_assets"]),
    ) == (Decimal("500"), Decimal(expense), Decimal(ending))
    line = next(i for i in secs["traceability_appendix"]["lines"] if i["line_id"] == "income_statement.total_income")
    assert line["source_anchor"]["detail_count"] > 0
    details = (
        await client.get(
            "/reports/package/line-details",
            params={**period, "line_id": "income_statement.total_income", "anchor": "source_anchor", "limit": 500},
        )
    ).json()["details"]
    assert len(details) == line["source_anchor"]["detail_count"] and any(
        i["identifier"] == f"statement_result:{source.source_result_id}" and i["decision_id"] == str(source.decision_id)
        for i in details
    )
    manifest = (await client.get("/reports/package/manifest-entries", params={**period, "limit": 500})).json()[
        "entries"
    ]
    assert any(i["decision_id"] == str(source.decision_id) for i in manifest)
    contribs = await PackageAssembler()._contributions(
        db, user_id=uploaded_pdf.user_id, start_date=date(2026, 1, 1), end_date=cutoff, as_of_date=cutoff
    )
    stmt = next(i for i in contribs if i.contribution_type == "statement_source")
    assert ("balance_sheet" in stmt.section_ids) == (day == 31) and stmt.payload == source


async def test_empty_source_anchor_and_future_movements(uploaded_pdf, db) -> None:
    payload = await build_personal_report_package_traceability_payload(contributions=())
    line = next(i for i in payload["lines"] if i["line_id"] == "income_statement.total_income")
    assert (line["source_anchor"]["state"], line["source_anchor"]["unavailable_reason"]) == (
        "unavailable",
        "no_selected_source_contribution",
    )
    contribs = await PackageAssembler()._contributions(
        db,
        user_id=uploaded_pdf.user_id,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 4),
        as_of_date=date(2026, 1, 4),
    )
    assert not any(i.contribution_type == "statement_source" for i in contribs)


@pytest.mark.parametrize(
    ("source_end", "stock_allowed"), [(None, False), (date(2026, 1, 31), False), (date(2026, 1, 7), True)]
)
def test_future_or_undated_positions_are_not_stock_evidence(source_end: date | None, stock_allowed: bool) -> None:
    source = SimpleNamespace(
        source_result=SimpleNamespace(
            balances=(),
            transactions=(),
            positions=(ExtractedPositionFact("p1", "TEST", Decimal("1"), Decimal("9999"), "SGD", None),),
        ),
        effective_period_start=date(2026, 1, 1),
        effective_period_end=source_end,
        input_refs=(),
        statement_id=uuid4(),
        state="unproven",
        decision=None,
        reason_code="source_decision_missing",
    )
    contrib = _statement_section_contribution(
        source, start_date=date(2026, 1, 1), end_date=date(2026, 1, 7), as_of_date=date(2026, 1, 7)
    )
    assert (
        ("balance_sheet" in contrib.section_ids),
        ("investment_performance" in contrib.section_ids),
        "income_statement" in contrib.section_ids,
        contrib.is_authoritative,
    ) == (stock_allowed, stock_allowed, False, False)
