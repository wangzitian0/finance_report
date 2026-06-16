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
    # AC13.21.1 (#1141): a balance-invalid bank statement no longer dead-ends in
    # `uploaded`; it enters review (`PARSED`), matching the brokerage path.
    assert route_by_threshold(90, False) == BankStatementStatus.PARSED


def test_AC13_21_1_balance_invalid_routes_to_parsed_review():
    """AC13.21.1 (#1141): balance-invalid bank statements route to PARSED (review).

    A parsed-but-unvalidated bank statement must never be parked in `uploaded`
    (the retry-rejected, readiness-invisible dead-end). It must enter the same
    reviewable resting state as a brokerage statement, regardless of score.
    """
    for score in (0, 50, 59, 60, 84, 85, 95, 100):
        assert route_by_threshold(score, balance_valid=False) == BankStatementStatus.PARSED, (
            f"balance-invalid score={score} must route to PARSED, never UPLOADED"
        )
    # Valid-balance routing semantics are preserved (low signal -> manual entry).
    assert route_by_threshold(50, balance_valid=True) == BankStatementStatus.UPLOADED


async def test_AC13_21_4_readiness_counts_parsed_balance_invalid(db, test_user):
    """AC13.21.4 (#1141): the balance-invalid resting state is readiness-visible.

    A balance-invalid bank statement rests in `PARSED` (see routing below); report
    readiness counts `PARSED` + `APPROVED` summaries, so the statement is an
    available report input instead of an invisible `uploaded` orphan. This drives
    the real readiness query against a seeded DB row rather than inspecting source
    text, so a regression in the status filter would actually fail the test.
    """
    from src.models import StatementSummary
    from src.services.report_readiness import get_personal_report_package_readiness

    # The balance-invalid bank statement rests in PARSED, not UPLOADED.
    resting_status = route_by_threshold(95, balance_valid=False)
    assert resting_status == BankStatementStatus.PARSED

    # Baseline: no statements seeded -> readiness counts zero.
    baseline = await get_personal_report_package_readiness(db, test_user.id)
    assert baseline["source_summary"]["statements"] == 0

    # Seed a PARSED, balance-invalid statement (the exact resting state under test).
    statement = StatementSummary(
        user_id=test_user.id,
        account_id=None,
        file_hash="readiness-parsed-balance-invalid",
        institution="DBS",
        currency="SGD",
        status=resting_status,
        balance_validated=False,
    )
    db.add(statement)
    await db.flush()

    # The real readiness query must count the PARSED balance-invalid statement.
    readiness = await get_personal_report_package_readiness(db, test_user.id)
    assert readiness["source_summary"]["statements"] == 1


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
