"""Correction feedback loop: the replay is observable read-only (EPIC-018 AC18.14, #931).

AC18.12 makes the thermometer (the low-confidence proportion) observable; this
endpoint makes the furnace observable — the held-out replay of the live correction
corpus, so the loop's effect on the proportion is auditable. It adds no second
source of truth: the corpus is still a projection of `CorrectionLog`.
"""

import pytest


@pytest.mark.asyncio
async def test_AC18_14_4_replay_endpoint_surfaces_the_loop_effect(client):
    """AC18.14.4: the held-out replay result is exposed read-only via the API."""
    response = await client.get("/metrics/correction-loop/replay")
    assert response.status_code == 200
    body = response.json()
    # Empty corpus is a defined, observable zero — never a divide-by-zero.
    assert body["holdout_size"] == 0
    assert body["grounded"] == 0
    assert body["reduced"] is False
    assert body["proportion_before"] == "0"
    assert body["proportion_after"] == "0"
