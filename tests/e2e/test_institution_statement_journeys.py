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
import csv
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from common.testing.ac_proof import ac_proof
from common.testing import money_amount
from common.testing.provider_review import (
    FixtureDisposition,
    approve_statement_with_fixture_review,
)
from conftest import fail_or_skip_ai_ocr_gate
from pdf_fixture_paths import committed_fixture_pdf, generated_pdf_path
from playwright.async_api import Page, expect

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
    record_property: Callable[[str, object], None] | None = None,
) -> dict:
    """Upload → parse → approve → balance sheet; returns the parsed payload."""
    headers = await _auth_headers(page)
    async with httpx.AsyncClient(
        headers=headers, verify=False, timeout=120.0
    ) as client:
        model = await _default_image_model(client)
        if record_property:
            record_property("selected_ocr_model", model)
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
            if record_property:
                record_property("required_economic_review_decisions", 0)
                record_property("required_statement_approvals", 0)
                record_property("statement_approval_api_attempts", 0)
        else:
            approval = await approve_statement_with_fixture_review(
                client,
                api_url=_api_url,
                statement_id=statement_id,
                transactions=transactions,
                dispositions=dispositions,
            )
            assert approval.get("status") == "approved"
            if record_property:
                record_property(
                    "required_economic_review_decisions",
                    approval.get("reviewed_dispositions", 0),
                )
                record_property("required_statement_approvals", 1)
                record_property(
                    "statement_approval_api_attempts",
                    2 if approval.get("reviewed_dispositions", 0) else 1,
                )

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
    ac_ids=["AC-llm.12.4", "AC-testing.package-lifecycle.2"],
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
    record_property,
) -> None:
    """EPIC-003 EPIC-008 / AC-llm.12.4 AC-testing.package-lifecycle.2.

    GXS ships as a committed PDF + expected-JSON pair, so this journey grades
    the live extraction: opening/closing balances must match the expected
    values exactly (Decimal), and the row count must reach the expected count.
    """
    started = time.monotonic()
    expected = json.loads(GXS_EXPECTED.read_text())
    expected_stmt = expected["statement"]
    expected_count = len(expected["events"])

    parsed = await _run_institution_journey(
        authenticated_page_unique,
        pdf_path=committed_fixture_pdf("gxs_statement_fixture.pdf"),
        institution="GXS E2E Institution Journey",
        min_transactions=expected_count,
        dispositions=GXS_DISPOSITIONS,
        record_property=record_property,
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
    await _assert_saved_gxs_package(
        authenticated_page_unique,
        parsed=parsed,
        expected=expected,
        record_property=record_property,
    )
    record_property("happy_flow_elapsed_seconds", round(time.monotonic() - started, 2))


async def _assert_saved_gxs_package(
    page: Page, *, parsed: dict, expected: dict, record_property
) -> None:
    """Continue the supported source through the public immutable-package API."""
    headers = await _auth_headers(page)
    source = expected["statement"]
    expected_version = os.getenv("EXPECTED_SHA")
    assert expected_version, (
        "complete live happy-flow proof requires an explicit EXPECTED_SHA"
    )
    resolved_commit = subprocess.run(
        [
            "git",
            "rev-parse",
            "--verify",
            "--end-of-options",
            f"{expected_version}^{{commit}}",
        ],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        check=False,
    )
    # The post-merge gate checks out a shallow commit, so the release tag need
    # not exist locally. Exact release strings remain sufficient; mixed tag/SHA
    # comparison is allowed only when we can resolve their commit identity.
    expected_commit = (
        resolved_commit.stdout.strip() if resolved_commit.returncode == 0 else None
    )
    record_property("expected_version", expected_version)
    record_property("expected_commit", expected_commit)
    async with httpx.AsyncClient(
        headers=headers, verify=False, timeout=120.0
    ) as client:
        health = await client.get(_api_url("/health"))
        assert health.status_code == 200
        _assert_pinned_deployment(health.json(), expected_version, expected_commit)
        record_property("backend_version", health.json().get("git_sha"))
        frontend = await client.get(f"{APP_URL.rstrip('/')}/frontend-version.json")
        record_property("frontend_version_http_status", frontend.status_code)
        assert frontend.status_code == 200, (
            "frontend deployment version must be observable"
        )
        _assert_pinned_deployment(frontend.json(), expected_version, expected_commit)
        frontend_version = frontend.json().get("git_sha")
        assert frontend_version, "frontend deployment must identify its actual build"
        record_property("frontend_version", frontend_version)
        expected_transactions = sorted(
            (row["date"], Decimal(row["amount"]), row["direction"], row["currency"])
            for row in expected["events"]
        )
        actual_transactions = sorted(
            (row["txn_date"], Decimal(row["amount"]), row["direction"], row["currency"])
            for row in parsed["transactions"]
        )
        assert actual_transactions == expected_transactions, (
            "source transaction facts must match the independent fixture"
        )

        readiness = await client.get(_api_url("/accounts/opening-balance-readiness"))
        assert readiness.status_code == 200
        needs_opening = readiness.json()["needs_opening_balance"]
        record_property("required_opening_balance_confirmations", int(needs_opening))
        if needs_opening:
            # A successful parse/transaction review does not establish opening
            # equity. Use the same explicit guided action as the product UI.
            current = await client.get(_api_url(f"/statements/{parsed['id']}"))
            assert current.status_code == 200
            account_id = current.json()["account_id"]
            assert account_id
            opening = await client.post(
                _api_url("/accounts/opening-balances"),
                json={
                    # The brought-forward balance precedes this month's cash
                    # events, as in the deterministic trusted-year scenario.
                    "entry_date": (
                        date.fromisoformat(source["period_start"]) - timedelta(days=1)
                    ).isoformat(),
                    "balances": {account_id: source["opening_balance"]},
                    "currency": source["currency"],
                    "memo": "GXS fixture source-declared opening balance",
                },
            )
            assert opening.status_code == 201, (
                f"guided opening balance HTTP {opening.status_code}"
            )

        ledger_response = await client.get(_api_url("/journal-entries?limit=100"))
        assert ledger_response.status_code == 200
        entries = ledger_response.json()["items"]
        for transaction in parsed["transactions"]:
            effects = [
                entry for entry in entries if entry["source_id"] == transaction["id"]
            ]
            assert len(effects) == 1, (
                "each source transaction must have one ledger effect"
            )
            assert effects[0]["status"] == "posted"
            assert effects[0]["decision_anchor_id"], (
                "posted source must retain its authority anchor"
            )

        period = {
            "start_date": source["period_start"],
            "end_date": source["period_end"],
            "as_of_date": source["period_end"],
            "currency": source["currency"],
        }
        generated = await client.post(
            _api_url("/reports/package/generate"), json=period
        )
        assert generated.status_code == 200, (
            f"package generation HTTP {generated.status_code}"
        )
        snapshot = generated.json()
        document = snapshot["document"]
        blockers = [item["code"] for item in document["readiness"]["blockers"]]
        assert snapshot["status"] == "trusted", f"package trust blocked by: {blockers}"
        assert document["snapshot_id"] == snapshot["id"]
        assert document["package_decision_id"]
        assert document["input_manifest"]
        assert all(item["decision_id"] for item in document["input_manifest"])
        manifest_refs = {
            reference
            for item in document["input_manifest"]
            for reference in item["input_refs"]
        }
        source_review = await client.get(_api_url(f"/statements/{parsed['id']}/review"))
        assert source_review.status_code == 200
        source_digest = source_review.json()["source_result_digest"]
        assert source_digest
        source_manifest = [
            item
            for item in document["input_manifest"]
            if any(
                reference.startswith("statement_result:")
                for reference in item["input_refs"]
            )
        ]
        assert len(source_manifest) == 1
        assert source_manifest[0]["target_kind"] == "statement_extraction_result"
        assert source_manifest[0]["target_version"] == source_digest
        assert f"account:{source_review.json()['account_id']}" in manifest_refs
        assert any(
            reference.startswith("source_document:")
            for reference in source_manifest[0]["input_refs"]
        )
        assert {f"journal_entry:{entry['id']}" for entry in entries} <= manifest_refs
        for key, value in period.items():
            assert snapshot[key] == value
        sections = document["sections"]
        expected_income = sum(
            (
                Decimal(row["amount"])
                for row in expected["events"]
                if row["direction"] == "IN"
            ),
            Decimal("0"),
        )
        expected_expenses = sum(
            (
                Decimal(row["amount"])
                for row in expected["events"]
                if row["direction"] == "OUT"
            ),
            Decimal("0"),
        )
        assert (
            money_amount(
                sections["income_statement"]["total_income"], source["currency"]
            )
            == expected_income
        )
        assert (
            money_amount(
                sections["income_statement"]["total_expenses"], source["currency"]
            )
            == expected_expenses
        )
        assert (
            money_amount(sections["income_statement"]["net_income"], source["currency"])
            == expected_income - expected_expenses
        )
        assert money_amount(
            sections["balance_sheet"]["total_assets"], source["currency"]
        ) == Decimal(source["closing_balance"])
        assert sections["balance_sheet"]["is_balanced"] is True
        assert money_amount(
            sections["cash_flow"]["summary"]["ending_cash"], source["currency"]
        ) == Decimal(source["closing_balance"])
        assert sections["cash_flow"]["proof_state"] == "proven"

        listed = await client.get(_api_url("/reports/package/snapshots"))
        assert listed.status_code == 200
        assert snapshot["id"] in {item["id"] for item in listed.json()}
        selected_path = _api_url(f"/reports/package/snapshots/{snapshot['id']}")
        reopened = await client.get(selected_path)
        assert reopened.status_code == 200
        assert reopened.json()["document"] == document
        exported_json = await client.get(f"{selected_path}/export?format=json")
        assert exported_json.status_code == 200
        assert exported_json.json()["document"] == document
        exported_csv = await client.get(f"{selected_path}/export?format=csv")
        assert exported_csv.status_code == 200
        csv_rows = list(csv.DictReader(io.StringIO(exported_csv.text)))
        assert csv_rows, "saved CSV must contain report lines"
        trace_lines = sections["traceability_appendix"]["lines"]
        assert {row["line_id"] for row in csv_rows} == {
            line["line_id"] for line in trace_lines
        }
        expected_refs = "|".join(
            sorted(
                f"{item['decision_id']}@{reference}"
                for item in document["input_manifest"]
                for reference in item["input_refs"]
            )
        )
        assert all(
            row["input_decision_references"] == expected_refs for row in csv_rows
        )
        csv_amounts = {
            row["line_id"]: Decimal(row["amount"]) for row in csv_rows if row["amount"]
        }
        assert csv_amounts["balance_sheet.total_assets"] == Decimal(
            source["closing_balance"]
        )
        assert csv_amounts["income_statement.total_income"] == expected_income
        assert csv_amounts["income_statement.total_expenses"] == expected_expenses

        await _post_later_gxs_income(
            client,
            source=source,
            cash_account_id=source_review.json()["account_id"],
            expected_income=expected_income,
        )
        assert (await client.get(selected_path)).json()["document"] == document
        assert (
            await client.get(f"{selected_path}/export?format=json")
        ).content == exported_json.content
        assert (
            await client.get(f"{selected_path}/export?format=csv")
        ).content == exported_csv.content
        await _assert_gxs_snapshot_browser(
            page,
            snapshot=snapshot,
            json_bytes=exported_json.content,
            csv_bytes=exported_csv.content,
        )
        record_property("saved_package_browser_interactions", 5)


def _assert_pinned_deployment(
    payload: dict, expected_version: str, expected_commit: str | None
) -> None:
    """Release tags must match exactly; an observed SHA must name their commit."""
    observed = [payload.get("git_sha"), payload.get("version")]
    assert all(observed), "deployed service must publish version and git_sha"
    for version in observed:
        assert version == expected_version or (
            expected_commit
            and re.fullmatch(r"[0-9a-f]{7,40}", version)
            and expected_commit.startswith(version)
        ), f"deployed version {version} does not match pinned target {expected_version}"


async def _post_later_gxs_income(
    client: httpx.AsyncClient,
    *,
    source: dict,
    cash_account_id: str,
    expected_income: Decimal,
) -> None:
    """Change a live financial total through normal posting before reopening."""
    accounts = await client.get(_api_url("/accounts?limit=100"))
    assert accounts.status_code == 200
    income_account = next(
        (item for item in accounts.json()["items"] if item["type"] == "INCOME"),
        None,
    )
    assert income_account is not None, (
        "fixture economic review must create an INCOME counter-account before "
        "the post-snapshot income check"
    )
    draft = await client.post(
        _api_url("/journal-entries"),
        json={
            "entry_date": source["period_end"],
            "memo": "Later independent fixture income",
            "rationale": "Generated post-snapshot change verifies frozen artifact stability.",
            "lines": [
                {
                    "account_id": cash_account_id,
                    "direction": "DEBIT",
                    "amount": "1.00",
                    "currency": source["currency"],
                },
                {
                    "account_id": income_account["id"],
                    "direction": "CREDIT",
                    "amount": "1.00",
                    "currency": source["currency"],
                },
            ],
        },
    )
    assert draft.status_code == 201
    posted = await client.post(
        _api_url(f"/journal-entries/{draft.json()['id']}/postings")
    )
    assert posted.status_code == 200
    live = await client.get(
        _api_url("/reports/income-statement"),
        params={
            "start_date": source["period_start"],
            "end_date": source["period_end"],
            "currency": source["currency"],
        },
    )
    assert live.status_code == 200
    assert money_amount(
        live.json()["total_income"], source["currency"]
    ) == expected_income + Decimal("1.00")


async def _assert_gxs_snapshot_browser(
    page: Page, *, snapshot: dict, json_bytes: bytes, csv_bytes: bytes
) -> None:
    """The saved artifact must also be selectable and downloadable by its user."""
    response = await page.goto(f"{APP_URL.rstrip('/')}/reports/package")
    assert response is not None and response.status == 200, (
        "report package page must render"
    )
    await page.get_by_label("Package report date").fill(snapshot["end_date"])
    await page.get_by_role("button", name="US-like", exact=True).click()
    await expect(
        page.get_by_role("heading", name="Saved Package Artifacts")
    ).to_be_visible()
    row = page.get_by_role("row").filter(
        has_text=f"{snapshot['start_date']} to {snapshot['end_date']}"
    )
    await expect(row).to_have_count(1)
    await row.get_by_role("button", name="Reopen", exact=True).click()
    identity = page.get_by_role("region", name="Package document identity")
    await expect(identity).to_contain_text(f"Frozen snapshot {snapshot['id']}")
    await expect(identity).to_contain_text("Trusted")
    for format_name, expected_bytes in (("JSON", json_bytes), ("CSV", csv_bytes)):
        async with page.expect_download() as download_info:
            await row.get_by_role("button", name=re.compile(format_name)).click()
        download = await download_info.value
        path = await download.path()
        assert path is not None
        assert Path(path).read_bytes() == expected_bytes
