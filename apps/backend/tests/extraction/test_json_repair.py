"""AC13.14: JSON-repair retry for recoverable malformed model responses (#982).

A single model response wrapped in markdown fences or padded with prose should
not reject an otherwise-valid upload. The extraction loop attempts a bounded,
deterministic repair before counting the response as a ``json_parse`` failure.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.extraction import ExtractionError, ExtractionService


class TestRepairJsonObject:
    def test_strips_json_code_fence(self):
        """AC13.14.1: A ```json fenced object is recovered."""
        content = '```json\n{"institution": "DBS", "transactions": []}\n```'
        repaired = ExtractionService._repair_json_object(content)
        assert repaired is not None
        assert json.loads(repaired) == {"institution": "DBS", "transactions": []}

    def test_strips_bare_code_fence_and_prose(self):
        """AC13.14.2: Surrounding prose and a bare ``` fence are stripped to the
        outermost balanced object."""
        content = 'Here is the result:\n```\n{"a": 1, "nested": {"b": 2}}\n```\nDone.'
        repaired = ExtractionService._repair_json_object(content)
        assert repaired is not None
        assert json.loads(repaired) == {"a": 1, "nested": {"b": 2}}

    def test_strips_single_line_fence(self):
        """AC13.14.1b: A single-line fenced block (no newline) is recovered."""
        content = '```json {"institution": "DBS", "transactions": []}```'
        repaired = ExtractionService._repair_json_object(content)
        assert repaired is not None
        assert json.loads(repaired) == {"institution": "DBS", "transactions": []}

    def test_clean_object_is_preserved(self):
        """AC13.14.3: An already-clean object round-trips unchanged."""
        content = '{"x": "y"}'
        repaired = ExtractionService._repair_json_object(content)
        assert repaired is not None
        assert json.loads(repaired) == {"x": "y"}

    def test_unrecoverable_returns_none(self):
        """AC13.14.4: Content with no JSON object is unrecoverable."""
        assert ExtractionService._repair_json_object("totally not json") is None
        assert ExtractionService._repair_json_object("") is None

    def test_does_not_misread_braces_in_strings(self):
        """AC13.14.4b: Braces inside string values do not truncate the object."""
        content = '```json\n{"note": "balance {pending}", "ok": true}\n```'
        repaired = ExtractionService._repair_json_object(content)
        assert repaired is not None
        assert json.loads(repaired) == {"note": "balance {pending}", "ok": True}

    def test_unbalanced_open_brace_returns_none(self):
        """AC13.14.4c: An opening brace with no matching close (truncated response)
        is unrecoverable rather than returning a partial object."""
        assert ExtractionService._repair_json_object('{"a": 1, "b": 2') is None
        # A brace inside a string must not count as the close that balances it.
        assert ExtractionService._repair_json_object('{"note": "a } b"') is None

    def test_escaped_quote_in_string_does_not_end_object_early(self):
        """AC13.14.4d: A backslash-escaped quote inside a string value does not end
        the string early, so the full object is recovered."""
        content = '{"path": "C:\\\\Users\\\\x", "quote": "she said \\"hi\\"", "ok": true}'
        repaired = ExtractionService._repair_json_object(content)
        assert repaired is not None
        assert json.loads(repaired) == {"path": "C:\\Users\\x", "quote": 'she said "hi"', "ok": True}

    def test_prefers_largest_object_when_example_precedes_real(self):
        """AC13.14.7: when a small example object precedes the real (larger)
        extraction, the real one is recovered — not the leading example."""
        content = (
            'Here is the format I will use: {"institution": "Example", "transactions": []}\n'
            "Now the actual data:\n"
            '{"institution": "DBS", "opening_balance": "1000.00", "closing_balance": "1100.00", '
            '"transactions": [{"amount": "100.00", "direction": "IN"}]}'
        )
        repaired = ExtractionService._repair_json_object(content)
        assert repaired is not None
        obj = json.loads(repaired)
        assert obj["institution"] == "DBS"
        assert obj["transactions"] == [{"amount": "100.00", "direction": "IN"}]

    def test_complete_object_then_trailing_unbalanced_brace(self):
        """AC13.14.8: a complete object followed by trailing junk that opens an
        unbalanced brace still recovers the complete object."""
        content = '{"institution": "DBS", "transactions": []}\nnote: {oops'
        repaired = ExtractionService._repair_json_object(content)
        assert repaired is not None
        assert json.loads(repaired) == {"institution": "DBS", "transactions": []}

    def test_leading_unbalanced_brace_then_real_object(self):
        """AC13.14.9: a leading unmatched brace (junk) before the real object does
        not stop the scan — the real object is still recovered."""
        content = 'note: {oops\n{"institution": "DBS", "transactions": []}'
        repaired = ExtractionService._repair_json_object(content)
        assert repaired is not None
        assert json.loads(repaired) == {"institution": "DBS", "transactions": []}


class TestExtractionSalvagesFencedResponse:
    async def test_fenced_response_is_salvaged(self):
        """AC13.14.5: A fenced (otherwise-valid) model response is salvaged by the
        extraction loop instead of rejecting the upload."""
        service = ExtractionService()
        fenced = '```json\n{"institution": "DBS", "transactions": []}\n```'

        with (
            patch.object(service, "api_key", "test-key"),
            patch.object(service, "base_url", "https://test.api"),
            patch("src.services.extraction.stream_ai_json", return_value=MagicMock()),
            patch("src.services.extraction.accumulate_stream", AsyncMock(return_value=fenced)),
        ):
            result = await service._extract_json_with_models(
                messages=[{"role": "user", "content": "x"}],
                models=["test-model"],
                prompt="p",
                institution="DBS",
                file_type="pdf",
                return_raw=False,
                has_content=True,
                has_url=False,
            )

        assert result == {"institution": "DBS", "transactions": []}

    async def test_unrecoverable_response_still_fails(self):
        """AC13.14.6: A response with no recoverable JSON still fails as before."""
        service = ExtractionService()

        with (
            patch.object(service, "api_key", "test-key"),
            patch.object(service, "base_url", "https://test.api"),
            patch("src.services.extraction.stream_ai_json", return_value=MagicMock()),
            patch("src.services.extraction.accumulate_stream", AsyncMock(return_value="not json at all")),
        ):
            with pytest.raises(ExtractionError):
                await service._extract_json_with_models(
                    messages=[{"role": "user", "content": "x"}],
                    models=["test-model"],
                    prompt="p",
                    institution="DBS",
                    file_type="pdf",
                    return_raw=False,
                    has_content=True,
                    has_url=False,
                )
