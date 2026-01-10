"""Unit tests for statement validation helpers."""

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
