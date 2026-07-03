"""Repro for #1389 — brokerage position identifier prefers a free-text name over the ticker.

Synthetic data only. When the vision model emits a company name in
`asset_identifier` and the real ticker in `symbol`, the name wins (it is first in
the precedence chain at brokerage_positions.py). Downstream market-data sync then
uses the name as its lookup scope and never resolves a price.
"""

from __future__ import annotations

from datetime import date


def test_brokerage_position_prefers_ticker_over_company_name():
    from src.extraction.extension.brokerage_positions import _parse_structured_positions

    payload = {
        "currency": "USD",
        "positions": [
            {
                # The model put a human-readable name here instead of the symbol.
                "asset_identifier": "Synthetic Chips Incorporated",
                "symbol": "SYNC",  # the actual ticker the model also returned
                "quantity": "100",
                "market_value": "12345.00",
                "currency": "USD",
            }
        ],
    }

    snapshots = _parse_structured_positions(payload, broker="SynthBroker", snapshot_date=date(2025, 6, 30))

    assert len(snapshots) == 1
    # A ticker must be the canonical identifier so price sync can resolve it.
    # A free-text company name is not a usable market-data key.
    assert snapshots[0].asset_identifier == "SYNC", (
        f"expected ticker 'SYNC' to win, got {snapshots[0].asset_identifier!r} "
        "(company name leaked into asset_identifier -> breaks market-data sync)"
    )
