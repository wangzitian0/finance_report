from decimal import Decimal

import pytest

from src.audit.money.balances import CurrencyBalances
from src.extraction.base.validation import (
    _safe_parse_decimal,
    bank_currency_balances,
    compute_confidence_breakdown,
    evaluate_statement_balance,
    validate_balance_per_currency,
    validate_completeness,
)


def _eval_payload(d: dict) -> dict:
    return evaluate_statement_balance(
        opening=_safe_parse_decimal(d.get("opening_balance")),
        closing=_safe_parse_decimal(d.get("closing_balance")),
        currency=d.get("currency"),
        currency_balances=d.get("balances"),
        transactions=d.get("transactions") or [],
    )


@pytest.mark.parametrize(
    ("extracted", "expected_valid", "note_sub"),
    [
        (
            {
                "opening_balance": "100.00",
                "closing_balance": "200.00",
                "transactions": [{"amount": "10.00", "direction": "IN"}],
            },
            False,
            "Balance mismatch",
        ),
        (
            {
                "opening_balance": "100.00",
                "closing_balance": "100.05",
                "transactions": [{"amount": "0.05", "direction": "IN"}],
            },
            True,
            None,
        ),
        (
            {
                "opening_balance": "100.00",
                "closing_balance": "80.00",
                "transactions": [{"amount": "-20.00", "direction": "OUT"}],
            },
            True,
            None,
        ),
        (
            {
                "opening_balance": "100.00",
                "closing_balance": "80.00",
                "transactions": [{"amount": "20.00", "direction": "DEBIT"}],
            },
            True,
            None,
        ),
        ({"opening_balance": "100.00", "closing_balance": "100.00", "transactions": [{}]}, False, "Validation error"),
        (
            {"opening_balance": "100.00", "closing_balance": "110.00", "transactions": [{"direction": "IN"}]},
            False,
            "Validation error",
        ),
    ],
)
def test_validate_balance_cases(extracted, expected_valid, note_sub) -> None:
    result = _eval_payload(extracted)
    assert result["balance_valid"] is expected_valid
    if note_sub:
        assert note_sub in (result["notes"] or "")


def test_completeness_and_confidence_scoring() -> None:
    missing = validate_completeness({"institution": "DBS", "period_start": "2025-01-01"})
    assert {"period_end", "opening_balance", "closing_balance"}.issubset(missing)
    partial = {
        "institution": "DBS",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "opening_balance": "100.00",
        "closing_balance": None,
        "transactions": [{"amount": "0.00", "direction": "IN"}],
    }
    assert (
        compute_confidence_breakdown(
            partial, {"balance_valid": True, "difference": "0.00"}, validate_completeness(partial)
        ).score
        < 100
    )
    many = {
        "institution": "DBS",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "opening_balance": "100.00",
        "closing_balance": "100.00",
        "transactions": [{"amount": "1.00", "direction": "IN"} for _ in range(501)],
    }
    assert compute_confidence_breakdown(many, {"balance_valid": False, "difference": "5.00"}, []).score >= 0
    moomoo = {
        "institution": "Moomoo",
        "currency": "SGD",
        "period_start": "2026-05-01",
        "period_end": "2026-05-31",
        "opening_balance": "100.00",
        "closing_balance": "90.00",
        "transactions": [
            {"amount": "10.00", "direction": "IN", "currency": "SGD", "balance_after": "110.00"},
            {"amount": "20.00", "direction": "DEBIT", "currency": "SGD", "balance_after": "90.00"},
        ],
    }
    assert compute_confidence_breakdown(moomoo, {"balance_valid": True, "difference": "0.00"}, []).score >= 90
    no_proof = {
        **moomoo,
        "opening_balance": "0.00",
        "closing_balance": "400.00",
        "transactions": [
            {"amount": "500.00", "direction": "IN", "currency": "SGD", "balance_after": "500.00"},
            {"amount": "100.00", "direction": "OUT", "currency": "SGD", "balance_after": "400.00"},
        ],
    }
    assert (
        compute_confidence_breakdown(
            no_proof, {"balance_valid": True, "difference": "0.00", "balance_proof_available": False}, []
        ).score
        <= 59
    )
    bad = {
        "institution": "DBS",
        "period_start": "bad-date",
        "period_end": "bad-date",
        "opening_balance": "invalid",
        "closing_balance": "invalid",
        "transactions": [],
    }
    assert (
        compute_confidence_breakdown(
            bad, {"balance_valid": False, "difference": None}, validate_completeness(bad)
        ).score
        >= 0
    )
    small_diff = {**partial, "closing_balance": "101.00", "transactions": [{"amount": "1.00", "direction": "IN"}]}
    assert (
        compute_confidence_breakdown(
            small_diff, {"balance_valid": False, "difference": "0.50"}, validate_completeness(small_diff)
        ).score
        >= 30
    )


def test_per_currency_reconcile_and_currency_balance_schema() -> None:
    ok_multi = validate_balance_per_currency(
        {
            "balances": [
                {"currency": "SGD", "opening": "1000.00", "closing": "1200.00"},
                {"currency": "USD", "opening": "500.00", "closing": "300.00"},
            ],
            "transactions": [
                {"amount": "200.00", "direction": "IN", "currency": "SGD"},
                {"amount": "200.00", "direction": "OUT", "currency": "USD"},
            ],
        }
    )
    assert (
        ok_multi["balance_valid"] is True
        and ok_multi["balance_computable"] is True
        and "expected_closing" not in ok_multi
    )
    bad_usd = validate_balance_per_currency(
        {
            "balances": [
                {"currency": "SGD", "opening": "1000.00", "closing": "1200.00"},
                {"currency": "USD", "opening": "500.00", "closing": "300.00"},
            ],
            "transactions": [
                {"amount": "200.00", "direction": "IN", "currency": "SGD"},
                {"amount": "150.00", "direction": "OUT", "currency": "USD"},
            ],
        }
    )
    per_ccy = {r["currency"]: r for r in bad_usd["per_currency"]}
    assert (
        bad_usd["balance_valid"] is False
        and per_ccy["SGD"]["balance_valid"] is True
        and per_ccy["USD"]["difference"] == "50.00"
    )
    assert (
        validate_balance_per_currency(
            {
                "currency": "SGD",
                "opening_balance": "100.00",
                "closing_balance": "150.00",
                "transactions": [{"amount": "50.00", "direction": "IN", "currency": "SGD"}],
            }
        )["balance_valid"]
        is True
    )
    assert (
        validate_balance_per_currency(
            {
                "currency": "SGD",
                "opening_balance": "100.00",
                "closing_balance": "200.00",
                "transactions": [{"amount": "10.00", "direction": "IN", "currency": "SGD"}],
            }
        )["balance_valid"]
        is False
    )
    orphan = validate_balance_per_currency(
        {
            "balances": [{"currency": "SGD", "opening": "1000.00", "closing": "1200.00"}],
            "transactions": [
                {"amount": "200.00", "direction": "IN", "currency": "SGD"},
                {"amount": "75.00", "direction": "IN", "currency": "EUR"},
            ],
        }
    )
    orphan_map = {r["currency"]: r for r in orphan["per_currency"]}
    assert (
        orphan["balance_valid"] is False
        and orphan_map["EUR"]["declared_balance"] is False
        and orphan_map["EUR"]["difference"] == "75.00"
    )
    dup = validate_balance_per_currency(
        {
            "balances": [
                {"currency": "SGD", "opening": "1000.00", "closing": "1200.00"},
                {"currency": "SGD", "opening": "5000.00", "closing": "5100.00"},
            ],
            "transactions": [{"amount": "200.00", "direction": "IN", "currency": "SGD"}],
        }
    )
    assert (
        dup["balance_valid"] is False
        and dup["balance_computable"] is False
        and "Duplicate currency" in (dup["notes"] or "")
    )
    balances = CurrencyBalances.from_jsonb([{"currency": "usd", "opening": "1000.00", "closing": "1200.50"}])
    bal = next(iter(balances))
    assert (bal.currency.code, bal.opening.amount, bal.closing.amount) == (
        "USD",
        Decimal("1000.00"),
        Decimal("1200.50"),
    )
    multi_ccy = bank_currency_balances(
        {
            "currency": "SGD",
            "balances": [
                {"currency": "SGD", "opening": "1000.00", "closing": "1500.00"},
                {"currency": "USD", "opening": "200.00", "closing": "500.00"},
            ],
        }
    )
    assert multi_ccy is not None and {b["currency"] for b in multi_ccy} == {"SGD", "USD"}
    assert (
        bank_currency_balances(
            {"currency": "SGD", "balances": [{"currency": "SGD", "opening": "1000.00", "closing": "1500.00"}]}
        )
        is None
    )
    assert (
        bank_currency_balances({"currency": "SGD", "opening_balance": "1000.00", "closing_balance": "1500.00"}) is None
    )


def test_currency_buckets_require_printed_opening_and_closing() -> None:
    missing_entry = validate_balance_per_currency(
        {"balances": [{"currency": "SGD", "opening": None, "closing": "100.00"}], "transactions": []}
    )
    assert (
        missing_entry["balance_valid"] is False
        and missing_entry["balance_computable"] is False
        and missing_entry["per_currency"] == []
    )
    assert "Printed opening and closing balances are required" in (missing_entry["notes"] or "")
    missing_header = validate_balance_per_currency(
        {"currency": "SGD", "opening_balance": "", "closing_balance": "100.00", "transactions": []}
    )
    assert missing_header["balance_valid"] is False and missing_header["balance_computable"] is False
    assert "Printed opening and closing balances are required" in (missing_header["notes"] or "")
