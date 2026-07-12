"""North-Star metric: low-confidence-data proportion over time (EPIC-018 AC18.12).

Vision names a single North-Star Metric — "the proportion of low-confidence data
trends down over time" — and calls it the single measurable expression of the
axioms. These tests pin the instrument: a deterministic proportion over the
ledger facts that back reports, recorded as an append-only series so the trend
is observable.
"""

from decimal import Decimal

import pytest

from src.models.journal import JournalEntrySourceType
from src.reporting.extension.confidence_metric import ConfidenceMetricService
from tests.ledger._ledger_helpers import create_valid_posted_entry


@pytest.mark.asyncio
async def test_AC18_12_1_low_confidence_proportion_and_tier_breakdown_are_deterministic(db, test_user):
    """AC-reporting.north-star.1: AC18.12.1: The metric is the LOW-tier share of posted ledger facts, with a full tier breakdown."""
    service = ConfidenceMetricService()
    # source_type -> confidence tier: manual=TRUSTED, user_confirmed=HIGH,
    # auto_matched=MEDIUM, auto_parsed/system=LOW.
    for source_type in (
        JournalEntrySourceType.MANUAL,
        JournalEntrySourceType.USER_CONFIRMED,
        JournalEntrySourceType.AUTO_MATCHED,
        JournalEntrySourceType.AUTO_PARSED,
        JournalEntrySourceType.AUTO_PARSED,
        JournalEntrySourceType.SYSTEM,
    ):
        await create_valid_posted_entry(db, test_user.id, source_type=source_type)

    result = await service.compute(db, test_user.id)

    assert result.total_count == 6
    assert result.low_confidence_count == 3  # 2x auto_parsed + 1x system
    assert result.low_confidence_proportion == Decimal("0.5")
    assert result.tier_breakdown == {"TRUSTED": 1, "HIGH": 1, "MEDIUM": 1, "LOW": 3}


@pytest.mark.asyncio
async def test_AC18_12_1_empty_ledger_reports_zero_not_undefined(db, test_user):
    """AC18.12.1: With no ledger facts the proportion is a defined 0, never a divide-by-zero."""
    result = await ConfidenceMetricService().compute(db, test_user.id)
    assert result.total_count == 0
    assert result.low_confidence_count == 0
    assert result.low_confidence_proportion == Decimal("0")


@pytest.mark.asyncio
async def test_AC18_12_2_metric_is_recorded_as_append_only_series_showing_the_trend(db, test_user):
    """AC-reporting.north-star.2: AC18.12.2: Snapshots accumulate (never overwrite) and read newest-first, so the trend is observable."""
    service = ConfidenceMetricService()

    await create_valid_posted_entry(db, test_user.id, source_type=JournalEntrySourceType.MANUAL)
    await create_valid_posted_entry(db, test_user.id, source_type=JournalEntrySourceType.AUTO_PARSED)
    first = await service.record_snapshot(db, test_user.id)
    await db.commit()
    assert first.low_confidence_proportion == Decimal("0.5")  # 1 LOW of 2

    # Trust improves: add two TRUSTED facts and record again.
    await create_valid_posted_entry(db, test_user.id, source_type=JournalEntrySourceType.MANUAL)
    await create_valid_posted_entry(db, test_user.id, source_type=JournalEntrySourceType.MANUAL)
    second = await service.record_snapshot(db, test_user.id)
    await db.commit()
    assert second.low_confidence_proportion == Decimal("0.25")  # 1 LOW of 4

    series = await service.list_snapshots(db, test_user.id)
    assert [s.low_confidence_proportion for s in series] == [Decimal("0.25"), Decimal("0.5")]
    # The earlier point is preserved unedited (append-only, not overwritten).
    assert series[-1].id == first.id
    assert series[-1].low_confidence_proportion == Decimal("0.5")


@pytest.mark.asyncio
async def test_AC18_12_3_north_star_endpoint_returns_current_and_series(client):
    """AC-reporting.north-star.3: AC18.12.3: The metric and its series are exposed read-only via the API."""
    response = await client.get("/metrics/confidence-north-star")
    assert response.status_code == 200
    body = response.json()
    assert "current" in body and "series" in body
    assert body["current"]["total_count"] == 0
    assert body["current"]["low_confidence_count"] == 0
    assert isinstance(body["series"], list)


@pytest.mark.asyncio
async def test_AC18_12_4_post_records_a_snapshot_into_the_series(client):
    """AC-reporting.north-star.4: AC18.12.4: POST records a North-Star point on demand, so the trend accumulates."""
    assert (await client.get("/metrics/confidence-north-star")).json()["series"] == []

    created = await client.post("/metrics/confidence-north-star/snapshots")
    assert created.status_code == 201
    assert created.json()["captured_at"]

    series = (await client.get("/metrics/confidence-north-star")).json()["series"]
    assert len(series) == 1
