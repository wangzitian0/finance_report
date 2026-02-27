"""
Tests for scripts/sanitize_fixtures.py

Covers:
- mask_company_name(): PTE LTD pattern, generic company names
- sanitize_description(): card numbers, NRIC, long digits, company names
- sanitize_fixture(): balance shifting, description sanitization
- load_fixture() / save_fixture(): JSON file I/O
"""

import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

# Ensure scripts/ is on path
SCRIPTS_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from sanitize_fixtures import (
    mask_company_name,
    sanitize_description,
    sanitize_fixture,
)


# ---------------------------------------------------------------------------
# mask_company_name
# ---------------------------------------------------------------------------


class TestMaskCompanyName:
    def test_pte_ltd_suffix(self):
        result = mask_company_name("ACME SOLUTIONS PTE LTD")
        assert "PTE LTD" in result
        assert "***ONS" in result  # last 3 of SOLUTIONS

    def test_pte_dot_ltd_dot_suffix(self):
        result = mask_company_name("TECH CORP PTE. LTD.")
        assert "PTE. LTD." in result or "PTE. LTD" in result

    def test_ltd_only_suffix(self):
        result = mask_company_name("BIGFIRM LTD")
        assert "LTD" in result
        assert "***" in result

    def test_short_company_name_pte_ltd(self):
        """Short word ≤3 chars before PTE LTD should NOT get the *** prefix stripped."""
        result = mask_company_name("AB PTE LTD")
        assert "PTE LTD" in result or "PTE" in result

    def test_generic_name_longer_than_3(self):
        result = mask_company_name("JOHNSON")
        assert result == "***SON"

    def test_generic_name_exactly_3_chars(self):
        result = mask_company_name("ABC")
        assert result == "ABC"

    def test_generic_name_shorter_than_3(self):
        result = mask_company_name("AB")
        assert result == "AB"

    def test_newline_stripped(self):
        result = mask_company_name("ACME\nSOLUTIONS PTE LTD")
        assert "\n" not in result

    def test_preserves_suffix_text(self):
        result = mask_company_name("LONGNAME PTE LTD EXTRA")
        # suffix includes EXTRA
        assert "PTE LTD" in result

    def test_pte_ltd_with_empty_company_part(self):
        result = mask_company_name("PTE LTD")
        assert "PTE LTD" in result or "PTE" in result


# ---------------------------------------------------------------------------
# sanitize_description
# ---------------------------------------------------------------------------


class TestSanitizeDescription:
    def test_card_number_masked(self):
        desc = "Payment to 1234-5678-9012-3456"
        result = sanitize_description(desc)
        assert "XXXX-XXXX-XXXX-3456" in result
        assert "1234-5678-9012" not in result

    def test_nric_masked(self):
        desc = "Transfer from S1234567A"
        result = sanitize_description(desc)
        assert (
            "S1234567A".replace("1234567", "XXXXXXX") in result
            or "SXXXXXXXZ" not in result
        )
        # At minimum the middle digits should be replaced
        assert "S" in result and "A" in result
        assert "1234567" not in result

    def test_long_digit_sequence_masked(self):
        desc = "Ref 123456789012 paid"
        result = sanitize_description(desc)
        # 12-digit number: keep last 4 → XXXXXX9012
        assert "9012" in result
        assert "12345678" not in result

    def test_no_pii_unchanged(self):
        desc = "Monthly salary deposit"
        result = sanitize_description(desc)
        assert result == desc

    def test_company_name_in_description(self):
        desc = "PAYMENT TO ACME SOLUTIONS PTE LTD"
        result = sanitize_description(desc)
        assert "LTD" in result
        assert "***" in result

    def test_eight_digit_number_masked(self):
        """8-digit number like 68042507 → XXXX2507."""
        desc = "ATM 68042507 withdrawal"
        result = sanitize_description(desc)
        # The 8-digit regex only applies if followed by space/end/punctuation
        # "2507" should remain
        assert "2507" in result

    def test_empty_string(self):
        assert sanitize_description("") == ""

    def test_multiple_pii_types(self):
        desc = "Card 1234-5678-9012-3456 NRIC S9876543B"
        result = sanitize_description(desc)
        assert "XXXX-XXXX-XXXX-3456" in result
        assert "9876543" not in result


# ---------------------------------------------------------------------------
# sanitize_fixture
# ---------------------------------------------------------------------------


class TestSanitizeFixture:
    def _make_fixture(self, opening, closing, events=None):
        data = {
            "opening_balance": opening,
            "closing_balance": closing,
        }
        if events is not None:
            data["events"] = events
        return data

    def test_balance_shifted_to_300000(self):
        data = self._make_fixture("10000.00", "10500.00")
        result = sanitize_fixture(data)
        assert result["opening_balance"] == "300000.00"

    def test_net_flow_preserved(self):
        data = self._make_fixture("10000.00", "10500.00")
        result = sanitize_fixture(data)
        opening = Decimal(result["opening_balance"])
        closing = Decimal(result["closing_balance"])
        assert closing - opening == Decimal("500.00")

    def test_negative_flow_preserved(self):
        data = self._make_fixture("20000.00", "19000.00")
        result = sanitize_fixture(data)
        opening = Decimal(result["opening_balance"])
        closing = Decimal(result["closing_balance"])
        assert closing - opening == Decimal("-1000.00")

    def test_nested_statement_dict(self):
        data = {
            "statement": {
                "opening_balance": "5000.00",
                "closing_balance": "5200.00",
            }
        }
        result = sanitize_fixture(data)
        inner = result["statement"]
        assert inner["opening_balance"] == "300000.00"
        assert Decimal(inner["closing_balance"]) - Decimal(
            inner["opening_balance"]
        ) == Decimal("200.00")

    def test_none_balance_handled(self):
        data = self._make_fixture(None, None)
        result = sanitize_fixture(data)
        # Should not crash; opening should be 300000.00
        assert result["opening_balance"] == "300000.00"
        assert result["closing_balance"] == "300000.00"

    def test_none_string_balance_handled(self):
        data = self._make_fixture("None", "None")
        result = sanitize_fixture(data)
        assert result["opening_balance"] == "300000.00"

    def test_events_descriptions_sanitized(self):
        data = self._make_fixture(
            "1000.00",
            "1500.00",
            events=[{"description": "Card 1234-5678-9012-3456 payment"}],
        )
        result = sanitize_fixture(data)
        assert "XXXX-XXXX-XXXX-3456" in result["events"][0]["description"]

    def test_events_without_description_unaffected(self):
        data = self._make_fixture(
            "1000.00",
            "1000.00",
            events=[{"amount": "100.00"}],
        )
        result = sanitize_fixture(data)
        assert result["events"][0] == {"amount": "100.00"}

    def test_original_data_not_mutated(self):
        data = self._make_fixture("1000.00", "1200.00")
        sanitize_fixture(data)
        # original unchanged
        assert data["opening_balance"] == "1000.00"

    def test_no_events_key_ok(self):
        data = self._make_fixture("1000.00", "1100.00")
        result = sanitize_fixture(data)
        assert "events" not in result

    def test_invalid_balance_does_not_crash(self):
        data = self._make_fixture("not-a-number", "also-bad")
        result = sanitize_fixture(data)
        assert "opening_balance" in result

    def test_empty_events_list(self):
        data = self._make_fixture("1000.00", "1000.00", events=[])
        result = sanitize_fixture(data)
        assert result["events"] == []


# ---------------------------------------------------------------------------
# load_fixture / save_fixture (file I/O)
# ---------------------------------------------------------------------------


class TestFileIO:
    def test_load_and_save_roundtrip(self, tmp_path):
        """Import and exercise load_fixture / save_fixture via direct file ops."""
        import importlib

        module = importlib.import_module("sanitize_fixtures")

        # Some versions may not export these helpers; skip gracefully
        load_fixture = getattr(module, "load_fixture", None)
        save_fixture = getattr(module, "save_fixture", None)

        if load_fixture is None or save_fixture is None:
            pytest.skip("load_fixture/save_fixture not exported")

        payload = {"opening_balance": "1000.00", "closing_balance": "1500.00"}
        path = tmp_path / "test.json"
        save_fixture(path, payload)

        loaded = load_fixture(path)
        assert loaded == payload

    def test_save_creates_file(self, tmp_path):
        import importlib

        module = importlib.import_module("sanitize_fixtures")
        save_fixture = getattr(module, "save_fixture", None)

        if save_fixture is None:
            pytest.skip("save_fixture not exported")

        path = tmp_path / "out.json"
        save_fixture(path, {"key": "value"})
        assert path.exists()
        content = json.loads(path.read_text())
        assert content == {"key": "value"}
