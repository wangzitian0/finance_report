from __future__ import annotations

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

BROKERAGE_POSITIONS_CSV = b"Symbol,Quantity,Current Price,Market Value,Currency,P&L\nAAA,10,100.00,1000.00,USD,50.00\nBBB,5,20.00,100.00,USD,-10.00\n"
BROKERAGE_TRADE_HISTORY_CSV = b"Side,Symbol,Fill Quantity,Fill Price,Fill Amount,Fill Time,Fees,Total\nBUY,AAA,10,100.00,1000.00,2026-01-02 09:30:00,1.00,1001.00\nSELL,BBB,5,20.00,100.00,2026-01-03 10:00:00,1.00,99.00\n"
BANK_TRANSACTION_CSV = b"Transaction Date,Reference,Debit Amount,Credit Amount,Transaction Ref1\n15 Jan 2025,REF001,,500.00,SALARY\n16 Jan 2025,REF002,100.00,,GROCERIES\n"


def test_classify_brokerage_csv_distinguishes_schemas():
    pos_headers = ["Symbol", "Quantity", "Market Value", "Currency"]
    trade_headers = ["Side", "Symbol", "Fill Quantity", "Fill Price", "Total"]
    assert (classify_brokerage_csv(pos_headers), classify_brokerage_csv(trade_headers), classify_brokerage_csv(["Transaction Date", "Debit Amount", "Credit Amount"]), classify_brokerage_csv([])) == ("positions", "trade_history", None, None)

    positions = parse_brokerage_positions_csv_rows(pos_headers, [{"Symbol": "AAA", "Quantity": "10", "Market Value": "1,000.00", "Currency": "usd"}, {"Symbol": "", "Quantity": "1", "Market Value": "5.00", "Currency": "USD"}], broker="Interactive Brokers")
    assert len(positions) == 1 and (positions[0]["asset_identifier"], Decimal(positions[0]["quantity"]), Decimal(positions[0]["market_value"]), positions[0]["currency"]) == ("AAA", Decimal("10"), Decimal("1000.00"), "USD")
    with pytest.raises(UnsupportedBrokerageCsvError, match="trade-history"):
        parse_brokerage_csv_payload(trade_headers, [], institution="Interactive Brokers")


async def test_AC17_32_brokerage_csv_and_bank_csv_routing():
    service = ExtractionService()
    payload = await service._parse_csv_content(BROKERAGE_POSITIONS_CSV, "Interactive Brokers")
    snapshots = parse_brokerage_positions(payload, institution="Interactive Brokers")
    assert (len(payload["positions"]), payload["balance_source"], len(snapshots), snapshots[0].asset_identifier, snapshots[0].quantity, snapshots[0].market_value, snapshots[0].currency) == (
        2, "brokerage_positions_csv", 2, "AAA", Decimal("10"), Decimal("1000.00"), "USD"
    )

    with pytest.raises(ExtractionError) as excinfo:
        await service._parse_csv_content(BROKERAGE_TRADE_HISTORY_CSV, "Interactive Brokers")
    assert "trade-history" in str(excinfo.value).lower() and "No valid transactions found" not in str(excinfo.value)

    bank = await service._parse_csv_content(BANK_TRANSACTION_CSV, "DBS")
    assert ("positions" not in bank, len(bank["transactions"]), bank["transactions"][0]["direction"], bank["transactions"][0]["amount"], bank["transactions"][1]["direction"], bank["transactions"][1]["amount"]) == (
        True, 2, "IN", "500.00", "OUT", "100.00"
    )
