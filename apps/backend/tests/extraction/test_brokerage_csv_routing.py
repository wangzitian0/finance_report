"""Brokerage CSV routing tests (#1255 / AC17.32).

All CSV fixtures are SYNTHETIC: anonymized headers and made-up symbols/amounts,
no real account data or filenames.
"""

from decimal import Decimal

import pytest

from src.extraction.extension.brokerage_positions import (
    UnsupportedBrokerageCsvError,
    classify_brokerage_csv,
    parse_brokerage_csv_payload,
    parse_brokerage_positions,
    parse_brokerage_positions_csv_rows,
)
from src.extraction.extension.service import ExtractionError, ExtractionService

# --- Synthetic brokerage CSV fixtures (no real data) -----------------------

BROKERAGE_POSITIONS_CSV = b"""Symbol,Quantity,Current Price,Market Value,Currency,P&L
AAA,10,100.00,1000.00,USD,50.00
BBB,5,20.00,100.00,USD,-10.00
"""

BROKERAGE_TRADE_HISTORY_CSV = b"""Side,Symbol,Fill Quantity,Fill Price,Fill Amount,Fill Time,Fees,Total
BUY,AAA,10,100.00,1000.00,2026-01-02 09:30:00,1.00,1001.00
SELL,BBB,5,20.00,100.00,2026-01-03 10:00:00,1.00,99.00
"""

BANK_TRANSACTION_CSV = b"""Transaction Date,Reference,Debit Amount,Credit Amount,Transaction Ref1
15 Jan 2025,REF001,,500.00,SALARY
16 Jan 2025,REF002,100.00,,GROCERIES
"""


# --- Classifier unit tests --------------------------------------------------


def test_classify_brokerage_csv_distinguishes_schemas():
    """AC-extraction.332.1 AC-extraction.332.2 AC-extraction.332.3: header classifier separates the three CSV shapes."""
    assert classify_brokerage_csv(["Symbol", "Quantity", "Market Value", "Currency"]) == "positions"
    assert classify_brokerage_csv(["Side", "Symbol", "Fill Quantity", "Fill Price", "Total"]) == "trade_history"
    assert classify_brokerage_csv(["Transaction Date", "Debit Amount", "Credit Amount"]) is None
    assert classify_brokerage_csv([]) is None


def test_parse_brokerage_positions_csv_rows_uses_decimal():
    """AC-extraction.332.1: positions CSV rows map to Decimal-backed position dicts."""
    headers = ["Symbol", "Quantity", "Market Value", "Currency"]
    rows = [
        {"Symbol": "AAA", "Quantity": "10", "Market Value": "1,000.00", "Currency": "usd"},
        {"Symbol": "", "Quantity": "1", "Market Value": "5.00", "Currency": "USD"},  # skipped: no symbol
    ]
    positions = parse_brokerage_positions_csv_rows(headers, rows, broker="Interactive Brokers")
    assert len(positions) == 1
    pos = positions[0]
    assert pos["asset_identifier"] == "AAA"
    assert Decimal(pos["quantity"]) == Decimal("10")
    assert Decimal(pos["market_value"]) == Decimal("1000.00")
    assert pos["currency"] == "USD"


# --- AC-extraction.332.1: positions CSV reaches brokerage import path -----------------


async def test_AC17_32_1_brokerage_positions_csv_produces_positions_payload():
    """AC-extraction.332.1: Brokerage positions CSV is mapped into a ``positions`` payload.

    The payload must satisfy the brokerage import contract (parse_brokerage_positions
    yields snapshots) instead of failing with a bank "No valid transactions" error.
    """
    service = ExtractionService()
    payload = await service._parse_csv_content(BROKERAGE_POSITIONS_CSV, "Interactive Brokers")

    assert "positions" in payload
    assert len(payload["positions"]) == 2
    assert payload["balance_source"] == "brokerage_positions_csv"
    # The payload flows into the brokerage import path.
    snapshots = parse_brokerage_positions(payload, institution="Interactive Brokers")
    assert len(snapshots) == 2
    assert snapshots[0].asset_identifier == "AAA"
    assert snapshots[0].quantity == Decimal("10")
    assert snapshots[0].market_value == Decimal("1000.00")
    assert snapshots[0].currency == "USD"


# --- AC-extraction.332.2: trade-history CSV gives an actionable error -----------------


async def test_AC17_32_2_brokerage_trade_history_csv_raises_actionable_error():
    """AC-extraction.332.2: Trade-history CSV raises an actionable unsupported error.

    It must NOT surface the misleading generic bank parse failure.
    """
    service = ExtractionService()
    with pytest.raises(ExtractionError) as excinfo:
        await service._parse_csv_content(BROKERAGE_TRADE_HISTORY_CSV, "Interactive Brokers")

    message = str(excinfo.value)
    assert "trade-history" in message.lower()
    assert "No valid transactions found" not in message


def test_parse_brokerage_csv_payload_rejects_trade_history():
    """AC-extraction.332.2: trade-history schema raises the typed unsupported error."""
    headers = ["Side", "Symbol", "Fill Quantity", "Fill Price", "Total"]
    with pytest.raises(UnsupportedBrokerageCsvError, match="trade-history"):
        parse_brokerage_csv_payload(headers, [], institution="Interactive Brokers")


# --- AC-extraction.332.3: bank CSV parsing is unaffected ------------------------------


async def test_AC17_32_3_bank_csv_unaffected_by_brokerage_detection():
    """AC-extraction.332.3: Bank transaction CSV parsing is unchanged (no regression)."""
    service = ExtractionService()
    payload = await service._parse_csv_content(BANK_TRANSACTION_CSV, "DBS")

    assert "positions" not in payload
    assert len(payload["transactions"]) == 2
    assert payload["transactions"][0]["direction"] == "IN"
    assert payload["transactions"][0]["amount"] == "500.00"
    assert payload["transactions"][1]["direction"] == "OUT"
    assert payload["transactions"][1]["amount"] == "100.00"
