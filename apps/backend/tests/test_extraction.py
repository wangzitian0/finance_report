"""Tests for the document extraction service."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from src.services.extraction import ExtractionService

# Get fixtures directory
FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestBalanceValidation:
    """Tests for balance validation logic."""

    def setup_method(self):
        self.service = ExtractionService()

    def test_balance_valid(self):
        """Test that valid balances pass validation."""
        extracted = {
            "opening_balance": "1000.00",
            "closing_balance": "1100.00",
            "transactions": [
                {"amount": "200.00", "direction": "IN"},
                {"amount": "100.00", "direction": "OUT"},
            ],
        }
        result = self.service._validate_balance(extracted)
        assert result["balance_valid"] is True
        assert result["difference"] == "0.00"

    def test_balance_invalid(self):
        """Test that invalid balances fail validation."""
        extracted = {
            "opening_balance": "1000.00",
            "closing_balance": "2000.00",  # Wrong!
            "transactions": [
                {"amount": "100.00", "direction": "IN"},
            ],
        }
        result = self.service._validate_balance(extracted)
        assert result["balance_valid"] is False
        assert "mismatch" in result["notes"].lower()

    def test_balance_tolerance(self):
        """Test that small differences are tolerated."""
        extracted = {
            "opening_balance": "1000.00",
            "closing_balance": "1100.005",  # Slightly off
            "transactions": [
                {"amount": "100.00", "direction": "IN"},
            ],
        }
        result = self.service._validate_balance(extracted)
        # Should pass with 0.10 tolerance
        assert result["balance_valid"] is True


class TestConfidenceScoring:
    """Tests for confidence scoring logic."""

    def setup_method(self):
        self.service = ExtractionService()

    def test_high_confidence(self):
        """Test that complete data gets high confidence."""
        extracted = {
            "institution": "DBS",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "1000.00",
            "closing_balance": "1100.00",
            "transactions": [
                {"date": "2025-01-15", "amount": "100.00", "direction": "IN"},
            ],
        }
        validation = {"balance_valid": True, "difference": "0.00"}
        score = self.service._compute_confidence(extracted, validation)
        assert score >= 85, f"Expected high confidence, got {score}"

    def test_medium_confidence(self):
        """Test that partial data gets medium confidence."""
        extracted = {
            "institution": "DBS",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "1000.00",
            "closing_balance": "1150.00",  # Slight mismatch
            "transactions": [
                {"date": "2025-01-15", "amount": "100.00", "direction": "IN"},
            ],
        }
        validation = {"balance_valid": False, "difference": "50.00"}
        score = self.service._compute_confidence(extracted, validation)
        assert 60 <= score < 85, f"Expected medium confidence, got {score}"

    def test_low_confidence_empty_transactions(self):
        """Test that no transactions lowers confidence."""
        extracted = {
            "institution": "DBS",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "0",
            "closing_balance": "0",
            "transactions": [],  # No transactions
        }
        validation = {"balance_valid": True, "difference": "0.00"}
        score = self.service._compute_confidence(extracted, validation)
        assert score < 100, "Empty transactions should lower confidence"


class TestFixtureData:
    """Tests using real parsed fixture data."""

    @pytest.fixture
    def dbs_fixture(self):
        fixture_path = FIXTURES_DIR / "2504_parsed.json"
        if fixture_path.exists():
            with open(fixture_path) as f:
                return json.load(f)
        pytest.skip("DBS fixture not found")

    @pytest.fixture
    def maribank_fixture(self):
        fixture_path = FIXTURES_DIR / "Apr2025_MariBank_e-Statement_parsed.json"
        if fixture_path.exists():
            with open(fixture_path) as f:
                return json.load(f)
        pytest.skip("MariBank fixture not found")

    @pytest.fixture
    def gxs_fixture(self):
        fixture_path = FIXTURES_DIR / "gxs-2506_parsed.json"
        if fixture_path.exists():
            with open(fixture_path) as f:
                return json.load(f)
        pytest.skip("GXS fixture not found")

    def test_dbs_fixture_structure(self, dbs_fixture):
        """Test DBS fixture has correct structure."""
        assert dbs_fixture["success"] is True
        assert dbs_fixture["institution"] == "DBS"
        assert "statement" in dbs_fixture
        assert "events" in dbs_fixture
        assert len(dbs_fixture["events"]) > 0

    def test_dbs_balance_reconciliation(self, dbs_fixture):
        """Test DBS fixture balances reconcile."""
        stmt = dbs_fixture["statement"]
        events = dbs_fixture["events"]
        
        opening = Decimal(stmt["opening_balance"])
        closing = Decimal(stmt["closing_balance"])
        
        net = sum(
            Decimal(e["amount"]) if e["direction"] == "IN" else -Decimal(e["amount"])
            for e in events
        )
        
        expected_closing = opening + net
        diff = abs(closing - expected_closing)
        
        # Allow some tolerance due to potential rounding
        assert diff < Decimal("1.00"), f"Balance mismatch: {diff}"

    def test_maribank_fixture_merchants_sanitized(self, maribank_fixture):
        """Test MariBank fixture has sanitized merchant names."""
        events = maribank_fixture["events"]
        for event in events:
            desc = event.get("description", "")
            # Should not contain full merchant names
            assert "HAWKERLAB" not in desc, "Merchant name not sanitized"
            assert "DELICIOUS LITTLE LEAVES" not in desc, "Merchant name not sanitized"

    def test_gxs_fixture_daily_interest(self, gxs_fixture):
        """Test GXS fixture has daily interest entries."""
        events = gxs_fixture["events"]
        interest_events = [e for e in events if "Interest" in e.get("description", "")]
        assert len(interest_events) > 20, "GXS should have daily interest entries"

    def test_all_fixtures_have_dates(self, dbs_fixture, maribank_fixture, gxs_fixture):
        """Test all fixture events have valid dates."""
        for fixture in [dbs_fixture, maribank_fixture, gxs_fixture]:
            for event in fixture["events"]:
                assert event.get("date"), "Event missing date"
                # Check date format
                assert len(event["date"]) == 10, f"Invalid date format: {event['date']}"
                assert event["date"][4] == "-", f"Invalid date format: {event['date']}"


class TestPromptGeneration:
    """Tests for prompt generation functions."""

    def test_get_parsing_prompt_default(self):
        """Test default parsing prompt."""
        from src.prompts import get_parsing_prompt
        prompt = get_parsing_prompt()
        assert "financial statement parser" in prompt.lower()
        assert "JSON" in prompt
        assert "transactions" in prompt

    def test_get_parsing_prompt_dbs(self):
        """Test DBS-specific prompt."""
        from src.prompts import get_parsing_prompt
        prompt = get_parsing_prompt("DBS")
        assert "DBS" in prompt
        assert "Singapore" in prompt or "GIRO" in prompt or "PayNow" in prompt

    def test_get_parsing_prompt_cmb(self):
        """Test CMB-specific prompt."""
        from src.prompts import get_parsing_prompt
        prompt = get_parsing_prompt("CMB")
        assert "CMB" in prompt or "招商" in prompt
        assert "Chinese" in prompt or "中文" in prompt

    def test_get_parsing_prompt_unknown_institution(self):
        """Test with unknown institution."""
        from src.prompts import get_parsing_prompt
        prompt = get_parsing_prompt("UnknownBank")
        # Should return base prompt without institution hints
        assert "financial statement parser" in prompt.lower()

    def test_get_parsing_prompt_futu(self):
        """Test Futu-specific prompt."""
        from src.prompts import get_parsing_prompt
        prompt = get_parsing_prompt("Futu")
        assert "Futu" in prompt or "富途" in prompt

    def test_get_parsing_prompt_gxs(self):
        """Test GXS-specific prompt."""
        from src.prompts import get_parsing_prompt
        prompt = get_parsing_prompt("GXS")
        assert "GXS" in prompt

    def test_get_parsing_prompt_maribank(self):
        """Test MariBank-specific prompt."""
        from src.prompts import get_parsing_prompt
        prompt = get_parsing_prompt("MariBank")
        assert "MariBank" in prompt


class TestExtractionServiceHelpers:
    """Tests for extraction service helper methods."""

    def setup_method(self):
        from src.services.extraction import ExtractionService
        self.service = ExtractionService()

    def test_compute_event_confidence_complete(self):
        """Test event confidence with complete data."""
        event = {
            "date": "2025-01-15",
            "description": "Test transaction",
            "amount": "100.00",
            "direction": "IN",
        }
        conf = self.service._compute_event_confidence(event)
        assert conf.value == "high"

    def test_compute_event_confidence_missing_fields(self):
        """Test event confidence with missing fields."""
        event = {
            "date": "2025-01-15",
            "amount": "100.00",
        }
        conf = self.service._compute_event_confidence(event)
        assert conf.value in ["medium", "low"]

    def test_compute_event_confidence_invalid_date(self):
        """Test event confidence with invalid date format."""
        event = {
            "date": "invalid-date",
            "description": "Test",
            "amount": "100.00",
            "direction": "IN",
        }
        conf = self.service._compute_event_confidence(event)
        # Should be lower confidence due to invalid date
        assert conf.value in ["medium", "low"]

    def test_compute_event_confidence_null_date(self):
        """Test event confidence with null date."""
        event = {
            "date": None,
            "description": "Test",
            "amount": "100.00",
            "direction": "IN",
        }
        conf = self.service._compute_event_confidence(event)
        assert conf.value == "low"

    def test_safe_date_valid(self):
        """Test _safe_date with valid input."""
        d = self.service._safe_date("2025-01-01")
        assert d.year == 2025
        assert d.month == 1
        assert d.day == 1

    def test_safe_date_invalid_format(self):
        """Test _safe_date with invalid format."""
        import pytest
        with pytest.raises(ValueError, match="Invalid date format"):
            self.service._safe_date("invalid-date")

    def test_safe_date_empty(self):
        """Test _safe_date with empty input."""
        import pytest
        with pytest.raises(ValueError, match="Date is required"):
            self.service._safe_date(None)

    def test_safe_decimal_valid(self):
        """Test _safe_decimal with valid input."""
        d = self.service._safe_decimal("100.50")
        from decimal import Decimal
        assert d == Decimal("100.50")

    def test_safe_decimal_invalid(self):
        """Test _safe_decimal with invalid input."""
        d = self.service._safe_decimal("abc")
        from decimal import Decimal
        assert d == Decimal("0.00")

    def test_safe_decimal_none(self):
        """Test _safe_decimal with None."""
        d = self.service._safe_decimal(None)
        from decimal import Decimal
        assert d == Decimal("0.00")

    def test_compute_confidence_missing_transactions(self):
        """Test confidence with missing transactions key."""
        extracted = {
            "institution": "DBS",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "0",
            "closing_balance": "0",
        }
        validation = {"balance_valid": True, "difference": "0.00"}
        score = self.service._compute_confidence(extracted, validation)
        assert 0 <= score <= 100
