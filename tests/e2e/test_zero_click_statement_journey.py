from __future__ import annotations

import json
import time
import uuid
from collections import Counter
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
)
from tests.e2e.auto_accept_poll import wait_for_auto_approved_statement
from tests.e2e.journey_checkpoint import checkpoint
from tests.e2e.pdf_fixture_paths import committed_fixture_pdf

EXPECTED_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests/fixtures/pdf/generated/gxs_statement_fixture_expected.json"
)
LIVE_ENTRY_STATUSES = {"posted", "reconciled"}


def _live_entries_by_source(
    entries: list[dict], transaction_ids: set[str]
) -> Counter[str]:
    return Counter(
        e["source_id"]
        for e in entries
        if e["source_id"] in transaction_ids and e["status"] in LIVE_ENTRY_STATUSES
    )


async def _wait_until_every_row_has_its_effect(
    client: httpx.AsyncClient, statement_id: str, *, rows: int
) -> tuple[dict, list[dict]]:
    async def _fetch_entries(statement: dict) -> tuple[bool, list[dict]]:
        payload = await get_json(client, "/journal-entries", limit=100)
        assert payload["total"] == len(payload["items"])
        entries = payload["items"]
        return len(
            _live_entries_by_source(
                entries, {t["id"] for t in statement["transactions"]}
            )
        ) == rows, entries

    return await wait_for_auto_approved_statement(
        client,
        api_url=api_url,
        statement_id=statement_id,
        timeout_ms=PARSING_TIMEOUT_MS,
        poll_seconds=3,
        fetch_entries=_fetch_entries,
        terminal_fail_statuses=frozenset({"rejected"}),
        failure_prefix="the statement did not post by itself",
    )


@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.llm
@pytest.mark.product_defaults
async def test_upload_alone_produces_the_base_tables_and_the_three_statements(
    authenticated_page_unique: Page, tmp_path: Path, record_property
) -> None:
    expected = json.loads(EXPECTED_PATH.read_text())
    facts, events = expected["statement"], expected["events"]
    opening, closing = (
        Decimal(facts["opening_balance"]),
        Decimal(facts["closing_balance"]),
    )
    requests: list[RecordedRequest] = []
    async with httpx.AsyncClient(
        headers=await auth_headers(authenticated_page_unique),
        verify=False,
        timeout=120.0,
        event_hooks={"request": [recording_hook(requests)]},
    ) as client:
        await assert_pinned_via_client(
            client, record_property, reason="the zero-click proof"
        )
        await assert_default_ai_settings(client)
        model = await default_image_model(client)
        record_property("selected_ocr_model", model)
        pdf = tmp_path / "gxs-zero-click.pdf"
        pdf.write_bytes(
            committed_fixture_pdf("gxs_statement_fixture.pdf").read_bytes()
            + f"\n% zero click {uuid.uuid4()}\n".encode()
        )
        started = time.monotonic()
        statement_id = await upload_statement(
            client,
            filename=pdf.name,
            content=pdf.read_bytes(),
            content_type="application/pdf",
            model=model,
        )
        checkpoint(record_property, "U1")

        statement, entries = await _wait_until_every_row_has_its_effect(
            client, statement_id, rows=len(events)
        )
        record_property(
            "seconds_from_upload_to_posted", round(time.monotonic() - started, 1)
        )
        assert_statement_rows_equal(statement["transactions"], events)
        assert (
            statement["status"] == "approved"
            and statement["validation_error"] is None
            and statement["account_id"]
            and expected["institution"].lower()
            in (statement.get("institution") or "").lower()
        )
        assert (
            Decimal(str(statement["opening_balance"])) == opening
            and Decimal(str(statement["closing_balance"])) == closing
        )
        checkpoint(record_property, "U2")

        txn_ids = {t["id"] for t in statement["transactions"]}
        effects = _live_entries_by_source(entries, txn_ids)
        assert set(effects) == txn_ids and set(effects.values()) == {1}
        checkpoint(record_property, "U6")
        assert not [
            r
            for r in requests
            if "/approvals" in r.path
            or "/rejections" in r.path
            or (
                r.method != "GET"
                and (
                    "/review-envelopes" in r.path
                    or "reviewed-dispositions" in r.path
                    or r.path.endswith("/users/me/settings")
                )
            )
        ]

        currency, start, end = (
            statement["currency"],
            statement["period_start"],
            statement["period_end"],
        )
        accounts = (await get_json(client, "/accounts", include_balance="true"))[
            "items"
        ]
        assert (
            Decimal(
                str(
                    next(a for a in accounts if a["id"] == statement["account_id"])[
                        "balance"
                    ]
                )
            )
            == closing
        )
        bs = await get_json(
            client, "/reports/balance-sheet", as_of_date=end, currency=currency
        )
        inc = await get_json(
            client,
            "/reports/income-statement",
            start_date=start,
            end_date=end,
            currency=currency,
        )
        cf = await get_json(
            client,
            "/reports/cash-flow",
            start_date=start,
            end_date=end,
            currency=currency,
        )
        net_income = Decimal(inc["net_income"])
        assert (
            Decimal(inc["total_income"]) - Decimal(inc["total_expenses"]) == net_income
            and Decimal(bs["net_income"]) == net_income
            and bs["is_balanced"] is True
            and Decimal(bs["equation_delta"]) == 0
        )
        assert (
            Decimal(bs["total_equity"]) == opening
            and Decimal(bs["total_assets"]) - Decimal(bs["total_liabilities"])
            == Decimal(bs["total_equity"]) + net_income
        )
        cf_sum = cf["summary"]
        assert (
            Decimal(cf_sum["beginning_cash"]) == opening
            and cf["cash_bridge"]["reconciles"] is True
            and Decimal(cf_sum["beginning_cash"]) + Decimal(cf_sum["net_cash_flow"])
            == Decimal(cf_sum["ending_cash"])
        )

        names, by_txn = (
            {a["id"]: a["name"] for a in accounts},
            {t["id"]: t["description"] for t in statement["transactions"]},
        )
        for entry in entries:
            if (desc := by_txn.get(entry["source_id"])) is not None:
                record_property(
                    f"booked {entry['source_id'][:8]} {desc[:24]}",
                    ", ".join(
                        sorted(
                            names.get(ln["account_id"], "hidden system account")
                            for ln in entry["lines"]
                            if ln["account_id"] != statement["account_id"]
                        )
                    ),
                )
        processing = await get_json(client, "/reconciliation/transfers/summary")
        record_property("processing_balance", processing["current_balance"])
        record_property("net_income", str(net_income))
