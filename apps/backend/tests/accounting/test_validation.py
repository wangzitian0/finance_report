"""AC2.12.1 - AC2.12.6: Statement Validation Logic Tests

These tests validate balance calculation, completeness checks, confidence scoring,
and threshold-based routing logic for bank statements.
"""

from decimal import Decimal

from src.models.statement_enums import BankStatementStatus
from src.services.validation import (
    compute_confidence_score,
    route_by_threshold,
    validate_balance,
    validate_balance_per_currency,
    validate_completeness,
)


def test_validate_balance_mismatch():
    """Balance mismatch should return notes and invalid flag."""
    extracted = {
        "opening_balance": "100.00",
        "closing_balance": "200.00",
        "transactions": [{"amount": "10.00", "direction": "IN"}],
    }
    result = validate_balance(extracted)
    assert result["balance_valid"] is False
    assert "Balance mismatch" in (result["notes"] or "")


def test_validate_completeness_missing_fields():
    """Missing required fields should be listed."""
    extracted = {
        "institution": "DBS",
        "period_start": "2025-01-01",
    }
    missing = validate_completeness(extracted)
    assert "period_end" in missing
    assert "opening_balance" in missing
    assert "closing_balance" in missing


def test_compute_confidence_score_with_missing_fields():
    """Confidence score should drop when fields are missing."""
    extracted = {
        "institution": "DBS",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "opening_balance": "100.00",
        "closing_balance": None,
        "transactions": [{"amount": "0.00", "direction": "IN"}],
    }
    missing_fields = validate_completeness(extracted)
    balance_result = {"balance_valid": True, "difference": "0.00"}
    score = compute_confidence_score(extracted, balance_result, missing_fields)
    assert score < 100


def test_route_by_threshold():
    """Routing uses thresholds and balance validity."""
    assert route_by_threshold(90, True) == BankStatementStatus.APPROVED
    assert route_by_threshold(70, True) == BankStatementStatus.PARSED
    assert route_by_threshold(50, True) == BankStatementStatus.UPLOADED
    assert route_by_threshold(90, False) == BankStatementStatus.UPLOADED


def test_validate_balance_tolerance():
    """Balance within tolerance should be valid."""
    extracted = {
        "opening_balance": "100.00",
        "closing_balance": "100.05",
        "transactions": [{"amount": "0.05", "direction": "IN"}],
    }
    result = validate_balance(extracted)
    assert result["balance_valid"] is True
    assert Decimal(result["difference"]) <= Decimal("0.10")


def test_validate_balance_normalizes_signed_outflows():
    """AC8.13.10/Issue #409: Balance validation treats direction as the sign source."""
    extracted = {
        "opening_balance": "100.00",
        "closing_balance": "80.00",
        "transactions": [{"amount": "-20.00", "direction": "OUT"}],
    }

    result = validate_balance(extracted)

    assert result["balance_valid"] is True
    assert result["difference"] == "0.00"


def test_validate_balance_infers_non_standard_signed_outflows():
    """AC8.13.10/Issue #409: Non-standard debit directions normalize to OUT."""
    extracted = {
        "opening_balance": "100.00",
        "closing_balance": "80.00",
        "transactions": [{"amount": "20.00", "direction": "DEBIT"}],
    }

    result = validate_balance(extracted)

    assert result["balance_valid"] is True
    assert result["difference"] == "0.00"


def test_validate_balance_error_path():
    """Invalid transaction payloads should surface as validation errors."""
    extracted = {
        "opening_balance": "100.00",
        "closing_balance": "100.00",
        "transactions": [{}],
    }
    result = validate_balance(extracted)
    assert result["balance_valid"] is False
    assert "Validation error" in (result["notes"] or "")


def test_compute_confidence_score_large_transaction_count():
    extracted = {
        "institution": "DBS",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "opening_balance": "100.00",
        "closing_balance": "100.00",
        "transactions": [{"amount": "1.00", "direction": "IN"} for _ in range(501)],
    }
    balance_result = {"balance_valid": False, "difference": "5.00"}
    missing_fields = []
    score = compute_confidence_score(extracted, balance_result, missing_fields)
    assert score >= 0


def test_compute_confidence_score_normalizes_signed_outflow_progression():
    """AC8.13.10/Issue #409: Running-balance scoring normalizes signed OUT rows."""
    extracted = {
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

    score = compute_confidence_score(
        extracted,
        {"balance_valid": True, "difference": "0.00"},
        missing_fields=[],
    )

    assert score == 100


def test_compute_confidence_score_without_balance_proof_gets_no_balance_component():
    """AC3.2.5: Inferred balances do not earn source balance-validation confidence."""
    extracted = {
        "institution": "DBS",
        "currency": "SGD",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "opening_balance": "0.00",
        "closing_balance": "400.00",
        "transactions": [
            {"amount": "500.00", "direction": "IN", "currency": "SGD", "balance_after": "500.00"},
            {"amount": "100.00", "direction": "OUT", "currency": "SGD", "balance_after": "400.00"},
        ],
    }

    score = compute_confidence_score(
        extracted,
        {"balance_valid": True, "difference": "0.00", "balance_proof_available": False},
        missing_fields=[],
    )

    assert score == 65


def test_compute_confidence_score_invalid_difference() -> None:
    extracted = {
        "institution": "DBS",
        "period_start": "bad-date",
        "period_end": "bad-date",
        "opening_balance": "invalid",
        "closing_balance": "invalid",
        "transactions": [],
    }
    balance_result = {"balance_valid": False, "difference": None}
    missing_fields = validate_completeness(extracted)
    score = compute_confidence_score(extracted, balance_result, missing_fields)
    assert score >= 0


def test_compute_confidence_score_small_diff():
    """Small balance differences should still earn partial score."""
    extracted = {
        "institution": "DBS",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "opening_balance": "100.00",
        "closing_balance": "101.00",
        "transactions": [{"amount": "1.00", "direction": "IN"}],
    }
    missing_fields = validate_completeness(extracted)
    balance_result = {"balance_valid": False, "difference": "0.50"}
    score = compute_confidence_score(extracted, balance_result, missing_fields)
    assert score >= 30


def test_validate_balance_incomplete_transaction():
    """Transaction with some fields present but missing required ones should surface error."""
    extracted = {
        "opening_balance": "100.00",
        "closing_balance": "110.00",
        "transactions": [{"direction": "IN"}],  # Has direction but missing amount
    }
    result = validate_balance(extracted)
    assert result["balance_valid"] is False
    assert "Validation error" in (result["notes"] or "")


# --- #1123 AC1: per-currency balances + per-currency reconciliation ---


def test_AC1_per_currency_reconcile_does_not_cross_sum():
    """AC4.13.1 (#1123 AC1): A multi-currency statement reconciles each currency independently.

    Each currency's running balance is checked with its OWN
    ``open_ccy + ΣIN_ccy − ΣOUT_ccy ≈ close_ccy`` invariant. The currencies must
    NOT be summed together: here both SGD and USD balance individually, but the
    cross-summed scalar total (which the legacy aggregate check would compute)
    does NOT balance — so a correct per-currency check passes where a cross-sum
    check would wrongly fail (or, worse, wrongly pass on offsetting errors).
    """
    extracted = {
        "balances": [
            {"currency": "SGD", "opening": "1000.00", "closing": "1200.00"},
            {"currency": "USD", "opening": "500.00", "closing": "300.00"},
        ],
        "transactions": [
            {"amount": "200.00", "direction": "IN", "currency": "SGD"},
            {"amount": "200.00", "direction": "OUT", "currency": "USD"},
        ],
    }

    result = validate_balance_per_currency(extracted)

    assert result["balance_valid"] is True
    assert result["balance_computable"] is True
    per_ccy = {r["currency"]: r for r in result["per_currency"]}
    assert set(per_ccy) == {"SGD", "USD"}
    assert per_ccy["SGD"]["balance_valid"] is True
    assert per_ccy["USD"]["balance_valid"] is True
    # No cross-currency total is produced; each currency stands alone.
    assert "expected_closing" not in result


def test_AC1_per_currency_reconcile_flags_only_offending_currency():
    """AC4.13.2 (#1123 AC1): A mismatch in one currency does not contaminate the others.

    USD is short by 50; SGD is correct. The per-currency result marks only USD
    invalid and keeps SGD valid — never collapsing them into one aggregate flag.
    """
    extracted = {
        "balances": [
            {"currency": "SGD", "opening": "1000.00", "closing": "1200.00"},
            {"currency": "USD", "opening": "500.00", "closing": "300.00"},
        ],
        "transactions": [
            {"amount": "200.00", "direction": "IN", "currency": "SGD"},
            {"amount": "150.00", "direction": "OUT", "currency": "USD"},
        ],
    }

    result = validate_balance_per_currency(extracted)

    assert result["balance_valid"] is False
    per_ccy = {r["currency"]: r for r in result["per_currency"]}
    assert per_ccy["SGD"]["balance_valid"] is True
    assert per_ccy["USD"]["balance_valid"] is False
    assert per_ccy["USD"]["difference"] == "50.00"


def test_AC1_single_currency_degenerate_path_still_passes():
    """AC4.13.3 (#1123 AC1): A single-currency statement passes via the degenerate path.

    With only the scalar ``opening_balance`` / ``closing_balance`` present (no
    ``balances`` array — today's payloads), per-currency validation falls back to
    one synthetic currency bucket and reproduces the existing scalar check.
    """
    extracted = {
        "currency": "SGD",
        "opening_balance": "100.00",
        "closing_balance": "150.00",
        "transactions": [{"amount": "50.00", "direction": "IN", "currency": "SGD"}],
    }

    result = validate_balance_per_currency(extracted)

    assert result["balance_valid"] is True
    assert len(result["per_currency"]) == 1
    assert result["per_currency"][0]["currency"] == "SGD"
    assert result["per_currency"][0]["balance_valid"] is True


def test_AC1_single_currency_degenerate_path_detects_mismatch():
    """AC4.13.4 (#1123 AC1): The degenerate single-currency path still catches mismatches."""
    extracted = {
        "currency": "SGD",
        "opening_balance": "100.00",
        "closing_balance": "200.00",
        "transactions": [{"amount": "10.00", "direction": "IN", "currency": "SGD"}],
    }

    result = validate_balance_per_currency(extracted)

    assert result["balance_valid"] is False
    assert result["per_currency"][0]["balance_valid"] is False


def test_AC1_currency_balance_schema_round_trips_decimals():
    """AC4.13.5 (#1123 AC1): ``CurrencyBalance`` carries (currency, opening, closing) as Decimal."""
    from src.schemas.extraction import CurrencyBalance

    bal = CurrencyBalance(currency="usd", opening="1000.00", closing="1200.50")

    assert bal.currency == "USD"  # normalized upper-case ISO code
    assert bal.opening == Decimal("1000.00")
    assert bal.closing == Decimal("1200.50")


def test_AC1_orphan_currency_transaction_is_surfaced_not_dropped():
    """AC4.13.7 (#1123 AC1): A transaction in an undeclared currency is surfaced, not dropped.

    EUR appears in a transaction but has no declared balance bucket. Without
    surfacing it, the EUR money would vanish and the statement could appear to
    reconcile. The orphan currency must show up as its own per-currency result
    (flagged ``declared_balance=False``) and force the overall result invalid.
    """
    extracted = {
        "balances": [
            {"currency": "SGD", "opening": "1000.00", "closing": "1200.00"},
        ],
        "transactions": [
            {"amount": "200.00", "direction": "IN", "currency": "SGD"},
            {"amount": "75.00", "direction": "IN", "currency": "EUR"},
        ],
    }

    result = validate_balance_per_currency(extracted)

    per_ccy = {r["currency"]: r for r in result["per_currency"]}
    assert set(per_ccy) == {"SGD", "EUR"}, "orphan EUR transaction must not be dropped"
    assert per_ccy["SGD"]["declared_balance"] is True
    assert per_ccy["SGD"]["balance_valid"] is True
    assert per_ccy["EUR"]["declared_balance"] is False
    assert per_ccy["EUR"]["balance_valid"] is False
    assert per_ccy["EUR"]["difference"] == "75.00"
    assert result["balance_valid"] is False


def test_AC1_duplicate_currency_in_balances_is_rejected():
    """AC4.13.8 (#1123 AC1): Duplicate currencies in ``balances`` are rejected, not collapsed.

    Two SGD buckets would make ``nets`` ambiguous (keyed by currency), so the
    validator rejects the payload with ``balance_computable=False`` rather than
    silently picking one bucket and producing an arbitrary result.
    """
    extracted = {
        "balances": [
            {"currency": "SGD", "opening": "1000.00", "closing": "1200.00"},
            {"currency": "SGD", "opening": "5000.00", "closing": "5100.00"},
        ],
        "transactions": [
            {"amount": "200.00", "direction": "IN", "currency": "SGD"},
        ],
    }

    result = validate_balance_per_currency(extracted)

    assert result["balance_valid"] is False
    assert result["balance_computable"] is False
    assert result["per_currency"] == []
    assert "Duplicate currency" in (result["notes"] or "")
