"""Tests for the tools/reverify_real_corpus.py CLI wrapper (AC-llm.14.4, #1744 item c).

common/testing/reverify_real_corpus.py's own tests (test_reverify_real_corpus.py)
cover the domain-agnostic comparison/orchestration logic via an injected fake
live_extractor; these cover the CONCRETE extractor + entrypoint this wrapper
owns (kept out of common/testing to respect the infra/domain package boundary
— see the module docstring), which that DI seam deliberately never exercises.
"""

from __future__ import annotations

from pathlib import Path

from tools.reverify_real_corpus import _live_extractor, main


def test_live_extractor_returns_none_when_no_api_key(
    monkeypatch, tmp_path: Path
) -> None:
    from src.config import settings

    monkeypatch.setattr(settings, "ai_api_key", "", raising=False)
    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")

    assert _live_extractor(pdf_path) is None


def test_live_extractor_returns_extraction_result_on_success(
    monkeypatch, tmp_path: Path
) -> None:
    from src.extraction.extension.service import ExtractionService

    monkeypatch.setattr(
        "src.config.settings.ai_api_key", "sk-test-dummy", raising=False
    )

    captured: dict = {}

    async def _fake_extract(self, *, file_content, institution, file_type, filename):
        captured["file_content"] = file_content
        captured["institution"] = institution
        captured["file_type"] = file_type
        captured["filename"] = filename
        return {
            "opening_balance": "100.00",
            "closing_balance": "130.00",
            "transactions": [],
        }

    monkeypatch.setattr(ExtractionService, "extract_financial_data", _fake_extract)

    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")

    result = _live_extractor(pdf_path)

    assert result == {
        "opening_balance": "100.00",
        "closing_balance": "130.00",
        "transactions": [],
    }
    assert captured["file_content"] == b"%PDF-fake"
    assert captured["institution"] is None
    assert captured["file_type"] == "pdf"
    assert captured["filename"] == "statement.pdf"


def test_live_extractor_returns_none_on_extraction_error(
    monkeypatch, tmp_path: Path
) -> None:
    from src.extraction.extension.service import ExtractionError, ExtractionService

    monkeypatch.setattr(
        "src.config.settings.ai_api_key", "sk-test-dummy", raising=False
    )

    async def _fake_extract(self, **_kwargs):
        raise ExtractionError("provider rejected the request")

    monkeypatch.setattr(ExtractionService, "extract_financial_data", _fake_extract)

    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")

    assert _live_extractor(pdf_path) is None


def test_main_delegates_argv_and_this_modules_live_extractor(monkeypatch) -> None:
    """main() must forward argv verbatim and pass ITS OWN _live_extractor through
    — not some other callable — so the CLI actually performs a real extraction."""
    captured: dict = {}

    def _fake_reverify_main(argv, *, live_extractor):
        captured["argv"] = argv
        captured["live_extractor"] = live_extractor
        return 0

    monkeypatch.setattr(
        "tools.reverify_real_corpus._reverify_main", _fake_reverify_main
    )

    rc = main(["--case-id", "abc123", "--pdf", "/tmp/statement.pdf"])

    assert rc == 0
    assert captured["argv"] == ["--case-id", "abc123", "--pdf", "/tmp/statement.pdf"]
    assert captured["live_extractor"] is _live_extractor
