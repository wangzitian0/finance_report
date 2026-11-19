from __future__ import annotations

import asyncio
import calendar
import json
import time
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from playwright.async_api import Page
from tests.fixtures.provider_review import FixtureDisposition, FixtureEnvelope

from tests.e2e._journey_helpers import (
    api_url,
    assert_pinned_via_client,
    auth_headers,
    create_account,
    create_opening_balances,
    get_json,
    upload_parse_and_approve_csv,
)
from tests.e2e.assistant_answer import (
    ANSWER_TIMEOUT_SECONDS,
    EMPTY_ANSWER_FAILURE,
    OUT_OF_DATA_QUESTION,
    QUESTION,
    misstated_metrics,
    money_amounts,
    says_no_data,
    topic_claims,
)
from tests.e2e.journey_checkpoint import checkpoint

CURRENCY, OPENING, SALARY, RENT = (
    "SGD",
    Decimal("10000.00"),
    Decimal("5000.00"),
    Decimal("1500.00"),
)
CLOSING = OPENING + SALARY - RENT
CSV_HEADER = "Statement Currency,Statement Period Start,Statement Period End,Statement Opening Balance,Statement Closing Balance,Date,Description,Amount"
DISPOSITIONS = {
    "Salary Credit ACME": FixtureDisposition(
        "income", "INCOME", "Monthly salary credit", "SALARY"
    ),
    "Rent Payment Landlord": FixtureDisposition(
        "expense", "EXPENSE", "Monthly rent expense", "HOUSING"
    ),
}
REPORT_CITATIONS = {
    "balance_sheet.total_equity": "/reports?tab=balance-sheet",
    "income_statement.current_month": "/reports?tab=income-statement",
}


async def _ask(client: httpx.AsyncClient, question: str) -> tuple[str, dict, float]:
    started = time.monotonic()
    try:
        resp = await asyncio.wait_for(
            client.post(
                api_url("/chat"),
                json={"message": question},
                timeout=ANSWER_TIMEOUT_SECONDS,
            ),
            timeout=ANSWER_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        pytest.fail(
            f"the assistant gave no full answer within {ANSWER_TIMEOUT_SECONDS} s: {question!r}"
        )
    seconds = round(time.monotonic() - started, 1)
    assert resp.status_code == 200 and resp.text.strip(), EMPTY_ANSWER_FAILURE.format(
        seconds=seconds, question=question
    )
    raw_meta = resp.headers.get("X-Advisor-Metadata")
    assert raw_meta, f"the answer has no X-Advisor-Metadata header: {resp.text}"
    return resp.text, json.loads(raw_meta), seconds


@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.llm
async def test_assistant_answers_from_the_data_of_the_user(
    authenticated_page_unique: Page, record_property
) -> None:
    async with httpx.AsyncClient(
        headers=await auth_headers(authenticated_page_unique),
        verify=False,
        timeout=120.0,
    ) as client:
        health = await assert_pinned_via_client(
            client, record_property, reason="the assistant chat proof"
        )
        today = datetime.fromisoformat(health["timestamp"]).date()
        month_start = today.replace(day=1)
        month_end = month_start.replace(
            day=calendar.monthrange(month_start.year, month_start.month)[1]
        )
        record_property("server_today", today.isoformat())

        account_id = await create_account(
            client, "Assistant Journey Savings", currency=CURRENCY
        )
        await create_opening_balances(
            client,
            entry_date=(month_start - timedelta(days=1)).isoformat(),
            balances={account_id: str(OPENING)},
            currency=CURRENCY,
            memo="Opening cash before the assistant journey statement",
        )
        rows = (("Salary Credit ACME", SALARY), ("Rent Payment Landlord", -RENT))
        csv_text = "\n".join(
            [
                CSV_HEADER,
                *(
                    f"{CURRENCY},{month_start},{month_end},{OPENING},{CLOSING},{month_start},{d},{a}"
                    for d, a in rows
                ),
                "",
            ]
        )
        await upload_parse_and_approve_csv(
            client,
            filename=f"assistant_{uuid.uuid4().hex[:6]}.csv",
            csv_bytes=csv_text.encode("utf-8"),
            institution="Assistant Journey Bank",
            account_id=account_id,
            dispositions=DISPOSITIONS,
            expected_txns=len(rows),
            envelope=FixtureEnvelope(
                currency=CURRENCY,
                period_start=month_start,
                period_end=month_end,
                opening_balance=OPENING,
                closing_balance=CLOSING,
                rationale="The generated CSV declares these source facts.",
            ),
        )

        bs = await get_json(
            client,
            "/reports/balance-sheet",
            as_of_date=today.isoformat(),
            currency=CURRENCY,
        )
        inc = await get_json(
            client,
            "/reports/income-statement",
            start_date=month_start.isoformat(),
            end_date=today.isoformat(),
            currency=CURRENCY,
        )
        oracle = {
            "net_worth": Decimal(str(bs["total_assets"]))
            - Decimal(str(bs["total_liabilities"])),
            "income": Decimal(str(inc["total_income"])),
            "expenses": Decimal(str(inc["total_expenses"])),
        }
        assert oracle == {"net_worth": CLOSING, "income": SALARY, "expenses": RENT}

        answer, metadata, seconds = await _ask(client, QUESTION)
        record_property("assistant_answer_seconds", seconds)
        record_property(
            "assistant_citations",
            ",".join(c.get("source_ref", "") for c in metadata.get("citations", [])),
        )
        assert (
            datetime.fromisoformat(
                (await get_json(client, "/health"))["timestamp"]
            ).date()
            == today
        )
        assert not (misstated := misstated_metrics(answer, oracle)), (
            f"expected {oracle}, found {misstated}. Answer: {answer[:1200]}"
        )
        assert metadata.get("grounded") is True
        cited = {
            c.get("source_ref"): c
            for c in metadata.get("citations", [])
            if isinstance(c, dict)
        }
        for source_ref, href in REPORT_CITATIONS.items():
            citation = cited.get(source_ref)
            assert (
                citation
                and citation.get("href") == href
                and citation.get("confidence_tier") != "UNAVAILABLE"
            )

        refusal, _, refusal_seconds = await _ask(client, OUT_OF_DATA_QUESTION)
        record_property("out_of_data_answer_seconds", refusal_seconds)
        assert says_no_data(refusal) and not topic_claims(refusal)
        invented = money_amounts(refusal) - {
            Decimal("0"),
            OPENING,
            SALARY,
            RENT,
            CLOSING,
            SALARY - RENT,
        }
        assert not invented, f"invented amounts {sorted(invented)}: {refusal[:1200]}"
        checkpoint(record_property, "U14")
