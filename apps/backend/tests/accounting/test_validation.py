"""AC2.12.1 - AC2.12.6: Statement Validation Logic Tests

These tests validate balance calculation, completeness checks, confidence scoring,
and threshold-based routing logic for bank statements.
"""

from decimal import Decimal

from src.models.statement import BankStatementStatus
from src.services.validation import (
    compute_confidence_score,
    route_by_threshold,
    validate_balance,
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
    assert route_by_threshold(90, True) == BankStatementStatus.PARSED
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
