"""AC4.13.9 (#1502): a multi-currency BANK statement must not collapse its
currencies into one scalar opening/closing.

A consolidated / multi-currency bank statement (e.g. DBS) holds several currencies
at once. The brokerage path already persists a per-currency NAV array (#1139); this
brings the bank path to parity: when the bank payload declares per-currency
``balances`` for >1 currency, ``parse_document`` persists ``currency_balances`` and
the per-currency self-check governs ``balance_validated`` (a cross-summed scalar
check across currencies is meaningless). A single-currency bank statement keeps the
unchanged scalar path.
"""

from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

from src.extraction.extension.service import ExtractionService


def _multi_currency_bank_payload() -> dict:
    """A DBS-style multi-currency bank payload: SGD + USD, each a closed loop
    (opening + ΣIN − ΣOUT == closing per currency, never cross-summed)."""
    return {
        "institution": "DBS",
        "account_last4": "0355",
        "currency": "SGD",  # presentation/primary currency only
        "period_start": "2025-06-01",
        "period_end": "2025-06-30",
        "opening_balance": "1000.00",
        "closing_balance": "1500.00",
        "balances": [
            {"currency": "SGD", "opening": "1000.00", "closing": "1500.00"},
            {"currency": "USD", "opening": "200.00", "closing": "500.00"},
        ],
        "transactions": [
            {"date": "2025-06-10", "description": "Salary", "amount": "500.00", "direction": "IN", "currency": "SGD"},
            {
                "date": "2025-06-12",
                "description": "USD inflow",
                "amount": "300.00",
                "direction": "IN",
                "currency": "USD",
            },
        ],
    }


async def test_AC4_13_9_bank_multi_currency_statement_persists_balances_and_per_currency_governs(test_user):
    """AC-reconciliation.per-currency-balance.9: AC4.13.9: the per-currency array is persisted (not collapsed) and, because each
    currency reconciles, the statement is balance-validated even though a cross-summed
    scalar check would be meaningless."""
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(return_value=_multi_currency_bank_payload())

    statement, _ = await service.parse_document(
        file_path=Path("dbs-statement-2506.pdf"),
        institution="DBS",
        user_id=test_user.id,
        file_content=b"%PDF-1.7",
        file_hash="dbs-multicurrency-hash",
        original_filename="dbs-statement-2506.pdf",
    )

    # Per-currency balances persisted, not collapsed into one scalar currency.
    assert statement.currency_balances is not None
    by_ccy = {b["currency"]: b for b in statement.currency_balances}
    assert set(by_ccy) == {"SGD", "USD"}
    assert Decimal(by_ccy["USD"]["closing"]) == Decimal("500.00")
    # The presentation currency stays SGD; it does not force the USD leg to SGD.
    assert statement.currency == "SGD"
    # Each currency reconciles -> the statement is validated (per-currency governs).
    assert statement.balance_validated is True


async def test_AC4_13_9_bank_multi_currency_per_currency_mismatch_flags_invalid(test_user, monkeypatch):
    """AC4.13.9: a per-currency self-check failure must never present as valid. For a
    bank the unreconciled extraction is quarantined (LLM-LED gate, #1352) — the point
    under test is that per-currency governs the verdict (balance_validated False), and
    the per-currency evidence array is still persisted; it is never silently valid."""
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(return_value=_multi_currency_bank_payload())

    def _failing_per_currency(_extracted):
        return {
            "balance_valid": False,
            "balance_computable": True,
            "per_currency": [
                {"currency": "USD", "balance_valid": False, "expected_closing": "500.00", "actual_closing": "400.00"},
                {"currency": "SGD", "balance_valid": True},
            ],
        }

    monkeypatch.setattr("src.extraction.extension.service.validate_balance_per_currency", _failing_per_currency)

    statement, _ = await service.parse_document(
        file_path=Path("dbs-statement-2506.pdf"),
        institution="DBS",
        user_id=test_user.id,
        file_content=b"%PDF-1.7",
        file_hash="dbs-multicurrency-fail-hash",
        original_filename="dbs-statement-2506.pdf",
    )

    assert statement.currency_balances is not None  # evidence still persisted
    assert statement.balance_validated is False  # per-currency governs; never silently valid
    assert statement.validation_error  # carries a typed failure reason, not silence


async def test_AC4_13_9_single_currency_bank_statement_keeps_scalar_path(test_user):
    """AC4.13.9: a single-currency bank statement is unchanged — no currency_balances,
    scalar reconciliation governs (backward compatible)."""
    service = ExtractionService()
    payload = {
        "institution": "DBS",
        "account_last4": "0355",
        "currency": "SGD",
        "period_start": "2025-06-01",
        "period_end": "2025-06-30",
        "opening_balance": "1000.00",
        "closing_balance": "1500.00",
        "transactions": [
            {"date": "2025-06-10", "description": "Salary", "amount": "500.00", "direction": "IN", "currency": "SGD"},
        ],
    }
    service.extract_financial_data = AsyncMock(return_value=payload)

    statement, _ = await service.parse_document(
        file_path=Path("dbs-statement-2506.pdf"),
        institution="DBS",
        user_id=test_user.id,
        file_content=b"%PDF-1.7",
        file_hash="dbs-singlecurrency-hash",
        original_filename="dbs-statement-2506.pdf",
    )

    assert statement.currency_balances is None
    assert statement.balance_validated is True
