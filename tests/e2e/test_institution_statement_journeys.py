"""Tier 3 provider-backed E2E: per-institution statement journeys (AC-llm.12).

The staging real-LLM corpus proved live extraction on two institution shapes
(DBS full journey, Moomoo/Futu canary) while the fixture toolkit ships
generators/fixtures for seven. These journeys close that data-plane gap: one
minimal upload → parse → approve → balance-sheet journey per uncovered
institution, so provider drift against a statement *shape* (Chinese bank
layout, digital-bank layout, 平安银行) surfaces in the audit-replay corpus
instead of first failing on a real user statement.

Corpus placement: `llm`-marked `post_merge_environment` proofs land in the
non-blocking audit-replay corpus by subtraction (AC8.13.159) — the blocking
canary set is unchanged.

House rules (AC8.13.109): isolated user per test, cookie auth for API calls,
absolute `_api_url(...)` URLs, deterministic waits only.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import time
import uuid
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from common.testing.ac_proof import ac_proof
from common.testing.provider_review import (
    FixtureDisposition,
    approve_statement_with_fixture_review,
)
from conftest import fail_or_skip_ai_ocr_gate
from pdf_fixture_paths import committed_fixture_pdf, generated_pdf_path
from playwright.async_api import Page

APP_URL = os.getenv("APP_URL", "http://localhost:3000")
PARSING_TIMEOUT_MS = int(os.getenv("PARSING_TIMEOUT_MS", "480000"))

GXS_EXPECTED = (
    Path(__file__).resolve().parents[2]
    / "common"
    / "testing"
    / "fixtures"
    / "pdf"
    / "generated"
    / "gxs_statement_fixture_expected.json"
)

CMB_DISPOSITIONS = {
    "工资入账": FixtureDisposition(
        "income", "INCOME", "The CMB fixture declares salary income.", "SALARY"
    ),
    "转账-房租": FixtureDisposition(
        "expense", "EXPENSE", "The CMB fixture declares rent expense.", "RENT"
    ),
    "微信支付-超市": FixtureDisposition(
        "expense", "EXPENSE", "The CMB fixture declares grocery expense.", "GROCERIES"
    ),
    "转账-父母": FixtureDisposition(
        "expense",
        "EXPENSE",
        "The CMB fixture declares family-support expense.",
        "FAMILY_SUPPORT",
    ),
    "报销入账": FixtureDisposition(
        "expense_refund",
        "EXPENSE",
        "The CMB fixture declares an expense reimbursement.",
        "REIMBURSEMENT",
    ),
    "水电费代扣": FixtureDisposition(
        "expense", "EXPENSE", "The CMB fixture declares utility expense.", "UTILITIES"
    ),
    "利息收入": FixtureDisposition(
        "income", "INCOME", "The CMB fixture declares interest income.", "INTEREST"
    ),
}

MARIBANK_DISPOSITIONS = {
    "PayNow to KOPI SHOP PTE LTD": FixtureDisposition(
        "expense", "EXPENSE", "The MariBank fixture declares dining expense.", "DINING"
    ),
    "Interest Credited": FixtureDisposition(
        "income", "INCOME", "The MariBank fixture declares interest income.", "INTEREST"
    ),
    "PayNow to RIDE-HAIL SERVICES": FixtureDisposition(
        "expense",
        "EXPENSE",
        "The MariBank fixture declares transport expense.",
        "TRANSPORT",
    ),
    "Credit Card Repayment": FixtureDisposition(
        "card_repayment",
        "LIABILITY",
        "The MariBank fixture declares a credit-card repayment.",
    ),
    "PayNow from LEE WEI": FixtureDisposition(
        "income",
        "INCOME",
        "The MariBank fixture declares external miscellaneous income.",
        "OTHER_INCOME",
    ),
    "PayNow to ONLINE GROCER": FixtureDisposition(
        "expense",
        "EXPENSE",
        "The MariBank fixture declares grocery expense.",
        "GROCERIES",
    ),
}

PINGAN_DISPOSITIONS = {
    "工资代发": FixtureDisposition(
        "income", "INCOME", "The Pingan fixture declares salary income.", "SALARY"
    ),
    "转账汇款": FixtureDisposition(
        "expense",
        "EXPENSE",
        "The Pingan fixture declares this generated external transfer as family-support expense.",
        "FAMILY_SUPPORT",
    ),
    "快捷支付": FixtureDisposition(
        "expense",
        "EXPENSE",
        "The Pingan fixture declares shopping expense.",
        "SHOPPING",
    ),
    "信用卡还款": FixtureDisposition(
        "card_repayment",
        "LIABILITY",
        "The Pingan fixture declares a credit-card repayment.",
    ),
    "账户结息": FixtureDisposition(
        "income", "INCOME", "The Pingan fixture declares interest income.", "INTEREST"
    ),
    "基金申购": FixtureDisposition(
        "investment_purchase",
        "ASSET",
        "The Pingan fixture declares an investment purchase.",
    ),
    "基金赎回": FixtureDisposition(
        "investment_sale", "ASSET", "The Pingan fixture declares an investment sale."
    ),
}

GXS_DISPOSITIONS = {
    "Interest Earned": FixtureDisposition(
        "income", "INCOME", "The GXS fixture declares interest income.", "INTEREST"
    ),
    "PayNow from ALVIN GOH": FixtureDisposition(
        "income",
        "INCOME",
        "The GXS fixture declares external miscellaneous income.",
        "OTHER_INCOME",
    ),
    "Payment to GrabPay Wallet": FixtureDisposition(
        "expense", "EXPENSE", "The GXS fixture declares transport expense.", "TRANSPORT"
    ),
    "PayNow to MERCHANT HAWKER": FixtureDisposition(
        "expense", "EXPENSE", "The GXS fixture declares dining expense.", "DINING"
    ),
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


def _unique_pdf_copy(src: Path) -> Path:
    """Unique name AND unique content — the backend deduplicates by SHA-256."""
    suffix = int(time.time() * 1000) % 1_000_000
    tmp = Path(tempfile.mkdtemp())
    dest = tmp / f"{src.stem}_{suffix}{src.suffix}"
    shutil.copy2(src, dest)
    with open(dest, "ab") as f:
        f.write(f"\n%% E2E test run {uuid.uuid4()}\n".encode())
    return dest


async def _default_image_model(client: httpx.AsyncClient) -> str:
    response = await client.get(_api_url("/llm/catalog?modality=image"))
    assert response.status_code == 200, (
        f"model catalog request failed: {response.status_code} {response.text}"
    )
    payload = response.json()
    return payload.get("default_model") or payload["models"][0]["id"]


async def _upload_statement_pdf(
    client: httpx.AsyncClient, *, pdf_path: Path, institution: str, model: str
) -> str:
    with pdf_path.open("rb") as fh:
        response = await client.post(
            _api_url("/statements/upload"),
            data={"institution": institution, "model": model},
            files={"file": (pdf_path.name, fh, "application/pdf")},
        )
    assert response.status_code in (200, 201, 202), (
        f"{institution} upload failed: {response.status_code} {response.text}"
    )
    statement_id = response.json().get("id")
    assert statement_id, f"{institution} upload response missing id: {response.text}"
    return str(statement_id)


async def _wait_for_parsed(
    client: httpx.AsyncClient, statement_id: str, *, model: str
) -> dict:
    """Wait for the statement to reach a reviewable-or-further terminal state.

    A high-confidence, balance-valid parse with a detected account skips
    'parsed' entirely and lands directly on 'approved' (route_by_threshold,
    #1780) -- this is intentional auto-post behavior (#1467), not a race, so
    both states count as success. The caller must branch on which one it got:
    an already-'approved' statement must not be posted again.
    """
    deadline = asyncio.get_running_loop().time() + PARSING_TIMEOUT_MS / 1000
    last_payload: dict | None = None
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(_api_url(f"/statements/{statement_id}"))
        assert response.status_code == 200, (
            f"statement poll failed for {statement_id}: {response.status_code} {response.text}"
        )
        last_payload = response.json()
        status = last_payload.get("status")
        if status == "rejected":
            fail_or_skip_ai_ocr_gate(
                f"institution journey rejected statement {statement_id}: {last_payload.get('validation_error')}",
                statement=last_payload,
                model=model,
            )
        if status in ("parsed", "approved"):
            return last_payload
        await asyncio.sleep(5)

    pytest.fail(
        f"statement {statement_id} never reached 'parsed' or 'approved' within {PARSING_TIMEOUT_MS}ms; last payload: {last_payload}"
    )


async def _run_institution_journey(
    page: Page,
    *,
    pdf_path: Path,
    institution: str,
    min_transactions: int,
    dispositions: dict[str, FixtureDisposition],
) -> dict:
    """Upload → parse → approve → balance sheet; returns the parsed payload."""
    headers = await _auth_headers(page)
    async with httpx.AsyncClient(
        headers=headers, verify=False, timeout=120.0
    ) as client:
        model = await _default_image_model(client)
        statement_id = await _upload_statement_pdf(
            client,
            pdf_path=_unique_pdf_copy(pdf_path),
            institution=institution,
            model=model,
        )
        parsed = await _wait_for_parsed(client, statement_id, model=model)

        transactions = parsed.get("transactions") or []
        assert len(transactions) >= min_transactions, (
            f"{institution}: expected >= {min_transactions} extracted transactions, got {len(transactions)}"
        )

        if parsed.get("status") == "approved":
            # High-confidence auto-post (#1467) already approved and posted this
            # statement before we ever observed 'parsed' (#1780) -- calling
            # /review/approve again is safe (auto_create_posted_entries_for_
            # statement is idempotent) but would report journal_entries_created=0
            # since nothing new is left to post, which would fail the assertion
            # below for no real reason. Nothing further to do here.
            pass
        else:
            approval = await approve_statement_with_fixture_review(
                client,
                api_url=_api_url,
                statement_id=statement_id,
                transactions=transactions,
                dispositions=dispositions,
            )
            assert approval.get("status") == "approved"

        report = await client.get(_api_url("/reports/balance-sheet"))
        assert report.status_code == 200, (
            f"{institution} balance sheet failed: {report.status_code} {report.text}"
        )
        assert report.json().get("is_balanced") is True

        return parsed


@ac_proof(
    "cmb-statement-journey",
    ac_ids=["AC-llm.12.1"],
    scope="behavioral",
    ci_tier="post_merge_environment",
    trust_mode="llm_ocr_post_merge",
    source_classes=["bank_statement"],
    mirror_proof_id="extraction-corpus-journeys-pr",
    issue="#1613",
    required_markers=["e2e", "tier3", "critical", "llm"],
)
@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.llm
async def test_cmb_statement_journey(authenticated_page_unique: Page) -> None:
    """EPIC-003 EPIC-008 / AC-llm.12.1: CMB (Chinese bank layout) journey."""
    await _run_institution_journey(
        authenticated_page_unique,
        pdf_path=generated_pdf_path("cmb"),
        institution="CMB E2E Institution Journey",
        min_transactions=1,
        dispositions=CMB_DISPOSITIONS,
    )


@ac_proof(
    "maribank-statement-journey",
    ac_ids=["AC-llm.12.2"],
    scope="behavioral",
    ci_tier="post_merge_environment",
    trust_mode="llm_ocr_post_merge",
    source_classes=["bank_statement"],
    mirror_proof_id="extraction-corpus-journeys-pr",
    issue="#1613",
    required_markers=["e2e", "tier3", "critical", "llm"],
)
@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.llm
async def test_maribank_statement_journey(authenticated_page_unique: Page) -> None:
    """EPIC-003 EPIC-008 / AC-llm.12.2: MariBank (digital bank) journey."""
    await _run_institution_journey(
        authenticated_page_unique,
        pdf_path=generated_pdf_path("mari"),
        institution="MariBank E2E Institution Journey",
        min_transactions=1,
        dispositions=MARIBANK_DISPOSITIONS,
    )


@ac_proof(
    "pingan-statement-journey",
    ac_ids=["AC-llm.12.3"],
    scope="behavioral",
    ci_tier="post_merge_environment",
    trust_mode="llm_ocr_post_merge",
    source_classes=["bank_statement"],
    mirror_proof_id="extraction-corpus-journeys-pr",
    issue="#1613",
    required_markers=["e2e", "tier3", "critical", "llm"],
)
@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.llm
async def test_pingan_statement_journey(authenticated_page_unique: Page) -> None:
    """EPIC-003 EPIC-008 / AC-llm.12.3: 平安银行 (Chinese layout) journey."""
    await _run_institution_journey(
        authenticated_page_unique,
        pdf_path=generated_pdf_path("pingan"),
        institution="Pingan E2E Institution Journey",
        min_transactions=1,
        dispositions=PINGAN_DISPOSITIONS,
    )


@ac_proof(
    "gxs-statement-journey-graded",
    ac_ids=["AC-llm.12.4"],
    scope="behavioral",
    ci_tier="post_merge_environment",
    trust_mode="llm_ocr_post_merge",
    source_classes=["bank_statement"],
    mirror_proof_id="extraction-corpus-journeys-pr",
    issue="#1613",
    required_markers=["e2e", "tier3", "critical", "llm"],
)
@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.llm
async def test_gxs_statement_journey_matches_expected_balances(
    authenticated_page_unique: Page,
) -> None:
    """EPIC-003 EPIC-008 / AC-llm.12.4: GXS journey graded against truth.

    GXS ships as a committed PDF + expected-JSON pair, so this journey grades
    the live extraction: opening/closing balances must match the expected
    values exactly (Decimal), and the row count must reach the expected count.
    """
    expected = json.loads(GXS_EXPECTED.read_text())
    expected_stmt = expected["statement"]
    expected_count = len(expected["events"])

    parsed = await _run_institution_journey(
        authenticated_page_unique,
        pdf_path=committed_fixture_pdf("gxs_statement_fixture.pdf"),
        institution="GXS E2E Institution Journey",
        min_transactions=expected_count,
        dispositions=GXS_DISPOSITIONS,
    )

    assert Decimal(str(parsed["opening_balance"])) == Decimal(
        expected_stmt["opening_balance"]
    ), (
        f"GXS opening balance drifted: {parsed['opening_balance']} != {expected_stmt['opening_balance']}"
    )
    assert Decimal(str(parsed["closing_balance"])) == Decimal(
        expected_stmt["closing_balance"]
    ), (
        f"GXS closing balance drifted: {parsed['closing_balance']} != {expected_stmt['closing_balance']}"
    )
