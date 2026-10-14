"""Core-journey proof U3: Stage 1 accepts a clean source and reviews a broken one (#2392).

One isolated user uploads two generated PDF statements. The statements differ in
the account number and in the printed closing balance.

* The clean statement prints closing = opening + transactions. Stage 1 accepts it
  with no review call. The ledger holds one posted entry for each transaction.
* The broken statement prints a closing balance 0.05 above that figure. Stage 1
  does not accept it. It waits in review with a balance error and posts nothing.

Both paths run in one test. No assertion depends on which path happened.

Why the gap is 0.05: the parser accepts a gap up to 0.10. Stage 1 accepts a gap up
to 0.001. A gap above 0.10 makes the parser extract the document again, and a new
extraction can read a corrected closing balance. That outcome varies from run to
run. A gap of 0.05 is never extracted again, so it always reaches Stage 1.

Why both documents print total credits and total debits, and print the closing
balance twice: on an older fixture with one closing line, the model returned the
computed closing balance, not the printed one, in 2 of 8 staging runs. The product
then approved the broken statement (#2394). In those runs every row and every posted
amount was right. This fixture has not been shown to be safer. It was not approved
in 11 trials, but 11 trials are too few to tell. The numbers and the raw data are in
#2394. A flaky result of this test is a signal about #2394, not about the board.

Auto-posting needs economic meaning for every transaction. The product default is
on (#2405). The test changes no setting. It reads the ``enable_ai_classification``
setting of the new user and asserts that it is on. It also asserts that it sent no
settings write. The classifier proposes a category for each transaction. The 0.85
confidence gate decides. Each description names a merchant or an income source, so
each proposal is clear.

No CSV can reach auto-accept. The CSV parser always marks its balances as missing,
and that caps the confidence at 59. Only live OCR plus live classification reaches
``approved``.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from common.testing.ac_proof import ac_proof
from deployment_pin import assert_pinned_deployment, resolve_expected_commit
from journey_checkpoint import checkpoint
from playwright.async_api import Page

APP_URL = os.getenv("APP_URL", "http://localhost:3000")
PARSING_TIMEOUT_MS = int(os.getenv("PARSING_TIMEOUT_MS", "480000"))
POLL_SECONDS = 3
SETTLE_SECONDS = 5

# Stage 1 auto-accept threshold (HIGH_CONFIDENCE_AUTO_APPROVE_THRESHOLD in the backend).
AUTO_ACCEPT_CONFIDENCE = 85

INSTITUTION = "Stage One Routing Bank"
CLEAN_ACCOUNT_NUMBER = "5551-234-8901"
BROKEN_ACCOUNT_NUMBER = "5551-234-7702"
CURRENCY = "SGD"
PERIOD_START = date(2026, 5, 1)
PERIOD_END = date(2026, 5, 31)
OPENING_BALANCE = Decimal("2000.00")
# 2000.00 + 3000.00 + 1.50 - 85.40 - 23.60 - 55.00
CLEAN_CLOSING_BALANCE = Decimal("4837.50")
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


def _api_url(path: str) -> str:
    return f"{APP_URL.rstrip('/')}/api{path}"


async def _auth_headers(page: Page) -> dict[str, str]:
    cookies = await page.context.cookies(APP_URL)
    auth_cookie = next(
        (cookie for cookie in cookies if cookie["name"] == "finance_access_token"),
        None,
    )
    assert auth_cookie, "authenticated Playwright context is missing auth cookie"
    return {"Cookie": f"finance_access_token={auth_cookie['value']}"}


def _render_statement_pdf(
    path: Path, *, account_number: str, closing_balance: Decimal
) -> Path:
    """Write a text PDF with a debit and credit table, totals and no running balance."""
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
    table = [["Date", "Description", "Debit", "Credit"]]
    for row in FIXTURE_ROWS:
        shown = f"{row.amount:,.2f}"
        table.append(
            [
                row.txn_date.isoformat(),
                row.description,
                shown if row.direction == "OUT" else "",
                shown if row.direction == "IN" else "",
            ]
        )
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
            f"Statement Summary: Opening Balance {CURRENCY} {OPENING_BALANCE:,.2f}, "
            f"Closing Balance {CURRENCY} {closing_balance:,.2f}",
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


def _signed_net(rows: tuple[FixtureRow, ...]) -> Decimal:
    return sum(
        (row.amount if row.direction == "IN" else -row.amount for row in rows),
        Decimal("0"),
    )


async def _default_image_model(client: httpx.AsyncClient) -> str:
    response = await client.get(_api_url("/llm/catalog?modality=image"))
    assert response.status_code == 200, (
        f"model catalog request failed: {response.status_code} {response.text}"
    )
    payload = response.json()
    return payload.get("default_model") or payload["models"][0]["id"]


async def _upload_pdf(client: httpx.AsyncClient, *, pdf_path: Path, model: str) -> str:
    with pdf_path.open("rb") as handle:
        response = await client.post(
            _api_url("/statements/upload"),
            data={"institution": INSTITUTION, "model": model},
            files={"file": (pdf_path.name, handle, "application/pdf")},
        )
    assert response.status_code in (200, 201, 202), (
        f"upload failed: {response.status_code} {response.text}"
    )
    statement_id = response.json().get("id")
    assert statement_id, f"upload response missing id: {response.text}"
    return str(statement_id)


async def _get_statement(client: httpx.AsyncClient, statement_id: str) -> dict:
    response = await client.get(_api_url(f"/statements/{statement_id}"))
    assert response.status_code == 200, (
        f"statement read failed: {response.status_code} {response.text}"
    )
    return response.json()


async def _get_journal_entries(client: httpx.AsyncClient) -> list[dict]:
    response = await client.get(_api_url("/journal-entries?limit=100"))
    assert response.status_code == 200, (
        f"journal entry read failed: {response.status_code} {response.text}"
    )
    payload = response.json()
    assert payload["total"] == len(payload["items"]), (
        "the user holds more entries than one page; the count check needs every entry"
    )
    return payload["items"]


def _posted_entries_for(entries: list[dict], statement: dict) -> list[dict]:
    transaction_ids = {transaction["id"] for transaction in statement["transactions"]}
    return [
        entry
        for entry in entries
        if entry["source_id"] in transaction_ids and entry["status"] == "posted"
    ]


async def _wait_for_auto_accept(
    client: httpx.AsyncClient, statement_id: str
) -> tuple[dict, list[dict]]:
    """Wait until Stage 1 posts every transaction of the statement, with no review call.

    The test makes no call to a review or approve endpoint. A statement that
    settles as anything other than approved fails the test at once.
    """
    deadline = time.monotonic() + PARSING_TIMEOUT_MS / 1000
    statement: dict = {}
    posted: list[dict] = []
    while time.monotonic() < deadline:
        statement = await _get_statement(client, statement_id)
        status = statement["status"]
        if status in ("parsed", "rejected", "uploaded"):
            pytest.fail(
                "clean statement was not auto-accepted: "
                f"status={status} confidence_score={statement.get('confidence_score')} "
                f"balance_validated={statement.get('balance_validated')} "
                f"validation_error={statement.get('validation_error')!r}"
            )
        if status == "approved":
            posted = _posted_entries_for(await _get_journal_entries(client), statement)
            if len(posted) == len(FIXTURE_ROWS):
                return statement, posted
        await asyncio.sleep(POLL_SECONDS)
    pytest.fail(
        f"statement {statement_id} did not reach parsed within {PARSING_TIMEOUT_MS}ms "
        "(clean statement: approved with every entry posted): "
        f"status={statement.get('status')} posted_entries={len(posted)}"
    )


async def _wait_for_parse_end(client: httpx.AsyncClient, statement_id: str) -> dict:
    """Wait until the parse of a statement leaves the parsing state."""
    deadline = time.monotonic() + PARSING_TIMEOUT_MS / 1000
    statement: dict = {}
    while time.monotonic() < deadline:
        statement = await _get_statement(client, statement_id)
        if statement["status"] != "parsing":
            return statement
        await asyncio.sleep(POLL_SECONDS)
    pytest.fail(
        f"statement {statement_id} did not reach parsed within {PARSING_TIMEOUT_MS}ms "
        f"(broken statement): status={statement.get('status')}"
    )


def _statement_rows(statement: dict) -> list[tuple]:
    return sorted(
        (t["txn_date"], Decimal(str(t["amount"])), t["direction"], t["currency"])
        for t in statement["transactions"]
    )


def _fixture_rows() -> list[tuple]:
    return sorted(
        (row.txn_date.isoformat(), row.amount, row.direction, CURRENCY)
        for row in FIXTURE_ROWS
    )


@dataclass(frozen=True)
class RecordedRequest:
    method: str
    path: str


def _recording_hook(requests: list[RecordedRequest]):
    async def record(request: httpx.Request) -> None:
        requests.append(RecordedRequest(request.method, request.url.path))

    return record


def _review_action_requests(requests: list[RecordedRequest]) -> list[RecordedRequest]:
    """Requests that act as a person: any approve call, or a write to a review path."""
    return [
        request
        for request in requests
        if "/review/approve" in request.path
        or (
            request.method != "GET"
            and ("/review/" in request.path or "reviewed-disposition" in request.path)
        )
    ]


def _settings_write_requests(requests: list[RecordedRequest]) -> list[RecordedRequest]:
    """Requests that change the user's settings."""
    return [
        request
        for request in requests
        if request.method != "GET" and request.path.endswith("/users/me/settings")
    ]


def _bank_side_lines(entries: list[dict], account_id: str) -> Counter:
    return Counter(
        (line["direction"], Decimal(str(line["amount"])))
        for entry in entries
        for line in entry["lines"]
        if line["account_id"] == account_id
    )


@ac_proof(
    "stage1-routing-clean-accepted-broken-reviewed",
    ac_ids=["AC-extraction.stage1-routing.1"],
    scope="behavioral",
    ci_tier="post_merge_environment",
    trust_mode="llm_ocr_post_merge",
    source_classes=["bank_statement"],
    mirror_proof_id="extraction-corpus-journeys-pr",
    issue="#2392",
    required_markers=["e2e", "tier3", "critical", "llm"],
)
@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.llm
@pytest.mark.product_defaults
async def test_stage1_accepts_clean_source_and_reviews_broken_source(
    authenticated_page_unique: Page, tmp_path: Path, record_property
) -> None:
    """EPIC-003 EPIC-008: AC-extraction.stage1-routing.1, both Stage 1 paths in one run."""
    # The fixture is hand-checkable: the clean closing equals opening plus net flow,
    # and the broken closing does not.
    assert OPENING_BALANCE + _signed_net(FIXTURE_ROWS) == CLEAN_CLOSING_BALANCE
    assert OPENING_BALANCE + _signed_net(FIXTURE_ROWS) != BROKEN_CLOSING_BALANCE

    expected_version = os.getenv("EXPECTED_SHA")
    assert expected_version, (
        "the Stage 1 routing proof requires an explicit EXPECTED_SHA"
    )
    expected_commit = resolve_expected_commit(expected_version)
    record_property("expected_version", expected_version)
    record_property("expected_commit", expected_commit)

    headers = await _auth_headers(authenticated_page_unique)
    sent_requests: list[RecordedRequest] = []
    async with httpx.AsyncClient(
        headers=headers,
        verify=False,
        timeout=120.0,
        event_hooks={"request": [_recording_hook(sent_requests)]},
    ) as client:
        health = await client.get(_api_url("/health"))
        assert health.status_code == 200
        assert_pinned_deployment(health.json(), expected_version, expected_commit)
        frontend = await client.get(f"{APP_URL.rstrip('/')}/frontend-version.json")
        assert frontend.status_code == 200, (
            "frontend deployment version must be observable"
        )
        assert_pinned_deployment(frontend.json(), expected_version, expected_commit)
        checkpoint(record_property, "U12")

        settings = await client.get(_api_url("/users/me/settings"))
        assert settings.status_code == 200, (
            f"user settings read failed: {settings.status_code} {settings.text}"
        )
        assert settings.json()["enable_ai_classification"] is True, (
            "a new user must have AI classification on by default (#2405)"
        )

        model = await _default_image_model(client)
        record_property("selected_ocr_model", model)

        # Path 1: the clean source. The test calls no review or approve endpoint.
        clean_pdf = _render_statement_pdf(
            tmp_path / "stage1_clean.pdf",
            account_number=CLEAN_ACCOUNT_NUMBER,
            closing_balance=CLEAN_CLOSING_BALANCE,
        )
        clean_id = await _upload_pdf(client, pdf_path=clean_pdf, model=model)
        clean, posted = await _wait_for_auto_accept(client, clean_id)

        assert clean["status"] == "approved"
        assert clean["balance_validated"] is True
        assert clean["confidence_score"] >= AUTO_ACCEPT_CONFIDENCE
        assert clean["account_id"], "Stage 1 must bind the statement to a bank account"
        assert Decimal(str(clean["opening_balance"])) == OPENING_BALANCE
        assert Decimal(str(clean["closing_balance"])) == CLEAN_CLOSING_BALANCE
        assert clean["currency"] == CURRENCY
        assert clean["period_start"] == PERIOD_START.isoformat()
        assert clean["period_end"] == PERIOD_END.isoformat()
        assert _statement_rows(clean) == _fixture_rows(), (
            "the extracted transactions must equal the fixture rows"
        )
        assert len(posted) == len(FIXTURE_ROWS)
        assert {entry["source_id"] for entry in posted} == {
            transaction["id"] for transaction in clean["transactions"]
        }, "each source transaction must have exactly one posted entry"
        assert all(entry["decision_anchor_id"] for entry in posted), (
            "each posted entry must keep its authority anchor"
        )
        assert _bank_side_lines(posted, clean["account_id"]) == Counter(
            ("DEBIT" if row.direction == "IN" else "CREDIT", row.amount)
            for row in FIXTURE_ROWS
        ), "the bank-side ledger lines must equal the fixture rows"

        await asyncio.sleep(SETTLE_SECONDS)
        settled = await _get_statement(client, clean_id)
        assert settled["status"] == "approved", (
            "the clean statement must stay approved after posting"
        )
        entries_after_clean = await _get_journal_entries(client)
        assert len(_posted_entries_for(entries_after_clean, settled)) == len(
            FIXTURE_ROWS
        )
        record_property("clean_statement_id", clean_id)
        record_property("clean_confidence_score", clean["confidence_score"])
        review_actions = _review_action_requests(sent_requests)
        assert review_actions == [], (
            f"the test must not approve or review the clean statement: {review_actions}"
        )
        record_property("statement_approval_api_attempts", len(review_actions))
        settings_writes = _settings_write_requests(sent_requests)
        assert settings_writes == [], (
            f"the default setting must be enough; the test sent: {settings_writes}"
        )

        # Path 2: the broken source. Its printed closing balance is 0.05 too high.
        broken_pdf = _render_statement_pdf(
            tmp_path / "stage1_broken.pdf",
            account_number=BROKEN_ACCOUNT_NUMBER,
            closing_balance=BROKEN_CLOSING_BALANCE,
        )
        broken_id = await _upload_pdf(client, pdf_path=broken_pdf, model=model)
        await _wait_for_parse_end(client, broken_id)
        await asyncio.sleep(SETTLE_SECONDS)
        reviewed = await _get_statement(client, broken_id)

        assert reviewed["status"] == "parsed", (
            "broken statement was not sent to review: "
            f"id={broken_id} status={reviewed['status']} "
            f"opening_balance={reviewed['opening_balance']} "
            f"closing_balance={reviewed['closing_balance']} "
            f"confidence_score={reviewed['confidence_score']} "
            f"rows={_statement_rows(reviewed)} "
            f"validation_error={reviewed['validation_error']!r}"
        )
        assert Decimal(str(reviewed["opening_balance"])) == OPENING_BALANCE
        assert Decimal(str(reviewed["closing_balance"])) == BROKEN_CLOSING_BALANCE
        assert reviewed["balance_validated"] is False
        assert (reviewed["validation_error"] or "") == BROKEN_REVIEW_REASON
        assert _statement_rows(reviewed) == _fixture_rows(), (
            "the reviewer must see the fixture rows of the broken statement"
        )
        review = await client.get(_api_url(f"/statements/{broken_id}/review"))
        assert review.status_code == 200
        assert review.json()["stage1_status"] == "pending_review"
        assert review.json()["balance_validated"] is False
        entries_after_broken = await _get_journal_entries(client)
        assert _posted_entries_for(entries_after_broken, reviewed) == [], (
            "the broken statement must post no ledger entry"
        )
        assert {entry["id"] for entry in entries_after_broken} == {
            entry["id"] for entry in entries_after_clean
        }, "no ledger entry may appear after the broken upload"
        record_property("broken_statement_id", broken_id)
        record_property("broken_confidence_score", reviewed["confidence_score"])
        checkpoint(record_property, "U3")
