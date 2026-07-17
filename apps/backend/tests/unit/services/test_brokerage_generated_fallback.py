import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.extraction import DocumentSource
from src.extraction.extension.brokerage_positions import _generated_brokerage_positions_payload_from_text
from src.extraction.extension.service import ExtractionService

pytestmark = pytest.mark.no_db


MOOMOO_GENERATED_TEXT = """
Moomoo SG - Monthly Statement
Statement Period: June 2026
Account: ****1582
Transaction Details
Date
Type
Description
Amount
Currency
2026-05-21
SUBSCRIPTION
Fullerton SGD Money Market Fund
1,250.50
SGD
"""


def test_generated_moomoo_pdf_text_fallback_emits_subscription_position():
    """AC-extraction.813.10/AC-extraction.304.12: Generated Moomoo PDF text can backfill a missing model position."""
    payload = _generated_brokerage_positions_payload_from_text(
        MOOMOO_GENERATED_TEXT,
        filename="test_moomoo_2606_24697.pdf",
        institution="Moomoo E2E Portfolio",
    )

    assert payload is not None
    assert payload["institution"] == "Moomoo"
    assert payload["account_last4"] == "1582"
    assert payload["snapshot_date"] == "2026-06-30"
    assert payload["positions"] == [
        {
            "symbol": "Fullerton SGD Money Market Fund",
            "asset_identifier": "Fullerton SGD Money Market Fund",
            "quantity": "1",
            "market_value": "1250.50",
            "currency": "SGD",
            "asset_type": "money_market",
        }
    ]


def test_generated_futu_pdf_text_fallback_emits_valuation_position():
    """AC-extraction.813.10/AC-extraction.304.12: Generated Futu PDF text can backfill a missing model position."""
    text = """
Futu Securities - Monthly Statement
Statement Period: June 2026
Account: ****6688
Activity and Valuation
Date
Type
Description
Amount
Currency
2026-05-21
VALUATION
Stock and options valuation
323,730.00
SGD
"""

    payload = _generated_brokerage_positions_payload_from_text(
        text,
        filename="test_futu_2606_24697.pdf",
        institution="Futu E2E Portfolio",
    )

    assert payload is not None
    assert payload["institution"] == "Futu"
    assert payload["account_last4"] == "6688"
    assert payload["snapshot_date"] == "2026-06-30"
    assert payload["positions"] == [
        {
            "symbol": "FUTU_STOCK_AND_OPTIONS",
            "asset_identifier": "FUTU_STOCK_AND_OPTIONS",
            "quantity": "1",
            "market_value": "323730.00",
            "currency": "SGD",
            "asset_type": "other",
        }
    ]


async def test_parse_document_backfills_generated_brokerage_positions_from_pdf_text(monkeypatch):
    """AC-extraction.813.10/AC-extraction.304.12: Generated brokerage PDFs do not fail open when the model emits empty positions."""
    service = ExtractionService()

    async def empty_model_payload(*args, **kwargs):
        return {
            "institution": "Moomoo",
            "account_last4": "1582",
            "currency": "SGD",
            "period_start": "2026-06-01",
            "period_end": "2026-06-30",
            "positions": [],
            "transactions": [],
        }

    monkeypatch.setattr(service, "_extract_with_balance_retry", empty_model_payload)
    monkeypatch.setattr(
        service,
        "_extract_pdf_text_for_brokerage_fallback",
        lambda _content: MOOMOO_GENERATED_TEXT,
    )

    result = await service.parse_document(
        DocumentSource.resolve(
            path=Path("test_moomoo_2606_24697.pdf"),
            content=b"%PDF-1.7",
            filename="test_moomoo_2606_24697.pdf",
        ),
        user_id=uuid4(),
        file_type="pdf",
        institution="Moomoo E2E Portfolio",
    )

    assert result.transactions == ()
    assert len(result.positions) == 1
    assert result.positions[0].symbol == "Fullerton SGD Money Market Fund"
    assert result.positions[0].quantity == Decimal("1")
    assert result.positions[0].market_value == Decimal("1250.50")
    assert result.positions[0].currency == "SGD"
    assert result.positions[0].asset_type == "money_market"


def test_pdf_text_fallback_closes_pymupdf_document(monkeypatch):
    """AC-extraction.813.10/AC-extraction.304.12: Generated brokerage PDF fallback closes PyMuPDF documents."""
    closed = False

    class FakePage:
        def get_text(self):
            return "Moomoo generated fixture"

    class FakeDocument:
        def __iter__(self):
            return iter([FakePage()])

        def close(self):
            nonlocal closed
            closed = True

    monkeypatch.setitem(sys.modules, "fitz", SimpleNamespace(open=lambda **_kwargs: FakeDocument()))

    assert ExtractionService()._extract_pdf_text_for_brokerage_fallback(b"%PDF") == "Moomoo generated fixture"
    assert closed is True
