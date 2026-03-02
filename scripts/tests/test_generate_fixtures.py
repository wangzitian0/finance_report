"""
Tests for scripts/generate_fixtures.py

Covers:
- get_cache_path(): cache file path generation
- parse_with_cache(): cached and uncached parsing paths
- process_extracted_data(): fixture format conversion with edge cases
- main(): end-to-end orchestration with mocked dependencies
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

# Ensure scripts/ is on path
SCRIPTS_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

# We need to mock the dotenv and backend imports before importing the module
# generate_fixtures.py does `from dotenv import load_dotenv` at module level
# and also inserts backend path. We can import it directly since dotenv is available.
import generate_fixtures


# ---------------------------------------------------------------------------
# get_cache_path
# ---------------------------------------------------------------------------


class TestGetCachePath:
    """Tests for get_cache_path function."""

    def test_returns_path_with_raw_suffix(self):
        """Given an input file, should return output path with _raw.json suffix."""
        file_path = Path("/input/statement.pdf")
        output_dir = Path("/output")
        result = generate_fixtures.get_cache_path(file_path, output_dir)
        assert result == Path("/output/statement_raw.json")

    def test_strips_original_extension(self):
        """Given a file with extension, should use stem (no extension) for cache name."""
        file_path = Path("/input/bank_2504.pdf")
        output_dir = Path("/tmp/output")
        result = generate_fixtures.get_cache_path(file_path, output_dir)
        assert result == Path("/tmp/output/bank_2504_raw.json")

    def test_uses_output_dir(self):
        """Given an output directory, should place cache file in that directory."""
        file_path = Path("/some/deep/path/file.csv")
        output_dir = Path("/cache")
        result = generate_fixtures.get_cache_path(file_path, output_dir)
        assert result.parent == Path("/cache")


# ---------------------------------------------------------------------------
# process_extracted_data
# ---------------------------------------------------------------------------


class TestProcessExtractedData:
    """Tests for process_extracted_data function."""

    def test_successful_extraction_with_transactions(self):
        """Given valid extracted data with transactions, should return success with events."""
        cache_data = {
            "file": "test.pdf",
            "institution": "DBS",
            "extracted": {
                "period_start": "2025-01-01",
                "period_end": "2025-01-31",
                "opening_balance": 1000.00,
                "closing_balance": 1500.00,
                "currency": "SGD",
                "transactions": [
                    {
                        "date": "2025-01-05",
                        "description": "Salary",
                        "amount": 500.00,
                        "direction": "IN",
                    },
                ],
            },
        }
        result = generate_fixtures.process_extracted_data(cache_data)

        assert result["success"] is True
        assert result["file"] == "test.pdf"
        assert result["institution"] == "DBS"
        assert result["statement"]["period_start"] == "2025-01-01"
        assert result["statement"]["period_end"] == "2025-01-31"
        assert result["statement"]["opening_balance"] == "1000.0"
        assert result["statement"]["closing_balance"] == "1500.0"
        assert result["statement"]["currency"] == "SGD"
        assert len(result["events"]) == 1
        assert result["events"][0]["date"] == "2025-01-05"
        assert result["events"][0]["description"] == "Salary"

    def test_extracted_data_is_list_with_items(self):
        """Given extracted data as a list (Gemini array response), should use first element."""
        cache_data = {
            "file": "test.pdf",
            "institution": "DBS",
            "extracted": [
                {
                    "period_start": "2025-01-01",
                    "period_end": "2025-01-31",
                    "opening_balance": 0,
                    "closing_balance": 0,
                    "transactions": [],
                },
            ],
        }
        result = generate_fixtures.process_extracted_data(cache_data)
        assert result["success"] is True

    def test_extracted_data_is_empty_list(self):
        """Given extracted data as an empty list, should return failure."""
        cache_data = {
            "file": "test.pdf",
            "institution": "DBS",
            "extracted": [],
        }
        result = generate_fixtures.process_extracted_data(cache_data)
        assert result["success"] is False
        assert result["error"] == "Empty array response"

    def test_extracted_data_has_error_key(self):
        """Given extracted data with an error key, should return failure with that error."""
        cache_data = {
            "file": "test.pdf",
            "institution": "DBS",
            "extracted": {"error": "Failed to parse JSON"},
        }
        result = generate_fixtures.process_extracted_data(cache_data)
        assert result["success"] is False
        assert result["error"] == "Failed to parse JSON"

    def test_missing_extracted_key_returns_failure(self):
        """Given cache_data with no 'extracted' key, should handle gracefully."""
        cache_data = {
            "file": "test.pdf",
            "institution": "DBS",
        }
        result = generate_fixtures.process_extracted_data(cache_data)
        # Empty dict -> no error key, no transactions, should still succeed
        assert result["success"] is True
        assert len(result["events"]) == 0

    def test_filters_out_invalid_dates(self):
        """Given transactions with None/UNKNOWN/empty dates, should filter them out."""
        cache_data = {
            "file": "test.pdf",
            "institution": "DBS",
            "extracted": {
                "period_start": "2025-01-01",
                "period_end": "2025-01-31",
                "transactions": [
                    {"date": "2025-01-05", "description": "Valid", "amount": 100},
                    {"date": "None", "description": "Invalid1", "amount": 50},
                    {"date": "UNKNOWN", "description": "Invalid2", "amount": 25},
                    {"date": "", "description": "Invalid3", "amount": 10},
                    {"date": None, "description": "Invalid4", "amount": 5},
                ],
            },
        }
        result = generate_fixtures.process_extracted_data(cache_data)
        assert result["success"] is True
        assert len(result["events"]) == 1
        assert result["events"][0]["description"] == "Valid"

    def test_defaults_for_missing_fields(self):
        """Given extracted data with missing optional fields, should use defaults."""
        cache_data = {
            "file": "test.pdf",
            "institution": "DBS",
            "extracted": {
                "transactions": [
                    {"date": "2025-01-01"},
                ],
            },
        }
        result = generate_fixtures.process_extracted_data(cache_data)
        assert result["success"] is True
        assert result["statement"]["currency"] == "SGD"
        assert result["statement"]["opening_balance"] == "0"
        assert result["statement"]["closing_balance"] == "0"
        assert result["events"][0]["description"] == ""
        assert result["events"][0]["amount"] == "0"
        assert result["events"][0]["direction"] == "OUT"

    def test_confidence_and_validation_fields(self):
        """Given valid extracted data, should set confidence_score and balance_validated."""
        cache_data = {
            "file": "test.pdf",
            "institution": "DBS",
            "extracted": {"transactions": []},
        }
        result = generate_fixtures.process_extracted_data(cache_data)
        assert result["statement"]["confidence_score"] == 100
        assert result["statement"]["balance_validated"] is True
        assert result["statement"]["validation_error"] is None


# ---------------------------------------------------------------------------
# parse_with_cache
# ---------------------------------------------------------------------------


class TestParseWithCache:
    """Tests for parse_with_cache async function."""

    @pytest.fixture
    def tmp_dirs(self, tmp_path):
        """Create temporary input/output directories."""
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        input_dir.mkdir()
        output_dir.mkdir()
        return input_dir, output_dir

    @pytest.mark.asyncio
    async def test_loads_from_cache_when_available(self, tmp_dirs):
        """Given a cached file exists and use_cache=True, should load from cache."""
        input_dir, output_dir = tmp_dirs
        file_path = input_dir / "test.pdf"
        file_path.write_bytes(b"fake pdf content")

        cache_data = {
            "file": "test.pdf",
            "institution": "DBS",
            "extracted": {"transactions": []},
        }
        cache_path = output_dir / "test_raw.json"
        cache_path.write_text(json.dumps(cache_data))

        result = await generate_fixtures.parse_with_cache(
            file_path, "DBS", output_dir, use_cache=True
        )
        assert result == cache_data

    @pytest.mark.asyncio
    async def test_skips_cache_when_disabled(self, tmp_dirs):
        """Given use_cache=False, should call API even if cache exists."""
        input_dir, output_dir = tmp_dirs
        file_path = input_dir / "test.pdf"
        file_path.write_bytes(b"fake pdf content")

        cache_path = output_dir / "test_raw.json"
        cache_path.write_text(json.dumps({"stale": True}))
        mock_service = MagicMock()
        mock_service.extract_financial_data = AsyncMock(
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"transactions": [], "period_start": "2025-01-01"}
                            )
                        }
                    }
                ]
            }
        )

        mock_extraction_module = MagicMock()
        mock_extraction_module.ExtractionService = lambda: mock_service
        modules_to_mock = {
            "src": MagicMock(),
            "src.services": MagicMock(),
            "src.services.extraction": mock_extraction_module,
        }
        with patch.dict("sys.modules", modules_to_mock):
            result = await generate_fixtures.parse_with_cache(
                file_path, "DBS", output_dir, use_cache=False
            )
        assert result["file"] == "test.pdf"
        assert result["institution"] == "DBS"

    @pytest.mark.asyncio
    async def test_handles_json_in_markdown_code_block(self, tmp_dirs):
        """Given API returns JSON wrapped in markdown code block, should extract it."""
        input_dir, output_dir = tmp_dirs
        file_path = input_dir / "test.pdf"
        file_path.write_bytes(b"fake pdf content")

        markdown_response = (
            '```json\n{"transactions": [], "period_start": "2025-01-01"}\n```'
        )

        mock_service = MagicMock()
        mock_service.extract_financial_data = AsyncMock(
            return_value={"choices": [{"message": {"content": markdown_response}}]}
        )

        with patch.dict(
            "sys.modules",
            {
                "src.services.extraction": MagicMock(
                    ExtractionService=lambda: mock_service
                )
            },
        ):
            result = await generate_fixtures.parse_with_cache(
                file_path, "DBS", output_dir, use_cache=False
            )

        assert result["extracted"]["period_start"] == "2025-01-01"

    @pytest.mark.asyncio
    async def test_handles_unparseable_response(self, tmp_dirs):
        """Given API returns non-JSON content, should return error dict."""
        input_dir, output_dir = tmp_dirs
        file_path = input_dir / "test.pdf"
        file_path.write_bytes(b"fake pdf content")

        mock_service = MagicMock()
        mock_service.extract_financial_data = AsyncMock(
            return_value={
                "choices": [{"message": {"content": "This is not JSON at all"}}]
            }
        )

        with patch.dict(
            "sys.modules",
            {
                "src.services.extraction": MagicMock(
                    ExtractionService=lambda: mock_service
                )
            },
        ):
            result = await generate_fixtures.parse_with_cache(
                file_path, "DBS", output_dir, use_cache=False
            )

        assert "error" in result["extracted"]
        assert result["extracted"]["error"] == "Failed to parse JSON"

    @pytest.mark.asyncio
    async def test_saves_to_cache_after_api_call(self, tmp_dirs):
        """Given a successful API call, should save result to cache file."""
        input_dir, output_dir = tmp_dirs
        file_path = input_dir / "test.pdf"
        file_path.write_bytes(b"fake pdf content")

        mock_service = MagicMock()
        mock_service.extract_financial_data = AsyncMock(
            return_value={
                "choices": [{"message": {"content": json.dumps({"transactions": []})}}]
            }
        )

        with patch.dict(
            "sys.modules",
            {
                "src.services.extraction": MagicMock(
                    ExtractionService=lambda: mock_service
                )
            },
        ):
            await generate_fixtures.parse_with_cache(
                file_path, "DBS", output_dir, use_cache=False
            )

        cache_path = output_dir / "test_raw.json"
        assert cache_path.exists()
        saved = json.loads(cache_path.read_text())
        assert saved["file"] == "test.pdf"
        assert saved["institution"] == "DBS"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    """Tests for main async function."""

    @pytest.mark.asyncio
    async def test_main_skips_missing_files(self, tmp_path, capsys, monkeypatch):
        """Given input files don't exist, should skip them with warning."""
        monkeypatch.setattr(generate_fixtures, "repo_root", tmp_path)
        monkeypatch.setattr("sys.argv", ["generate_fixtures.py"])

        # Create required directories
        (tmp_path / "tmp" / "input").mkdir(parents=True)
        (tmp_path / "tmp" / "output").mkdir(parents=True)
        (tmp_path / "apps" / "backend" / "tests" / "fixtures").mkdir(parents=True)

        await generate_fixtures.main()

        captured = capsys.readouterr()
        assert "Skipping" in captured.out

    @pytest.mark.asyncio
    async def test_main_processes_existing_files(self, tmp_path, monkeypatch):
        """Given input files exist, should process them and save fixtures."""
        monkeypatch.setattr(generate_fixtures, "repo_root", tmp_path)
        monkeypatch.setattr("sys.argv", ["generate_fixtures.py"])

        input_dir = tmp_path / "tmp" / "input"
        output_dir = tmp_path / "tmp" / "output"
        fixtures_dir = tmp_path / "apps" / "backend" / "tests" / "fixtures"
        input_dir.mkdir(parents=True)
        output_dir.mkdir(parents=True)
        fixtures_dir.mkdir(parents=True)

        # Create a test file matching the mapping
        test_file = input_dir / "2504.pdf"
        test_file.write_bytes(b"fake pdf")

        # Pre-populate cache so we don't need to call API
        cache_data = {
            "file": "2504.pdf",
            "institution": "DBS",
            "extracted": {
                "period_start": "2025-04-01",
                "period_end": "2025-04-30",
                "opening_balance": 1000,
                "closing_balance": 1500,
                "currency": "SGD",
                "transactions": [
                    {
                        "date": "2025-04-05",
                        "description": "Test",
                        "amount": 500,
                        "direction": "IN",
                    }
                ],
            },
        }
        cache_path = output_dir / "2504_raw.json"
        cache_path.write_text(json.dumps(cache_data))

        await generate_fixtures.main()

        # Check fixture was saved
        fixture_file = fixtures_dir / "2504_parsed.json"
        assert fixture_file.exists()
        fixture = json.loads(fixture_file.read_text())
        assert fixture["success"] is True
        assert len(fixture["events"]) == 1

        # Check summary was saved
        summary_file = fixtures_dir / "summary.json"
        assert summary_file.exists()

    @pytest.mark.asyncio
    async def test_main_handles_parse_exception(self, tmp_path, capsys, monkeypatch):
        """Given parsing raises exception, should capture error and continue."""
        monkeypatch.setattr(generate_fixtures, "repo_root", tmp_path)
        monkeypatch.setattr("sys.argv", ["generate_fixtures.py"])

        input_dir = tmp_path / "tmp" / "input"
        output_dir = tmp_path / "tmp" / "output"
        fixtures_dir = tmp_path / "apps" / "backend" / "tests" / "fixtures"
        input_dir.mkdir(parents=True)
        output_dir.mkdir(parents=True)
        fixtures_dir.mkdir(parents=True)

        test_file = input_dir / "2504.pdf"
        test_file.write_bytes(b"fake pdf")

        # Mock parse_with_cache to raise an exception
        async def raise_error(*args, **kwargs):
            raise RuntimeError("API connection failed")

        monkeypatch.setattr(generate_fixtures, "parse_with_cache", raise_error)

        await generate_fixtures.main()

        captured = capsys.readouterr()
        assert "RuntimeError" in captured.out or "❌" in captured.out

    @pytest.mark.asyncio
    async def test_main_no_cache_flag(self, tmp_path, monkeypatch):
        """Given --no-cache flag, should pass use_cache=False to parse_with_cache."""
        monkeypatch.setattr(generate_fixtures, "repo_root", tmp_path)
        monkeypatch.setattr("sys.argv", ["generate_fixtures.py", "--no-cache"])

        input_dir = tmp_path / "tmp" / "input"
        output_dir = tmp_path / "tmp" / "output"
        fixtures_dir = tmp_path / "apps" / "backend" / "tests" / "fixtures"
        input_dir.mkdir(parents=True)
        output_dir.mkdir(parents=True)
        fixtures_dir.mkdir(parents=True)

        test_file = input_dir / "2504.pdf"
        test_file.write_bytes(b"fake pdf")

        calls = []

        async def mock_parse(file_path, institution, output_dir, use_cache=True):
            calls.append({"use_cache": use_cache})
            return {
                "file": file_path.name,
                "institution": institution,
                "extracted": {"transactions": []},
            }

        monkeypatch.setattr(generate_fixtures, "parse_with_cache", mock_parse)

        await generate_fixtures.main()

        assert len(calls) > 0
        assert calls[0]["use_cache"] is False
