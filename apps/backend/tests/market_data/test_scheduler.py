"""AC11.10: Market data scheduler tests."""

from datetime import datetime

from src.services.market_data_scheduler import MARKET_DATA_SYNC_TZ, next_market_data_sync_at


def test_next_market_data_sync_at_uses_nightly_sgt_schedule() -> None:
    """AC11.10.10: Nightly sync is scheduled for 22:00 Asia/Singapore."""
    before = datetime(2026, 1, 6, 21, 0, tzinfo=MARKET_DATA_SYNC_TZ)
    after = datetime(2026, 1, 6, 23, 0, tzinfo=MARKET_DATA_SYNC_TZ)

    assert next_market_data_sync_at(before) == datetime(2026, 1, 6, 22, 0, tzinfo=MARKET_DATA_SYNC_TZ)
    assert next_market_data_sync_at(after) == datetime(2026, 1, 7, 22, 0, tzinfo=MARKET_DATA_SYNC_TZ)
