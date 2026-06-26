"""Tests for the document extraction service."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from src.services.extraction import ExtractionError, ExtractionService
from src.services.validation import compute_confidence_score, validate_balance

# Get fixtures directory
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


class TestBalanceValidation:
    """Tests for balance validation logic."""

    def setup_method(self):
        self.service = ExtractionService()

    def test_balance_valid(self):
        """AC13.1.1: Test that valid balances pass validation."""
        extracted = {
            "opening_balance": "1000.00",
            "closing_balance": "1100.00",
            "transactions": [
                {"amount": "200.00", "direction": "IN"},
                {"amount": "100.00", "direction": "OUT"},
            ],
        }
        result = validate_balance(extracted)
        assert result["balance_valid"] is True
        assert result["difference"] == "0.00"

    def test_balance_invalid(self):
        """AC13.1.2: Test that invalid balances fail validation."""
        extracted = {
            "opening_balance": "1000.00",
            "closing_balance": "2000.00",  # Wrong!
            "transactions": [
                {"amount": "100.00", "direction": "IN"},
            ],
        }
        result = validate_balance(extracted)
        assert result["balance_valid"] is False
        assert "mismatch" in result["notes"].lower()

    def test_balance_tolerance(self):
        """AC13.1.3: Test that small differences are tolerated."""
        extracted = {
            "opening_balance": "1000.00",
            "closing_balance": "1100.005",  # Slightly off
            "transactions": [
                {"amount": "100.00", "direction": "IN"},
            ],
        }
        result = validate_balance(extracted)
        # Should pass with 0.10 tolerance
        assert result["balance_valid"] is True


class TestConfidenceScoring:
    """Tests for confidence scoring logic."""

    def setup_method(self):
        self.service = ExtractionService()

    def test_high_confidence(self):
        """AC13.2.1: Test that complete data gets high confidence (Auto-Accept)."""
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
        score = compute_confidence_score(extracted, validation)
        assert score >= 85, f"Expected high confidence, got {score}"

    def test_medium_confidence(self):
        """AC13.2.2: Test that partial data gets medium confidence (Review)."""
        extracted = {
            "institution": "DBS",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "1000.00",
            "closing_balance": "1105.00",  # Slight mismatch
            "transactions": [
                {"date": "2025-01-15", "amount": "100.00", "direction": "IN"},
            ],
        }
        validation = {"balance_valid": False, "difference": "5.00"}
        score = compute_confidence_score(extracted, validation)
        assert 60 <= score < 85, f"Expected medium confidence, got {score}"

    def test_low_confidence_empty_transactions(self):
        """AC3.3.3/AC13.2.3: Missing transactions and invalid fields route to manual confidence."""
        extracted = {
            "institution": "DBS",
            "period_start": "invalid-date",
            "period_end": "2025-01-31",
            "opening_balance": "0",
            "closing_balance": "0",
            "transactions": [],  # No transactions
        }
        validation = {"balance_valid": False, "difference": "100.00"}
        score = compute_confidence_score(extracted, validation)
        assert score < 60, "Low-confidence statements should require manual review"


class TestFixtureData:
    """Tests using real parsed fixture data."""

    @pytest.fixture
    def dbs_fixture(self):
        fixture_path = FIXTURES_DIR / "2504_parsed.json"
        if fixture_path.exists():
            with open(fixture_path) as f:
                return json.load(f)
        return None  # Pass but no data

    @pytest.fixture
    def maribank_fixture(self):
        fixture_path = FIXTURES_DIR / "Apr2025_MariBank_e-Statement_parsed.json"
        if fixture_path.exists():
            with open(fixture_path) as f:
                return json.load(f)
        return None  # Pass but no data

    @pytest.fixture
    def gxs_fixture(self):
        fixture_path = FIXTURES_DIR / "gxs-2506_parsed.json"
        if fixture_path.exists():
            with open(fixture_path) as f:
                return json.load(f)
        return None  # Pass but no data

    def test_dbs_fixture_structure(self, dbs_fixture):
        """AC13.3.1: Test DBS fixture has correct structure."""
        if dbs_fixture is None:
            return
        assert dbs_fixture["success"] is True
        assert dbs_fixture["institution"] == "DBS"
        assert "statement" in dbs_fixture
        assert "events" in dbs_fixture
        assert len(dbs_fixture["events"]) > 0

    def test_dbs_balance_reconciliation(self, dbs_fixture):
        """AC13.3.2: Test DBS fixture balances reconcile."""
        if dbs_fixture is None:
            return
        stmt = dbs_fixture["statement"]
        events = dbs_fixture["events"]

        opening = Decimal(stmt["opening_balance"])
        closing = Decimal(stmt["closing_balance"])

        net = sum(Decimal(e["amount"]) if e["direction"] == "IN" else -Decimal(e["amount"]) for e in events)

        expected_closing = opening + net
        diff = abs(closing - expected_closing)

        # Allow some tolerance due to potential rounding
        assert diff < Decimal("1.00"), f"Balance mismatch: {diff}"

    def test_maribank_fixture_merchants_sanitized(self, maribank_fixture):
        """AC13.3.3: Test MariBank fixture has sanitized merchant names."""
        if maribank_fixture is None:
            return
        events = maribank_fixture["events"]
        for event in events:
            desc = event.get("description", "")
            # Should not contain full merchant names
            assert "HAWKERLAB" not in desc, "Merchant name not sanitized"
            assert "DELICIOUS LITTLE LEAVES" not in desc, "Merchant name not sanitized"

    def test_gxs_fixture_daily_interest(self, gxs_fixture):
        """AC13.3.4: Test GXS fixture has daily interest entries."""
        if gxs_fixture is None:
            return
        events = gxs_fixture["events"]
        interest_events = [e for e in events if "Interest" in e.get("description", "")]
        assert len(interest_events) > 20, "GXS should have daily interest entries"

    def test_all_fixtures_have_dates(self, dbs_fixture, maribank_fixture, gxs_fixture):
        """AC13.3.5: Test all fixture events have valid dates."""
        for fixture in [dbs_fixture, maribank_fixture, gxs_fixture]:
            if fixture is None:
                continue
            for event in fixture["events"]:
                assert event.get("date"), "Event missing date"
                # Check date format
                assert len(event["date"]) == 10, f"Invalid date format: {event['date']}"
                assert event["date"][4] == "-", f"Invalid date format: {event['date']}"


class TestPromptGeneration:
    """Tests for prompt generation functions."""

    def test_get_parsing_prompt_default(self):
        """AC13.4.1 AC18.1.1: Test default parsing prompt."""
        from src.prompts import get_parsing_prompt

        prompt = get_parsing_prompt()
        assert "financial statement parser" in prompt.lower()
        assert "JSON" in prompt
        assert "transactions" in prompt
        assert "suggested_category" in prompt
        assert "category_confidence" in prompt
        # Multi-section extraction + per-currency completeness self-check (#1086/#1123)
        assert "MULTI-SECTION" in prompt
        assert "EVERY section" in prompt
        assert "COMPLETENESS SELF-CHECK" in prompt
        assert "reconcile EACH currency separately" in prompt
        assert "Never add amounts across different currencies" in prompt
        # Guardrails: no double-counting of mirrored legs, no fabrication (CR #1124)
        assert "EXACTLY ONCE" in prompt
        assert "do NOT double-count" in prompt
        assert "NEVER invent, fabricate" in prompt

    def test_get_parsing_prompt_dbs(self):
        """AC13.4.2: Test DBS-specific prompt."""
        from src.prompts import get_parsing_prompt

        prompt = get_parsing_prompt("DBS")
        assert "DBS" in prompt
        assert "Singapore" in prompt or "GIRO" in prompt or "PayNow" in prompt

    def test_get_parsing_prompt_cmb(self):
        """AC13.4.3: Test CMB-specific prompt."""
        from src.prompts import get_parsing_prompt

        prompt = get_parsing_prompt("CMB")
        assert "CMB" in prompt or "招商" in prompt
        assert "Chinese" in prompt or "中文" in prompt

    def test_get_parsing_prompt_unknown_institution(self):
        """AC13.4.4: Test with unknown institution."""
        from src.prompts import get_parsing_prompt

        prompt = get_parsing_prompt("UnknownBank")
        # Should return base prompt without institution hints
        assert "financial statement parser" in prompt.lower()

    def test_get_parsing_prompt_futu(self):
        """AC13.4.5: Test Futu-specific prompt."""
        from src.prompts import get_parsing_prompt

        prompt = get_parsing_prompt("Futu")
        assert "Futu" in prompt or "富途" in prompt

    def test_get_parsing_prompt_gxs(self):
        """AC13.4.6: Test GXS-specific prompt."""
        from src.prompts import get_parsing_prompt

        prompt = get_parsing_prompt("GXS")
        assert "GXS" in prompt

    def test_get_parsing_prompt_maribank(self):
        """AC13.4.7: Test MariBank-specific prompt."""
        from src.prompts import get_parsing_prompt

        prompt = get_parsing_prompt("MariBank")
        assert "MariBank" in prompt
        # MariBank hint must name the savings<->Mari Invest transfer legs (#1086)
        assert "Buy - Mari Invest" in prompt
        assert "Sell - Mari Invest" in prompt


class TestMediaPayloadBuilder:
    """Tests for _build_media_payload method."""

    def setup_method(self):
        from src.services.extraction import ExtractionService

        self.service = ExtractionService()

    def test_pdf_url_uses_zai_image_url_type(self):
        """AC13.5.1: Z.AI PDF URLs must use documented image_url payloads."""
        data = "https://s3.example.test/bucket/statement.pdf?signature=secret"
        payload = self.service._build_media_payload("pdf", "application/pdf", data)

        assert payload["type"] == "image_url"
        assert payload["image_url"]["url"] == data

    def test_pdf_base64_keeps_legacy_file_type(self):
        """AC13.5.1: Base64 PDFs keep legacy payload shape for non-URL APIs."""
        data = "data:application/pdf;base64,JVBERi0xLjQ="
        payload = self.service._build_media_payload("pdf", "application/pdf", data)

        assert payload["type"] == "file"
        assert payload["file"]["filename"] == "statement.pdf"
        assert payload["file"]["file_data"] == data

    def test_pdf_content_renders_to_image_payloads_for_zai_vision(self):
        """AC13.5.1: Uploaded PDFs can be converted to image_url payloads for Z.AI vision."""
        from io import BytesIO

        from reportlab.pdfgen import canvas

        buffer = BytesIO()
        pdf = canvas.Canvas(buffer)
        pdf.drawString(72, 720, "DBS statement fixture")
        pdf.save()

        payloads = self.service._render_pdf_pages_as_image_payloads(buffer.getvalue())

        assert len(payloads) == 1
        assert payloads[0]["type"] == "image_url"
        assert payloads[0]["image_url"]["url"].startswith("data:image/png;base64,")

    def test_prefer_url_rejects_private_urls_without_falling_back(self):
        """AC13.5.1: Z.AI PDF URL fallback must not accept private object URLs."""
        with pytest.raises(ExtractionError, match="No valid file content or accessible URL"):
            self.service._build_ai_file_input(
                file_content=None,
                file_url="http://10.0.0.5/statements/file.pdf?token=secret",
                file_type="pdf",
                mime_type="application/pdf",
                prefer_url=True,
            )

    def test_png_uses_image_url_type(self):
        """AC13.5.2: Test that PNG images use 'image_url' type."""
        data = "data:image/png;base64,iVBORw0KGgo="
        payload = self.service._build_media_payload("png", "image/png", data)

        assert payload["type"] == "image_url"
        assert "image_url" in payload
        assert payload["image_url"]["url"] == data

    def test_jpg_uses_image_url_type(self):
        """AC13.5.3: Test that JPG images use 'image_url' type."""
        data = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
        payload = self.service._build_media_payload("jpg", "image/jpeg", data)

        assert payload["type"] == "image_url"
        assert payload["image_url"]["url"] == data

    def test_jpeg_uses_image_url_type(self):
        """AC13.5.4: Test that JPEG images use 'image_url' type."""
        data = "https://example.com/statement.jpeg"
        payload = self.service._build_media_payload("jpeg", "image/jpeg", data)

        assert payload["type"] == "image_url"
        assert payload["image_url"]["url"] == data


class TestInstitutionDetection:
    """Tests for institution auto-detection in parse_document."""

    def setup_method(self):
        from src.services.extraction import ExtractionService

        self.service = ExtractionService()

    async def test_csv_requires_institution(self):
        """AC13.6.1: Test that CSV parsing raises error when institution is None."""
        from src.services.extraction import ExtractionError

        with pytest.raises(ExtractionError, match="Institution is required for CSV"):
            await self.service.parse_document(
                file_path=Path("test.csv"),
                institution=None,
                user_id=uuid4(),
                file_type="csv",
                account_id=None,
                file_content=b"date,amount\n2025-01-01,100",
                file_hash=None,
                file_url=None,
                original_filename="test.csv",
            )

    async def test_parse_document_accepts_none_institution_for_pdf(self):
        """AC13.6.2: Test that parse_document accepts institution=None for PDFs (AI auto-detect)."""
        with pytest.raises(Exception) as exc_info:
            await self.service.parse_document(
                file_path=Path("test.pdf"),
                institution=None,
                user_id=uuid4(),
                file_type="pdf",
                account_id=None,
                file_content=b"fake pdf content",
                file_hash=None,
                file_url=None,
                original_filename="test.pdf",
            )
        assert "Institution is required" not in str(exc_info.value)


class TestExtractionServiceHelpers:
    """Tests for extraction service helper methods."""

    def setup_method(self):
        from src.services.extraction import ExtractionService

        self.service = ExtractionService()

    def test_safe_date_valid(self):
        """AC13.7.5: Test _safe_date with valid input."""
        d = self.service._safe_date("2025-01-01")
        assert d.year == 2025
        assert d.month == 1
        assert d.day == 1

    def test_safe_date_invalid_format(self):
        """AC13.7.6: Test _safe_date with invalid format."""
        import pytest

        with pytest.raises(ValueError, match="Invalid date format"):
            self.service._safe_date("invalid-date")

    def test_safe_date_empty(self):
        """AC13.7.7: Test _safe_date with empty input."""
        import pytest

        with pytest.raises(ValueError, match="Date is required"):
            self.service._safe_date(None)

    def test_safe_decimal_valid(self):
        """AC13.7.8: Test _safe_decimal with valid input."""
        d = self.service._safe_decimal("100.50")
        from decimal import Decimal

        assert d == Decimal("100.50")

    def test_safe_decimal_invalid(self):
        """AC13.7.9: Test _safe_decimal with invalid input."""
        import pytest

        with pytest.raises(ValueError, match="Invalid decimal value"):
            self.service._safe_decimal("abc")

    def test_safe_decimal_none(self):
        """AC13.7.10: Test _safe_decimal with None."""
        assert self.service._safe_decimal(None) is None

    def test_safe_decimal_none_required(self):
        """AC13.7.11: Test _safe_decimal with None and required=True."""
        import pytest

        with pytest.raises(ValueError, match="Decimal value is required"):
            self.service._safe_decimal(None, required=True)

    def test_compute_confidence_missing_transactions(self):
        """AC13.7.12: Test confidence with missing transactions key."""
        extracted = {
            "institution": "DBS",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "0",
            "closing_balance": "0",
        }
        validation = {"balance_valid": True, "difference": "0.00"}
        score = compute_confidence_score(extracted, validation)
        assert 0 <= score <= 100

    async def test_parse_document_accepts_force_model(self):
        """AC13.6.3: Test that parse_document accepts force_model parameter."""
        service = ExtractionService()
        with pytest.raises(ExtractionError, match="File content is required"):
            await service.parse_document(
                file_path=Path("test.pdf"),
                institution="DBS",
                user_id=uuid4(),
                file_type="pdf",
                account_id=None,
                file_content=None,
                file_hash=None,
                file_url=None,
                original_filename=None,
                force_model="google/gemini-2.0-flash-exp:free",
            )


class TestBalanceProgression:
    def test_consistent_chain(self):
        """AC13.8.1: Test consistent balance chain scores full marks."""
        from src.services.validation import _score_balance_progression

        txns = [
            {"balance_after": "1000.00", "amount": "100.00", "direction": "IN"},
            {"balance_after": "1100.00", "amount": "100.00", "direction": "IN"},
            {"balance_after": "1050.00", "amount": "50.00", "direction": "OUT"},
        ]
        assert _score_balance_progression(txns) == 10

    def test_inconsistent_chain(self):
        """AC13.8.2: Test inconsistent balance chain scores zero."""
        from src.services.validation import _score_balance_progression

        txns = [
            {"balance_after": "1000.00", "amount": "100.00", "direction": "IN"},
            {"balance_after": "5000.00", "amount": "100.00", "direction": "IN"},
        ]
        assert _score_balance_progression(txns) == 0

    def test_single_txn(self):
        """AC13.8.3: Test single transaction scores zero."""
        from src.services.validation import _score_balance_progression

        txns = [{"balance_after": "1000.00", "amount": "100.00", "direction": "IN"}]
        assert _score_balance_progression(txns) == 0

    def test_no_balance_after(self):
        """AC13.8.4: Test transactions without balance_after score zero."""
        from src.services.validation import _score_balance_progression

        txns = [
            {"amount": "100.00", "direction": "IN"},
            {"amount": "200.00", "direction": "OUT"},
        ]
        assert _score_balance_progression(txns) == 0

    def test_empty_list(self):
        """AC13.8.5: Test empty transaction list scores zero."""
        from src.services.validation import _score_balance_progression

        assert _score_balance_progression([]) == 0

    def test_partial_consistency(self):
        """AC13.8.6: Test partial balance consistency scores half."""
        from src.services.validation import _score_balance_progression

        txns = [
            {"balance_after": "1000.00", "amount": "100.00", "direction": "IN"},
            {"balance_after": "1100.00", "amount": "100.00", "direction": "IN"},
            {"balance_after": "9999.00", "amount": "50.00", "direction": "OUT"},
        ]
        assert _score_balance_progression(txns) == 5


class TestCurrencyConsistency:
    def test_all_match_header(self):
        """AC13.8.7: Test all currencies match header scores full."""
        from src.services.validation import _score_currency_consistency

        txns = [{"currency": "SGD"}, {"currency": "SGD"}, {"currency": "SGD"}]
        assert _score_currency_consistency(txns, "SGD") == 5

    def test_none_match(self):
        """AC13.8.8: Test no currencies match header scores zero."""
        from src.services.validation import _score_currency_consistency

        txns = [{"currency": "USD"}, {"currency": "EUR"}]
        assert _score_currency_consistency(txns, "SGD") == 0

    def test_no_header_uses_most_common(self):
        """AC13.8.9: Test no header uses most common currency."""
        from src.services.validation import _score_currency_consistency

        txns = [{"currency": "SGD"}, {"currency": "SGD"}, {"currency": "USD"}]
        assert _score_currency_consistency(txns, None) == 3

    def test_no_currencies(self):
        """AC13.8.10: Test no currencies in transactions scores zero."""
        from src.services.validation import _score_currency_consistency

        txns = [{"amount": "100"}, {"amount": "200"}]
        assert _score_currency_consistency(txns, "SGD") == 0

    def test_empty_list(self):
        """AC13.8.11: Test empty currency list scores zero."""
        from src.services.validation import _score_currency_consistency

        assert _score_currency_consistency([], "SGD") == 0

    def test_mixed_currencies_partial(self):
        """AC13.8.12: Test mixed currencies partial match."""
        from src.services.validation import _score_currency_consistency

        txns = [{"currency": "SGD"}, {"currency": "USD"}, {"currency": "SGD"}, {"currency": "SGD"}]
        assert _score_currency_consistency(txns, "SGD") == 3

    def test_missing_currencies_penalized(self):
        """AC13.8.13: Test missing currencies penalized."""
        from src.services.validation import _score_currency_consistency

        txns = [{"currency": "SGD"}, {"amount": "100"}, {"amount": "200"}]
        assert _score_currency_consistency(txns, "SGD") == 1


class TestConfidenceScoringV2:
    def test_full_score_with_all_factors(self):
        """AC13.9.1: Test full score with all factors."""
        txns = [
            {
                "date": "2025-01-01",
                "description": "A",
                "amount": "100.00",
                "direction": "IN",
                "currency": "SGD",
                "balance_after": "1000.00",
            },
            {
                "date": "2025-01-02",
                "description": "B",
                "amount": "50.00",
                "direction": "IN",
                "currency": "SGD",
                "balance_after": "1050.00",
            },
        ]
        extracted = {
            "institution": "DBS",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "900.00",
            "closing_balance": "1050.00",
            "currency": "SGD",
            "transactions": txns,
        }
        balance_result = {"balance_valid": True, "difference": "0.00"}
        from src.services.validation import compute_confidence_score

        score = compute_confidence_score(extracted, balance_result)
        assert score == 100

    def test_no_new_factors_caps_at_85(self):
        """AC13.9.2: Test no new factors caps at 85."""
        txns = [
            {"date": "2025-01-01", "description": "A", "amount": "100.00", "direction": "IN"},
        ]
        extracted = {
            "institution": "DBS",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "0.00",
            "closing_balance": "100.00",
            "transactions": txns,
        }
        balance_result = {"balance_valid": True, "difference": "0.00"}
        from src.services.validation import compute_confidence_score

        score = compute_confidence_score(extracted, balance_result)
        assert score == 85


class TestUnderExtractionPenalty:
    """AC13.15: Penalize implausibly-low transaction counts (issue #967)."""

    @staticmethod
    def _brokerage_extracted(transactions):
        return {
            "institution": "Futu",
            "period_start": "2025-06-01",
            "period_end": "2025-06-30",
            "opening_balance": "0.00",
            "closing_balance": "100.00",
            "currency": "HKD",
            "transactions": transactions,
        }

    def test_brokerage_single_txn_penalized(self):
        """AC13.15.1: A brokerage statement yielding a single transaction is an
        under-capture signal and must not present as high confidence."""
        extracted = self._brokerage_extracted(
            [
                {
                    "date": "2025-06-15",
                    "description": "Aggregate",
                    "amount": "100.00",
                    "direction": "IN",
                    "currency": "HKD",
                }
            ]
        )
        balance_result = {"balance_valid": True, "difference": "0.00"}

        unpenalized = compute_confidence_score(extracted, balance_result, is_brokerage=False)
        penalized = compute_confidence_score(extracted, balance_result, is_brokerage=True)

        assert penalized < unpenalized, "Under-capture should lower confidence vs the un-penalized score"
        assert penalized <= 60, f"1-txn brokerage should stay in review band, got {penalized}"

    def test_brokerage_sufficient_txns_not_penalized(self):
        """AC13.15.2: A brokerage statement with a plausible transaction count is
        not penalized."""
        txns = [
            {"date": "2025-06-10", "description": "Buy", "amount": "40.00", "direction": "OUT", "currency": "HKD"},
            {"date": "2025-06-20", "description": "Sell", "amount": "140.00", "direction": "IN", "currency": "HKD"},
        ]
        extracted = self._brokerage_extracted(txns)
        balance_result = {"balance_valid": True, "difference": "0.00"}

        score = compute_confidence_score(extracted, balance_result, is_brokerage=True)
        assert score > 60, f"Plausible brokerage parse should not be penalized, got {score}"

    def test_bank_single_txn_not_penalized(self):
        """AC13.15.3: A non-brokerage (bank) statement with one transaction keeps
        its existing score — a single-transaction bank month is legitimate."""
        extracted = {
            "institution": "DBS",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "0.00",
            "closing_balance": "100.00",
            "transactions": [
                {"date": "2025-01-01", "description": "A", "amount": "100.00", "direction": "IN"},
            ],
        }
        balance_result = {"balance_valid": True, "difference": "0.00"}

        assert compute_confidence_score(extracted, balance_result, is_brokerage=False) == 85

    def test_default_is_not_brokerage(self):
        """AC13.15.4: is_brokerage defaults to False so existing callers are
        unaffected."""
        extracted = self._brokerage_extracted(
            [
                {
                    "date": "2025-06-15",
                    "description": "Aggregate",
                    "amount": "100.00",
                    "direction": "IN",
                    "currency": "HKD",
                }
            ]
        )
        balance_result = {"balance_valid": True, "difference": "0.00"}

        assert compute_confidence_score(extracted, balance_result) == compute_confidence_score(
            extracted, balance_result, is_brokerage=False
        )

    def test_effective_count_uses_persisted_not_extracted(self):
        """AC13.15.5: the cap uses the persisted count, so a payload that extracts
        2 rows but persists only 1 (a row skipped) still trips the cap."""
        txns = [
            {"date": "2025-06-10", "description": "Buy", "amount": "40.00", "direction": "OUT", "currency": "HKD"},
            {"date": "2025-06-20", "description": "Sell", "amount": "140.00", "direction": "IN", "currency": "HKD"},
        ]
        extracted = self._brokerage_extracted(txns)
        balance_result = {"balance_valid": True, "difference": "0.00"}

        # Raw extracted count is 2 -> not capped; persisted count is 1 -> capped.
        not_capped = compute_confidence_score(extracted, balance_result, is_brokerage=True)
        capped = compute_confidence_score(extracted, balance_result, is_brokerage=True, effective_txn_count=1)
        assert capped <= 60 < not_capped


class TestBankPeriodResolution:
    """AC3.11: tolerant resolution of a bank statement's required period (#1449)."""

    def setup_method(self):
        self.service = ExtractionService()

    def test_AC3_11_1_period_start_falls_back_to_period_end(self):
        """AC3.11.1: a missing period_start falls back to period_end instead of hard-failing."""
        start, end = self.service._resolve_required_period({"period_end": "2025-03-31", "transactions": []})
        assert start == date(2025, 3, 31)
        assert end == date(2025, 3, 31)

    def test_AC3_11_2_period_derived_from_transaction_dates(self):
        """AC3.11.2: with no period bounds, the period spans the transaction-date range."""
        start, end = self.service._resolve_required_period(
            {
                "transactions": [
                    {"date": "2025-03-05", "amount": "1.00", "direction": "IN"},
                    {"date": "2025-03-28", "amount": "2.00", "direction": "OUT"},
                    {"date": "2025-03-12", "amount": "3.00", "direction": "IN"},
                ]
            }
        )
        assert start == date(2025, 3, 5)
        assert end == date(2025, 3, 28)

    def test_AC3_11_3_no_resolvable_date_still_raises(self):
        """AC3.11.3: a statement with no period and no transaction dates still rejects."""
        with pytest.raises(ValueError, match="Date is required"):
            self.service._resolve_required_period({"transactions": []})

    def test_AC3_11_2_missing_end_prefers_transaction_range_over_other_bound(self):
        """AC3.11.2: a present period_start with a missing period_end resolves the end to
        the last transaction date (a meaningful period), not back to period_start
        (which would collapse to a zero-length range)."""
        start, end = self.service._resolve_required_period(
            {
                "period_start": "2025-03-01",
                "transactions": [
                    {"date": "2025-03-10", "amount": "1.00", "direction": "IN"},
                    {"date": "2025-03-27", "amount": "2.00", "direction": "OUT"},
                ],
            }
        )
        assert start == date(2025, 3, 1)
        assert end == date(2025, 3, 27)
