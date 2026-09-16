"""Real persisted source authority remains visible across a statement cutoff."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.extraction import resolve_statement_contribution
from src.reporting.extension.package_document import PackageAssembler, _statement_section_contribution
from tests.integration.test_pdf_report_checkpoint import uploaded_pdf  # noqa: F401


@pytest.mark.parametrize("day,ending,expense", [(7, "1500", "0"), (19, "1400", "100"), (31, "1400", "100")])
async def test_midperiod_source_lineage_preserves_cutoff(uploaded_pdf, client, db, day, ending, expense):  # noqa: F811
    """AC-reporting.report-integrity.8: movement lineage never grants future stock."""
    cutoff = date(2026, 1, day)
    source = await resolve_statement_contribution(
        db, user_id=uploaded_pdf.user_id, statement_id=uploaded_pdf.statement_id
    )
    assert source.is_authoritative
    assert source.effective_period_end == date(2026, 1, 31)
    response = await client.get(
        "/reports/package",
        params={
            "start_date": "2026-01-01",
            "end_date": cutoff.isoformat(),
            "as_of_date": cutoff.isoformat(),
            "currency": "SGD",
        },
    )
    assert response.status_code == 200, response.text
    document = response.json()
    sections = document["sections"]
    income = sections["income_statement"]
    assert Decimal(income["total_income"]) == Decimal("500")
    assert Decimal(income["total_expenses"]) == Decimal(expense)
    assert Decimal(sections["balance_sheet"]["total_assets"]) == Decimal(ending)
    line = next(
        item
        for item in sections["traceability_appendix"]["lines"]
        if item["line_id"] == "income_statement.total_income"
    )
    details = line["source_anchor"]["details"]
    assert details, "Included source-backed income requires concrete source authority"
    assert any(
        item["identifier"] == f"statement_result:{source.source_result_id}"
        and item["decision_id"] == str(source.decision_id)
        for item in details
    )
    assert any(item["decision_id"] == str(source.decision_id) for item in document["input_manifest"])
    contributions = await PackageAssembler()._contributions(
        db, user_id=uploaded_pdf.user_id, start_date=date(2026, 1, 1), end_date=cutoff, as_of_date=cutoff
    )
    statement = next(item for item in contributions if item.contribution_type == "statement_source")
    assert ("balance_sheet" in statement.section_ids) == (day == 31)
    assert statement.payload == source


async def test_empty_source_anchor_is_unavailable():
    """AC-reporting.report-integrity.8: template metadata is not source evidence."""
    from src.reporting.extension.report_traceability import build_personal_report_package_traceability_payload

    payload = await build_personal_report_package_traceability_payload(contributions=())
    line = next(item for item in payload["lines"] if item["line_id"] == "income_statement.total_income")
    assert line["source_anchor"]["state"] == "unavailable"
    assert line["source_anchor"]["unavailable_reason"] == "no_selected_source_contribution"


async def test_future_movements_do_not_supply_current_source_evidence(uploaded_pdf, db):  # noqa: F811
    """AC-reporting.report-integrity.8: a future fact cannot enter today's manifest."""
    contributions = await PackageAssembler()._contributions(
        db,
        user_id=uploaded_pdf.user_id,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 4),
        as_of_date=date(2026, 1, 4),
    )
    assert not any(item.contribution_type == "statement_source" for item in contributions)


@pytest.mark.parametrize(
    "source_end,stock_allowed", [(None, False), (date(2026, 1, 31), False), (date(2026, 1, 7), True)]
)
def test_future_or_undated_positions_are_not_stock_evidence(source_end, stock_allowed):
    """AC-reporting.report-integrity.8: stock sections require a completed period."""
    from src.extraction.base.result import ExtractedPositionFact

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
    contribution = _statement_section_contribution(
        source, start_date=date(2026, 1, 1), end_date=date(2026, 1, 7), as_of_date=date(2026, 1, 7)
    )
    assert ("balance_sheet" in contribution.section_ids) == stock_allowed
    assert ("investment_performance" in contribution.section_ids) == stock_allowed
    assert "income_statement" not in contribution.section_ids
    assert not contribution.is_authoritative
