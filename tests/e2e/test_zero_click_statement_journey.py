"""Core-journey proof: an upload alone produces the base tables and the default three statements (#2405).

One isolated user keeps the product defaults and uploads the committed GXS statement. The user calls no
review endpoint and no approve endpoint, and writes no setting. The system then holds:

* the transactions of the statement, equal to the independent fixture;
* exactly one posted ledger effect for each transaction (an income or expense entry, or a Processing leg);
* a bank account whose balance equals the printed closing balance;
* a balance sheet, an income statement and a cash flow that agree with each other and with the source.

The test does not assume which category the model picks for a row. The fixture row "Payment to GrabPay Wallet"
may post as a transport expense or as a Processing leg. The ties below hold for every choice. They check
that the three statements come from the same ledger and tie to the printed balances:

* the bank balance equals the printed closing balance;
* the equity stock equals the printed opening balance, and the accounting equation holds;
* the net income of the balance sheet equals the net income of the income statement;
* the cash flow bridge reconciles, and its beginning cash equals the printed opening balance.

The categories that the model chose are recorded as JUnit properties for the board. No assertion depends on them.
The manual review path has its own journeys (the GXS browser journey and the institution journeys).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from common.testing.ac_proof import ac_proof
from deployment_pin import assert_pinned_deployment, resolve_expected_commit
from journey_checkpoint import checkpoint
from pdf_fixture_paths import committed_fixture_pdf
from playwright.async_api import Page

APP_URL = os.getenv("APP_URL", "http://localhost:3000")
PARSING_TIMEOUT_MS = int(os.getenv("PARSING_TIMEOUT_MS", "480000"))
POLL_SECONDS = 3
EXPECTED_PATH = (
    Path(__file__).resolve().parents[2]
    / "common/testing/fixtures/pdf/generated/gxs_statement_fixture_expected.json"
)
# A posted entry is `posted`. A Processing leg is `reconciled` from the moment it exists.
LIVE_ENTRY_STATUSES = {"posted", "reconciled"}


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


@dataclass(frozen=True)
class RecordedRequest:
    method: str
    path: str


def _recording_hook(requests: list[RecordedRequest]):
    async def record(request: httpx.Request) -> None:
        requests.append(RecordedRequest(request.method, request.url.path))

    return record


def _person_actions(requests: list[RecordedRequest]) -> list[RecordedRequest]:
    """Requests that act as a person: any approve call, a write to a review path, or a settings write."""
    return [
        request
        for request in requests
        if "/review/approve" in request.path
        or (
            request.method != "GET"
            and (
                "/review/" in request.path
                or "reviewed-disposition" in request.path
                or request.path.endswith("/users/me/settings")
            )
        )
    ]


async def _get(client: httpx.AsyncClient, path: str, **params) -> dict:
    response = await client.get(_api_url(path), params=params or None)
    assert response.status_code == 200, (
        f"GET {path} failed: {response.status_code} {response.text}"
    )
    return response.json()


async def _default_image_model(client: httpx.AsyncClient) -> str:
    payload = await _get(client, "/llm/catalog", modality="image")
    return payload.get("default_model") or payload["models"][0]["id"]


async def _upload_pdf(client: httpx.AsyncClient, *, pdf_path: Path, model: str) -> str:
    with pdf_path.open("rb") as handle:
        response = await client.post(
            _api_url("/statements/upload"),
            data={"model": model},
            files={"file": (pdf_path.name, handle, "application/pdf")},
        )
    assert response.status_code in (200, 201, 202), (
        f"upload failed: {response.status_code} {response.text}"
    )
    statement_id = response.json().get("id")
    assert statement_id, f"upload response missing id: {response.text}"
    return str(statement_id)


def _live_entries_by_source(entries: list[dict], transaction_ids: set[str]) -> Counter:
    return Counter(
        entry["source_id"]
        for entry in entries
        if entry["source_id"] in transaction_ids
        and entry["status"] in LIVE_ENTRY_STATUSES
    )


async def _wait_until_every_row_has_its_effect(
    client: httpx.AsyncClient, statement_id: str, *, rows: int
) -> tuple[dict, list[dict]]:
    """Wait until the statement is approved and every transaction has a live entry, with no call of a person.

    A statement that settles as parsed or rejected fails the test at once, with the reason that it holds.
    """
    deadline = time.monotonic() + PARSING_TIMEOUT_MS / 1000
    statement: dict = {}
    entries: list[dict] = []
    while time.monotonic() < deadline:
        statement = await _get(client, f"/statements/{statement_id}")
        status = statement["status"]
        if status in ("parsed", "rejected"):
            pytest.fail(
                "the statement did not post by itself: "
                f"status={status} confidence_score={statement.get('confidence_score')} "
                f"balance_validated={statement.get('balance_validated')} "
                f"validation_error={statement.get('validation_error')!r}"
            )
        if status == "approved":
            payload = await _get(client, "/journal-entries", limit=100)
            assert payload["total"] == len(payload["items"]), (
                "the user holds more entries than one page; the count check needs every entry"
            )
            entries = payload["items"]
            transaction_ids = {t["id"] for t in statement["transactions"]}
            if len(_live_entries_by_source(entries, transaction_ids)) == rows:
                return statement, entries
        await asyncio.sleep(POLL_SECONDS)
    pytest.fail(
        f"statement {statement_id} did not post every row within {PARSING_TIMEOUT_MS}ms: "
        f"status={statement.get('status')} entries={len(entries)}"
    )


@ac_proof(
    "zero-click-upload-to-three-statements",
    ac_ids=["AC-extraction.auto-accept.13"],
    scope="behavioral",
    ci_tier="post_merge_environment",
    trust_mode="llm_ocr_post_merge",
    source_classes=["bank_statement"],
    mirror_proof_id="extraction-corpus-journeys-pr",
    issue="#2405",
    required_markers=["e2e", "tier3", "critical", "llm"],
)
@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.llm
@pytest.mark.product_defaults
async def test_upload_alone_produces_the_base_tables_and_the_three_statements(
    authenticated_page_unique: Page, tmp_path: Path, record_property
) -> None:
    """EPIC-003 EPIC-008: AC-extraction.auto-accept.13, no click between the upload and the statements."""
    expected = json.loads(EXPECTED_PATH.read_text())
    facts = expected["statement"]
    events = expected["events"]
    opening = Decimal(facts["opening_balance"])
    closing = Decimal(facts["closing_balance"])

    expected_version = os.getenv("EXPECTED_SHA")
    assert expected_version, "the zero-click proof requires an explicit EXPECTED_SHA"
    expected_commit = resolve_expected_commit(expected_version)
    record_property("expected_version", expected_version)

    requests: list[RecordedRequest] = []
    headers = await _auth_headers(authenticated_page_unique)
    async with httpx.AsyncClient(
        headers=headers,
        verify=False,
        timeout=120.0,
        event_hooks={"request": [_recording_hook(requests)]},
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

        settings = await _get(client, "/users/me/settings")
        assert settings["enable_ai_classification"] is True, (
            "a new user must have AI classification on by default (#2405)"
        )
        assert settings["auto_accept_ai_suggestions"] is True, (
            "a new user must not hold a choice against the automatic acceptance (#2405)"
        )
        assert settings["auto_accept_ai_suggestions_active"] is True, (
            "a new user must have the system accept the AI suggestions by default (#2405)"
        )

        model = await _default_image_model(client)
        record_property("selected_ocr_model", model)
        pdf = tmp_path / "gxs-zero-click.pdf"
        pdf.write_bytes(
            committed_fixture_pdf("gxs_statement_fixture.pdf").read_bytes()
            + f"\n% zero click {uuid.uuid4()}\n".encode()
        )
        started = time.monotonic()
        statement_id = await _upload_pdf(client, pdf_path=pdf, model=model)
        checkpoint(record_property, "U1")

        statement, entries = await _wait_until_every_row_has_its_effect(
            client, statement_id, rows=len(events)
        )
        record_property(
            "seconds_from_upload_to_posted", round(time.monotonic() - started, 1)
        )

        # The statement rows equal the independent fixture.
        actual_rows = sorted(
            (t["txn_date"], Decimal(str(t["amount"])), t["direction"], t["currency"])
            for t in statement["transactions"]
        )
        assert actual_rows == sorted(
            (e["date"], Decimal(e["amount"]), e["direction"], e["currency"])
            for e in events
        )
        assert statement["status"] == "approved"
        assert (
            expected["institution"].lower()
            in (statement.get("institution") or "").lower()
        ), (
            f"omitted institution must auto-detect {expected['institution']!r} from header, "
            f"got {statement.get('institution')!r}"
        )
        assert statement["validation_error"] is None, (
            f"a posted statement keeps no review note: {statement['validation_error']!r}"
        )
        assert statement["account_id"], (
            "the statement binds to a bank account by itself"
        )
        assert Decimal(str(statement["opening_balance"])) == opening
        assert Decimal(str(statement["closing_balance"])) == closing
        checkpoint(record_property, "U2")

        # Each transaction has exactly one live ledger effect.
        transaction_ids = {t["id"] for t in statement["transactions"]}
        effects = _live_entries_by_source(entries, transaction_ids)
        assert set(effects) == transaction_ids, "every transaction needs an entry"
        assert set(effects.values()) == {1}, (
            f"one entry for each transaction: {effects}"
        )
        checkpoint(record_property, "U6")

        # The user acted as a person never.
        actions = _person_actions(requests)
        assert not actions, f"the journey must make no call of a person: {actions}"

        # The base tables and the three statements tie to the source and to each other.
        currency = statement["currency"]
        start, end = statement["period_start"], statement["period_end"]
        accounts = (await _get(client, "/accounts", include_balance="true"))["items"]
        bank = next(a for a in accounts if a["id"] == statement["account_id"])
        assert Decimal(str(bank["balance"])) == closing, (
            f"the bank balance must equal the printed closing balance: {bank['balance']}"
        )
        balance_sheet = await _get(
            client, "/reports/balance-sheet", as_of_date=end, currency=currency
        )
        income = await _get(
            client,
            "/reports/income-statement",
            start_date=start,
            end_date=end,
            currency=currency,
        )
        cash_flow = await _get(
            client,
            "/reports/cash-flow",
            start_date=start,
            end_date=end,
            currency=currency,
        )
        net_income = Decimal(income["net_income"])
        assert (
            Decimal(income["total_income"]) - Decimal(income["total_expenses"])
            == net_income
        )
        assert Decimal(balance_sheet["net_income"]) == net_income
        assert balance_sheet["is_balanced"] is True
        assert Decimal(balance_sheet["equation_delta"]) == 0
        assert Decimal(balance_sheet["total_equity"]) == opening, (
            "the opening balance is the only equity stock of a new user"
        )
        assert (
            Decimal(balance_sheet["total_assets"])
            - Decimal(balance_sheet["total_liabilities"])
            == Decimal(balance_sheet["total_equity"]) + net_income
        )
        summary = cash_flow["summary"]
        assert Decimal(summary["beginning_cash"]) == opening
        assert cash_flow["cash_bridge"]["reconciles"] is True
        assert Decimal(summary["beginning_cash"]) + Decimal(
            summary["net_cash_flow"]
        ) == Decimal(summary["ending_cash"])

        # What the model chose is data for the board, not an assertion.
        names = {a["id"]: a["name"] for a in accounts}
        by_transaction = {t["id"]: t["description"] for t in statement["transactions"]}
        for entry in entries:
            description = by_transaction.get(entry["source_id"])
            if description is None:
                continue
            counter = sorted(
                names.get(line["account_id"], "hidden system account")
                for line in entry["lines"]
                if line["account_id"] != statement["account_id"]
            )
            record_property(
                f"booked {entry['source_id'][:8]} {description[:24]}",
                ", ".join(counter),
            )
        processing = await _get(client, "/accounts/processing/summary")
        record_property("processing_balance", processing["current_balance"])
        record_property("net_income", str(net_income))
