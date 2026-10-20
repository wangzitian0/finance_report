"""Core-journey proof U14: the assistant answers from the data of the user (#2461).

One isolated user records an opening balance of 10,000.00 and uploads one statement of the current
month: a salary of +5,000.00 and a rent of -1,500.00. The user approves the statement and asks the
assistant for the net worth, the income and the expenses. The test then proves on the pinned
deployed revision that:

* the reports (the oracle) equal the independent Decimal facts of the fixture: net worth 13,500.00,
  income 5,000.00 and expenses 1,500.00;
* the answer states each report amount after its own label, so an answer that swaps two amounts, or
  a wrong headline followed by correct prose, fails;
* the grounding header ``X-Advisor-Metadata`` is grounded and cites the balance sheet and the income
  statement. The service builds this header from the question and the report state before the model
  runs, so it proves the header contract on the deployment, not the use of the data. The amount
  check proves the use of the data;
* a question about a period with no data (dining in March 2019) gets an answer that says so in a
  sentence about that subject. No sentence about that subject states an amount, and the answer
  states no amount that is not in the data of the user.

The assistant reads the balance sheet of today and the income statement of the current month
(``_get_financial_summary_context``), so the statement uses the current month of the server.
"""

from __future__ import annotations

import asyncio
import calendar
import json
import os
import time
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from assistant_answer import (
    ANSWER_TIMEOUT_SECONDS,
    CSV_PARSE_TIMEOUT_SECONDS,
    OUT_OF_DATA_QUESTION,
    QUESTION,
    misstated_metrics,
    money_amounts,
    says_no_data,
    topic_sentences_with_amounts,
)
from common.testing.ac_proof import ac_proof
from common.testing.provider_review import (
    FixtureDisposition,
    FixtureEnvelope,
    approve_statement_with_fixture_review,
)
from deployment_pin import assert_pinned_deployment, resolve_expected_commit
from journey_checkpoint import checkpoint
from playwright.async_api import Page

APP_URL = os.getenv("APP_URL", "http://localhost:3000")
POLL_SECONDS = 0.5

CURRENCY = "SGD"
OPENING = Decimal("10000.00")
SALARY = Decimal("5000.00")
RENT = Decimal("1500.00")
CLOSING = OPENING + SALARY - RENT

CSV_HEADER = (
    "Statement Currency,Statement Period Start,Statement Period End,"
    "Statement Opening Balance,Statement Closing Balance,Date,Description,Amount"
)
DISPOSITIONS = {
    "Salary Credit ACME": FixtureDisposition(
        "income", "INCOME", "Monthly salary credit", "SALARY"
    ),
    "Rent Payment Landlord": FixtureDisposition(
        "expense", "EXPENSE", "Monthly rent expense", "HOUSING"
    ),
}
# The citations that tie the answer to the two reports of the oracle.
REPORT_CITATIONS = {
    "balance_sheet.total_equity": "/reports/balance-sheet",
    "income_statement.current_month": "/reports/income-statement",
}


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


async def _get(client: httpx.AsyncClient, path: str, **params) -> dict:
    response = await client.get(_api_url(path), params=params or None)
    assert response.status_code == 200, (
        f"GET {path} failed: {response.status_code} {response.text}"
    )
    return response.json()


async def _server_today(client: httpx.AsyncClient) -> date:
    health = await _get(client, "/health")
    return datetime.fromisoformat(health["timestamp"]).date()


async def _wait_for_parsed(client: httpx.AsyncClient, statement_id: str) -> dict:
    """Wait for the deterministic CSV parse. No provider parses a CSV, so the wait is short.

    The httpx timeout limits each request, so ``asyncio.timeout`` limits the whole wait.
    """
    statement: dict = {}
    try:
        async with asyncio.timeout(CSV_PARSE_TIMEOUT_SECONDS):
            while True:
                statement = await _get(client, f"/statements/{statement_id}")
                if statement.get("status") in ("parsed", "approved", "rejected"):
                    return statement
                await asyncio.sleep(POLL_SECONDS)
    except TimeoutError:
        pytest.fail(
            f"statement {statement_id} did not parse within {CSV_PARSE_TIMEOUT_SECONDS} s: {statement}"
        )


async def _ask(client: httpx.AsyncClient, question: str) -> tuple[str, dict, float]:
    """Send one question. Return the answer, the grounding header and the seconds.

    The httpx timeout limits each read of the stream, so ``wait_for`` limits the whole answer.
    """
    started = time.monotonic()
    try:
        response = await asyncio.wait_for(
            client.post(
                _api_url("/chat"),
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
    assert response.status_code == 200, (
        f"POST /chat failed for {question!r}: {response.status_code} {response.text}"
    )
    # A finished answer always ends with the disclaimer. An empty body means that the
    # provider stream failed before its first chunk, after the server sent HTTP 200.
    assert response.text.strip(), (
        f"the assistant sent HTTP 200 with an empty body after {seconds} s for {question!r}: "
        "the provider stream failed before its first chunk, and the AI service may be unavailable"
    )
    raw_metadata = response.headers.get("X-Advisor-Metadata")
    assert raw_metadata, f"the answer has no X-Advisor-Metadata header: {response.text}"
    return response.text, json.loads(raw_metadata), seconds


@ac_proof(
    "assistant-answers-from-the-data-of-the-user",
    ac_ids=["AC-advisor.grounding.3"],
    scope="behavioral",
    ci_tier="post_merge_environment",
    issue="#2461",
    required_markers=["e2e", "tier3", "critical", "llm"],
)
@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.llm
async def test_assistant_answers_from_the_data_of_the_user(
    authenticated_page_unique: Page, record_property
) -> None:
    """EPIC-021 EPIC-008: AC-advisor.grounding.3, the answer of the assistant equals the reports.

    Checkpoints proven: U12 (pinned revision), U14 (the assistant answers from the data of the user).
    """
    expected_version = os.getenv("EXPECTED_SHA")
    assert expected_version, (
        "the assistant chat proof requires an explicit EXPECTED_SHA"
    )
    expected_commit = resolve_expected_commit(expected_version)
    record_property("expected_version", expected_version)

    headers = await _auth_headers(authenticated_page_unique)
    async with httpx.AsyncClient(
        headers=headers, verify=False, timeout=120.0
    ) as client:
        health = await _get(client, "/health")
        assert_pinned_deployment(health, expected_version, expected_commit)
        frontend = await client.get(f"{APP_URL.rstrip('/')}/frontend-version.json")
        assert frontend.status_code == 200, (
            "frontend deployment version must be observable"
        )
        assert_pinned_deployment(frontend.json(), expected_version, expected_commit)
        checkpoint(record_property, "U12")

        # The assistant reads the current month of the server, so the statement uses it too.
        today = datetime.fromisoformat(health["timestamp"]).date()
        month_start = today.replace(day=1)
        month_end = month_start.replace(
            day=calendar.monthrange(month_start.year, month_start.month)[1]
        )
        record_property("server_today", today.isoformat())

        account = await client.post(
            _api_url("/accounts"),
            json={
                "name": "Assistant Journey Savings",
                "type": "ASSET",
                "currency": CURRENCY,
            },
        )
        assert account.status_code == 201, account.text
        account_id = account.json()["id"]
        opening = await client.post(
            _api_url("/accounts/opening-balances"),
            json={
                "entry_date": (month_start - timedelta(days=1)).isoformat(),
                "balances": {account_id: str(OPENING)},
                "currency": CURRENCY,
                "memo": "Opening cash before the assistant journey statement",
            },
        )
        assert opening.status_code == 201, opening.text

        rows = (("Salary Credit ACME", SALARY), ("Rent Payment Landlord", -RENT))
        csv_text = "\n".join(
            [
                CSV_HEADER,
                *(
                    f"{CURRENCY},{month_start},{month_end},{OPENING},{CLOSING},"
                    f"{month_start},{description},{amount}"
                    for description, amount in rows
                ),
                "",
            ]
        )
        upload = await client.post(
            _api_url("/statements/upload"),
            data={"institution": "Assistant Journey Bank", "account_id": account_id},
            files={
                "file": (
                    f"assistant_{uuid.uuid4().hex[:6]}.csv",
                    csv_text.encode("utf-8"),
                    "text/csv",
                )
            },
        )
        assert upload.status_code in (200, 201, 202), upload.text
        statement_id = upload.json()["id"]
        parsed = await _wait_for_parsed(client, statement_id)
        assert len(parsed["transactions"]) == len(rows), parsed
        approval = await approve_statement_with_fixture_review(
            client,
            api_url=_api_url,
            statement_id=statement_id,
            transactions=parsed["transactions"],
            dispositions=DISPOSITIONS,
            envelope=FixtureEnvelope(
                currency=CURRENCY,
                period_start=month_start,
                period_end=month_end,
                opening_balance=OPENING,
                closing_balance=CLOSING,
                rationale="The generated CSV declares these source facts.",
            ),
        )
        assert approval["status"] == "approved", approval

        # The reports are the oracle. They must first equal the independent facts of the fixture.
        balance_sheet = await _get(
            client,
            "/reports/balance-sheet",
            as_of_date=today.isoformat(),
            currency=CURRENCY,
        )
        income_statement = await _get(
            client,
            "/reports/income-statement",
            start_date=month_start.isoformat(),
            end_date=today.isoformat(),
            currency=CURRENCY,
        )
        oracle = {
            "net_worth": Decimal(str(balance_sheet["total_assets"]))
            - Decimal(str(balance_sheet["total_liabilities"])),
            "income": Decimal(str(income_statement["total_income"])),
            "expenses": Decimal(str(income_statement["total_expenses"])),
        }
        assert oracle == {"net_worth": CLOSING, "income": SALARY, "expenses": RENT}, (
            f"the reports do not equal the fixture facts: {oracle}"
        )

        answer, metadata, seconds = await _ask(client, QUESTION)
        record_property("assistant_answer_seconds", seconds)
        record_property(
            "assistant_citations",
            ",".join(c.get("source_ref", "") for c in metadata.get("citations", [])),
        )
        assert await _server_today(client) == today, (
            "the server date changed during the journey, so the assistant read another period"
        )

        misstated = misstated_metrics(answer, oracle)
        assert not misstated, (
            f"the answer does not state the report amount after its label: expected {oracle}, "
            f"found {misstated}. Answer: {answer[:1200]}"
        )
        assert metadata.get("grounded") is True, f"grounding header: {metadata}"
        cited = {
            c.get("source_ref"): c
            for c in metadata.get("citations", [])
            if isinstance(c, dict)
        }
        for source_ref, href in REPORT_CITATIONS.items():
            citation = cited.get(source_ref)
            assert citation, (
                f"the grounding header does not cite {source_ref}: {metadata}"
            )
            assert citation.get("href") == href, citation
            assert citation.get("confidence_tier") != "UNAVAILABLE", (
                f"the cited report was not available to the assistant: {citation}"
            )

        # A period with no data: the answer says so and invents no money amount.
        refusal, _, refusal_seconds = await _ask(client, OUT_OF_DATA_QUESTION)
        record_property("out_of_data_answer_seconds", refusal_seconds)
        assert says_no_data(refusal), (
            f"no sentence about the subject of the question says that the data holds no answer: "
            f"{refusal[:1200]}"
        )
        claims = topic_sentences_with_amounts(refusal)
        assert not claims, (
            f"a sentence about the subject of a question with no data states an amount: {claims}"
        )
        data_amounts = {
            Decimal("0"),
            OPENING,
            SALARY,
            RENT,
            CLOSING,
            SALARY - RENT,
        }
        invented = money_amounts(refusal) - data_amounts
        assert not invented, (
            f"the answer about a period with no data states amounts that are not in the data "
            f"{sorted(invented)}: {refusal[:1200]}"
        )
        checkpoint(record_property, "U14")
