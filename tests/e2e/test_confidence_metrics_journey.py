"""Core-journey proof U13: The proportion of low-confidence data is measured (#2370).

Axiom B (vision.md) establishes the North-Star metric:
"The proportion of low-confidence data trends down over time."

This journey proves on the pinned deployed revision that:
* The live correction feedback loop replay endpoint (/api/metrics/correction-loop/replay)
  measures held-out low-confidence proportions (proportion_before and proportion_after)
  as bounded Decimals in [0.00, 1.00].
* The reconciliation statistics endpoint (/api/reconciliation/stats) measures
  the transaction match rate and confidence distribution.
* The system-wide low-confidence proportion is explicitly computed, asserted, and recorded.
"""

from __future__ import annotations

import os
from decimal import Decimal

import httpx
import pytest
from common.testing.ac_proof import ac_proof
from deployment_pin import assert_pinned_deployment, resolve_expected_commit
from journey_checkpoint import checkpoint
from playwright.async_api import Page

APP_URL = os.getenv("APP_URL", "http://localhost:3000")


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


async def _assert_pinned_before_journey(page: Page, record_property) -> None:
    """Prove the pinned deployment before the journey starts (#2370)."""
    expected_version = os.getenv("EXPECTED_SHA")
    assert expected_version, "core-journey proof requires an explicit EXPECTED_SHA"
    expected_commit = resolve_expected_commit(expected_version)
    headers = await _auth_headers(page)
    async with httpx.AsyncClient(
        headers=headers, verify=False, timeout=120.0
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


@ac_proof(
    "confidence-metrics-measured-journey",
    ac_ids=["AC-extraction.1814.4"],
    scope="behavioral",
    ci_tier="post_merge_environment",
    issue="#2370",
    required_markers=["e2e", "journey"],
)
@pytest.mark.e2e
@pytest.mark.journey
async def test_proportion_of_low_confidence_data_is_measured(
    authenticated_page_unique: Page,
    record_property,
) -> None:
    """EPIC-018 AC-extraction.1814.4 / Axiom B: The proportion of low-confidence data is measured.

    Checkpoints proven: U12 (pinned revision), U13 (low-confidence proportion measured).
    """
    page = authenticated_page_unique
    await _assert_pinned_before_journey(page, record_property)

    headers = await _auth_headers(page)
    async with httpx.AsyncClient(
        headers=headers, verify=False, timeout=120.0
    ) as client:
        # 1. Query the live correction feedback loop replay endpoint.
        replay_resp = await client.get(_api_url("/metrics/correction-loop/replay"))
        assert replay_resp.status_code == 200, (
            f"correction loop replay failed: {replay_resp.status_code} {replay_resp.text}"
        )
        replay = replay_resp.json()
        assert "holdout_size" in replay
        assert "grounded" in replay
        assert "proportion_before" in replay
        assert "proportion_after" in replay
        assert "reduced" in replay

        prop_before = Decimal(str(replay["proportion_before"]))
        prop_after = Decimal(str(replay["proportion_after"]))
        assert Decimal("0.00") <= prop_before <= Decimal("1.00")
        assert Decimal("0.00") <= prop_after <= Decimal("1.00")

        # 2. Query reconciliation statistics.
        stats_resp = await client.get(_api_url("/reconciliation/stats"))
        assert stats_resp.status_code == 200, (
            f"reconciliation stats failed: {stats_resp.status_code} {stats_resp.text}"
        )
        stats = stats_resp.json()
        assert "matched_transactions" in stats
        assert "total_transactions" in stats
        assert "match_rate" in stats

        # 3. Query statements to inspect confidence scores.
        stmts_resp = await client.get(_api_url("/statements"))
        assert stmts_resp.status_code == 200, (
            f"statements list failed: {stmts_resp.status_code} {stmts_resp.text}"
        )
        stmts = stmts_resp.json().get("items", [])

        # 4. Compute and measure the proportion of low-confidence data.
        # Under Axiom B, low-confidence statements have score < 50 or failed balance validation.
        low_confidence_statements = sum(
            1
            for s in stmts
            if (
                s.get("confidence_score") is not None and s.get("confidence_score") < 50
            )
            or s.get("balance_validated") is False
        )
        total_statements = len(stmts)
        if total_statements > 0:
            statement_low_confidence_ratio = Decimal(
                low_confidence_statements
            ) / Decimal(total_statements)
        else:
            statement_low_confidence_ratio = Decimal("0.00")

        assert Decimal("0.00") <= statement_low_confidence_ratio <= Decimal("1.00")

        # Record metrics as observable JUnit test properties.
        record_property("replay_proportion_before", str(prop_before))
        record_property("replay_proportion_after", str(prop_after))
        record_property("replay_reduced", str(replay["reduced"]))
        record_property(
            "statement_low_confidence_ratio", str(statement_low_confidence_ratio)
        )
        record_property("reconciliation_match_rate", str(stats.get("match_rate", 0)))

        # 5. Record checkpoint U13.
        checkpoint(record_property, "U13")
