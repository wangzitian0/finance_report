from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from playwright.async_api import Page

from tests.e2e._journey_helpers import (
    PARSING_TIMEOUT_MS,
    RecordedRequest,
    api_url,
    assert_default_ai_settings,
    assert_pinned_via_client,
    assert_statement_rows_equal,
    auth_headers,
    default_image_model,
    get_json,
    recording_hook,
    upload_statement,
    wait_for_statement,
)
from tests.e2e.auto_accept_poll import wait_for_auto_approved_statement
from tests.e2e.journey_checkpoint import checkpoint

POLL_SECONDS, SETTLE_SECONDS, AUTO_ACCEPT_CONFIDENCE = 3, 5, 85
INSTITUTION, CURRENCY = "Stage One Routing Bank", "SGD"
PERIOD_START, PERIOD_END = date(2026, 5, 1), date(2026, 5, 31)
OPENING_BALANCE, CLEAN_CLOSING_BALANCE = Decimal("2000.00"), Decimal("4837.50")
BROKEN_CLOSING_BALANCE = CLEAN_CLOSING_BALANCE + Decimal("0.05")
BROKEN_REVIEW_REASON = "Balance mismatch: delta=0.05 exceeds tolerance 0.001"


@dataclass(frozen=True)
class FixtureRow:
    txn_date: date
    description: str
    direction: str
    amount: Decimal


FIXTURE_ROWS = (
    FixtureRow(
        date(2026, 5, 3), "Salary Credit ACME PTE LTD", "IN", Decimal("3000.00")
    ),
    FixtureRow(
        date(2026, 5, 7), "FairPrice Supermarket Groceries", "OUT", Decimal("85.40")
    ),
    FixtureRow(date(2026, 5, 12), "ComfortDelGro Taxi Fare", "OUT", Decimal("23.60")),
    FixtureRow(date(2026, 5, 20), "Singtel Mobile Bill", "OUT", Decimal("55.00")),
    FixtureRow(date(2026, 5, 31), "Interest Credited", "IN", Decimal("1.50")),
)
EXPECTED_EVENTS = [
    {
        "date": r.txn_date.isoformat(),
        "amount": str(r.amount),
        "direction": r.direction,
        "currency": CURRENCY,
    }
    for r in FIXTURE_ROWS
]


def _render_statement_pdf(
    path: Path, *, account_number: str, closing_balance: Decimal
) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    styles = getSampleStyleSheet()
    total_credits = sum(r.amount for r in FIXTURE_ROWS if r.direction == "IN")
    total_debits = sum(r.amount for r in FIXTURE_ROWS if r.direction == "OUT")
    table = [
        ["Date", "Description", "Debit", "Credit"],
        *(
            [
                r.txn_date.isoformat(),
                r.description,
                f"{r.amount:,.2f}" if r.direction == "OUT" else "",
                f"{r.amount:,.2f}" if r.direction == "IN" else "",
            ]
            for r in FIXTURE_ROWS
        ),
    ]
    story = [
        Paragraph(INSTITUTION, styles["Title"]),
        Paragraph("Monthly Account Statement", styles["Heading2"]),
        Paragraph(f"Account Number: {account_number}", styles["Normal"]),
        Paragraph(f"Currency: {CURRENCY}", styles["Normal"]),
        Paragraph(
            f"Statement Period: {PERIOD_START.isoformat()} to {PERIOD_END.isoformat()}",
            styles["Normal"],
        ),
        Spacer(1, 12),
        Paragraph(
            f"Statement Summary: Opening Balance {CURRENCY} {OPENING_BALANCE:,.2f}, Closing Balance {CURRENCY} {closing_balance:,.2f}",
            styles["Normal"],
        ),
        Paragraph(
            f"Opening Balance: {CURRENCY} {OPENING_BALANCE:,.2f}", styles["Normal"]
        ),
        Spacer(1, 12),
        Table(
            table,
            style=TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                    ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ]
            ),
        ),
        Spacer(1, 12),
        Paragraph(f"Total Credits: {CURRENCY} {total_credits:,.2f}", styles["Normal"]),
        Paragraph(f"Total Debits: {CURRENCY} {total_debits:,.2f}", styles["Normal"]),
        Paragraph(
            f"Closing Balance: {CURRENCY} {closing_balance:,.2f}", styles["Normal"]
        ),
    ]
    SimpleDocTemplate(str(path), pagesize=A4).build(story)
    return path


def _posted_entries_for(entries: list[dict], statement: dict) -> list[dict]:
    txn_ids = {t["id"] for t in statement["transactions"]}
    return [e for e in entries if e["source_id"] in txn_ids and e["status"] == "posted"]


async def _wait_for_auto_accept(
    client: httpx.AsyncClient, statement_id: str
) -> tuple[dict, list[dict]]:
    async def _fetch_posted(statement: dict) -> tuple[bool, list[dict]]:
        payload = await get_json(client, "/journal-entries?limit=100")
        assert payload["total"] == len(payload["items"])
        posted = _posted_entries_for(payload["items"], statement)
        return len(posted) == len(FIXTURE_ROWS), posted

    return await wait_for_auto_approved_statement(
        client,
        api_url=api_url,
        statement_id=statement_id,
        timeout_ms=PARSING_TIMEOUT_MS,
        poll_seconds=POLL_SECONDS,
        fetch_entries=_fetch_posted,
        terminal_fail_statuses=frozenset({"rejected", "uploaded"}),
        failure_prefix="clean statement was not auto-accepted",
        timeout_message=lambda st,
        entries: f"statement {statement_id} did not reach parsed within {PARSING_TIMEOUT_MS}ms: status={st.get('status')} posted_entries={len(entries)}",
    )


@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.llm
@pytest.mark.product_defaults
async def test_stage1_accepts_clean_source_and_reviews_broken_source(
    authenticated_page_unique: Page, tmp_path: Path, record_property
) -> None:
    signed_net = sum(
        (r.amount if r.direction == "IN" else -r.amount for r in FIXTURE_ROWS),
        Decimal("0"),
    )
    assert (
        OPENING_BALANCE + signed_net == CLEAN_CLOSING_BALANCE
        and OPENING_BALANCE + signed_net != BROKEN_CLOSING_BALANCE
    )
    sent_requests: list[RecordedRequest] = []
    async with httpx.AsyncClient(
        headers=await auth_headers(authenticated_page_unique),
        verify=False,
        timeout=120.0,
        event_hooks={"request": [recording_hook(sent_requests)]},
    ) as client:
        await assert_pinned_via_client(
            client, record_property, reason="the Stage 1 routing proof"
        )
        await assert_default_ai_settings(client)
        model = await default_image_model(client)
        record_property("selected_ocr_model", model)

        clean_pdf = _render_statement_pdf(
            tmp_path / "stage1_clean.pdf",
            account_number="5551-234-8901",
            closing_balance=CLEAN_CLOSING_BALANCE,
        )
        clean_id = await upload_statement(
            client,
            filename=clean_pdf.name,
            content=clean_pdf.read_bytes(),
            content_type="application/pdf",
            institution=INSTITUTION,
            model=model,
        )
        clean, posted = await _wait_for_auto_accept(client, clean_id)
        assert (
            clean["status"] == "approved"
            and clean["balance_validated"] is True
            and clean["confidence_score"] >= AUTO_ACCEPT_CONFIDENCE
            and clean["account_id"]
            and Decimal(str(clean["opening_balance"])) == OPENING_BALANCE
            and Decimal(str(clean["closing_balance"])) == CLEAN_CLOSING_BALANCE
            and (clean["currency"], clean["period_start"], clean["period_end"])
            == (CURRENCY, PERIOD_START.isoformat(), PERIOD_END.isoformat())
        )
        assert_statement_rows_equal(clean["transactions"], EXPECTED_EVENTS)
        assert (
            len(posted) == len(FIXTURE_ROWS)
            and {e["source_id"] for e in posted}
            == {t["id"] for t in clean["transactions"]}
            and all(e["decision_anchor_id"] for e in posted)
        )
        assert Counter(
            (ln["direction"], Decimal(str(ln["amount"])))
            for e in posted
            for ln in e["lines"]
            if ln["account_id"] == clean["account_id"]
        ) == Counter(
            (
                ("DEBIT" if r.direction == "IN" else "CREDIT", r.amount)
                for r in FIXTURE_ROWS
            )
        )

        await asyncio.sleep(SETTLE_SECONDS)
        settled = await get_json(client, f"/statements/{clean_id}")
        assert settled["status"] == "approved"
        entries_after_clean = (await get_json(client, "/journal-entries?limit=100"))[
            "items"
        ]
        assert len(_posted_entries_for(entries_after_clean, settled)) == len(
            FIXTURE_ROWS
        )
        assert [
            r
            for r in sent_requests
            if "/approvals" in r.path
            or "/rejections" in r.path
            or (
                r.method != "GET"
                and ("/review-envelopes" in r.path or "reviewed-dispositions" in r.path)
            )
        ] == []
        assert [
            r
            for r in sent_requests
            if r.method != "GET" and r.path.endswith("/users/me/settings")
        ] == []

        broken_pdf = _render_statement_pdf(
            tmp_path / "stage1_broken.pdf",
            account_number="5551-234-7702",
            closing_balance=BROKEN_CLOSING_BALANCE,
        )
        broken_id = await upload_statement(
            client,
            filename=broken_pdf.name,
            content=broken_pdf.read_bytes(),
            content_type="application/pdf",
            institution=INSTITUTION,
            model=model,
        )
        await wait_for_statement(
            client,
            broken_id,
            poll_seconds=POLL_SECONDS,
            target_statuses=("parsed", "approved", "rejected"),
            fail_statuses=(),
        )
        await asyncio.sleep(SETTLE_SECONDS)
        reviewed = await get_json(client, f"/statements/{broken_id}")
        assert (
            reviewed["status"] == "parsed"
            and reviewed["balance_validated"] is False
            and Decimal(str(reviewed["opening_balance"])) == OPENING_BALANCE
            and Decimal(str(reviewed["closing_balance"])) == BROKEN_CLOSING_BALANCE
            and (reviewed["validation_error"] or "") == BROKEN_REVIEW_REASON
        )
        assert_statement_rows_equal(reviewed["transactions"], EXPECTED_EVENTS)
        review = await get_json(client, f"/statements/{broken_id}/review")
        assert (
            review["stage1_status"] == "pending_review"
            and review["balance_validated"] is False
        )
        entries_after_broken = (await get_json(client, "/journal-entries?limit=100"))[
            "items"
        ]
        assert _posted_entries_for(entries_after_broken, reviewed) == [] and {
            e["id"] for e in entries_after_broken
        } == {e["id"] for e in entries_after_clean}
        for k, v in {
            "clean_statement_id": clean_id,
            "clean_confidence_score": clean["confidence_score"],
            "statement_approval_api_attempts": 0,
            "broken_statement_id": broken_id,
            "broken_confidence_score": reviewed["confidence_score"],
        }.items():
            record_property(k, v)
        checkpoint(record_property, "U3")
