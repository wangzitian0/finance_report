from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

from src.extraction import DocumentSource
from src.extraction.extension.service import ExtractionService


def _multi_currency_bank_payload():
    return {
        "institution": "DBS", "account_last4": "0355", "currency": "SGD", "period_start": "2025-06-01", "period_end": "2025-06-30",
        "opening_balance": "1000.00", "closing_balance": "1500.00",
        "balances": [{"currency": "SGD", "opening": "1000.00", "closing": "1500.00"}, {"currency": "USD", "opening": "200.00", "closing": "500.00"}],
        "transactions": [{"date": "2025-06-10", "description": "Salary", "amount": "500.00", "direction": "IN", "currency": "SGD"}, {"date": "2025-06-12", "description": "USD inflow", "amount": "300.00", "direction": "IN", "currency": "USD"}],
    }


async def test_AC4_13_9_bank_multi_currency_and_scalar_paths(test_user, monkeypatch):
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(return_value=_multi_currency_bank_payload())
    res_mc = await service.parse_document(DocumentSource.resolve(path=Path("dbs-statement-2506.pdf"), content=b"%PDF-1.7", content_hash="dbs-multicurrency-hash", filename="dbs-statement-2506.pdf"), institution="DBS", user_id=test_user.id)
    by_ccy = {b.currency: b for b in res_mc.balances}
    assert (set(by_ccy), by_ccy["USD"].closing, res_mc.balance_validated) == ({"SGD", "USD"}, Decimal("500.00"), True)

    monkeypatch.setattr("src.extraction.extension.service.validate_balance_per_currency", lambda _e: {"balance_valid": False, "balance_computable": True, "per_currency": [{"currency": "USD", "balance_valid": False, "expected_closing": "500.00", "actual_closing": "400.00"}, {"currency": "SGD", "balance_valid": True}]})
    res_fail = await service.parse_document(DocumentSource.resolve(path=Path("dbs-statement-2506.pdf"), content=b"%PDF-1.7", content_hash="dbs-multicurrency-fail-hash", filename="dbs-statement-2506.pdf"), institution="DBS", user_id=test_user.id)
    assert (len(res_fail.balances), res_fail.balance_validated, bool(res_fail.review_reasons)) == (2, False, True)

    service.extract_financial_data = AsyncMock(return_value={"institution": "DBS", "account_last4": "0355", "currency": "SGD", "period_start": "2025-06-01", "period_end": "2025-06-30", "opening_balance": "1000.00", "closing_balance": "1500.00", "transactions": [{"date": "2025-06-10", "description": "Salary", "amount": "500.00", "direction": "IN", "currency": "SGD"}]})
    res_sc = await service.parse_document(DocumentSource.resolve(path=Path("dbs-statement-2506.pdf"), content=b"%PDF-1.7", content_hash="dbs-singlecurrency-hash", filename="dbs-statement-2506.pdf"), institution="DBS", user_id=test_user.id)
    assert (len(res_sc.balances), res_sc.balances[0].currency, res_sc.balance_validated) == (1, "SGD", True)
