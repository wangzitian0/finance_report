"""A failed check goes back to the model as feedback, and the model reads the document again (#2964)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import fitz

from src.config import settings
from src.extraction.base.findings import FindingCode, check_feedback_block, reading_findings
from src.extraction.extension.service import ExtractionService

PRINTED = "10.00 20.00 30.00 40.00 50.00"
FEEDBACK_HEADER = "Check results of your previous answer"


def _pdf(text: str) -> bytes:
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _rows(*amounts: str) -> list[dict]:
    return [
        {"date": f"2025-01-{day:02d}", "amount": amount, "direction": "OUT", "currency": "SGD"}
        for day, amount in enumerate(amounts, start=10)
    ]


def _reading(*amounts: str, **fields) -> dict:
    base = {
        "institution": "DBS",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "currency": "SGD",
        "opening_balance": None,
        "closing_balance": None,
        "transactions": _rows(*amounts),
    }
    return {**base, **fields}


async def _run(readings: list, *, content: bytes, max_attempts: int, institution: str | None = None):
    service, mock = ExtractionService(), AsyncMock(side_effect=readings)
    with (
        patch.object(settings, "ai_extract_max_attempts", max_attempts),
        patch.object(service, "extract_financial_data", mock),
    ):
        slices, _ = await service._extract_with_balance_retry(
            file_content=content,
            institution=institution,
            file_type="pdf",
            file_url=None,
            force_model=None,
            filename="s.pdf",
        )
    return slices[0].payload, mock


def test_reading_findings_name_each_failed_check_with_its_values():
    reading = _reading(
        "10.00",
        "20.00",
        "30.00",
        "40.00",
        "999.99",
        institution=None,
        opening_balance="77.77",
        closing_balance="50.00",
    )
    findings = reading_findings(reading, source_text=PRINTED)
    by_code = {finding.code: finding for finding in findings}

    assert set(by_code) == {
        FindingCode.MISSING_FACT,
        FindingCode.BALANCE_MISMATCH,
        FindingCode.OPENING_NOT_IN_TEXT,
        FindingCode.ROWS_NOT_IN_TEXT,
    }
    assert "institution" in by_code[FindingCode.MISSING_FACT].feedback
    assert "77.77" in by_code[FindingCode.OPENING_NOT_IN_TEXT].feedback
    assert by_code[FindingCode.ROWS_NOT_IN_TEXT].rows == (5,)
    assert "row 5 (2025-01-14, 999.99)" in by_code[FindingCode.ROWS_NOT_IN_TEXT].feedback
    # 77.77 - 1099.99 = -1022.22, and the document prints 50.00.
    assert "-1022.22" in by_code[FindingCode.BALANCE_MISMATCH].feedback
    assert "1072.22" in by_code[FindingCode.BALANCE_MISMATCH].feedback


def test_reading_findings_are_empty_for_a_reading_that_passes_and_the_block_is_empty():
    reading = _reading("10.00", "20.00", "30.00", "40.00", "50.00")
    assert reading_findings(reading, source_text=PRINTED) == []
    assert check_feedback_block([]) == ""
    # An institution that the caller supplies is not a missing fact of the reading.
    assert reading_findings({**reading, "institution": None}, source_text=PRINTED, institution_given=True) == []


def test_a_row_without_a_date_or_a_number_is_a_finding():
    reading = _reading("10.00", "20.00")
    reading["transactions"][0]["amount"] = "not-a-number"
    reading["transactions"][1]["date"] = None
    (finding,) = reading_findings(reading, source_text=None)
    assert finding.code is FindingCode.ROW_INVALID and finding.rows == (1, 2)


async def test_a_row_that_the_text_does_not_print_starts_a_second_pass_with_the_finding():
    wrong = _reading("10.00", "20.00", "30.00", "40.00", "999.99")
    right = _reading("10.00", "20.00", "30.00", "40.00", "50.00")

    result, mock = await _run([wrong, right], content=_pdf(PRINTED), max_attempts=2)

    first, second = mock.await_args_list
    assert result is right
    assert first.kwargs["feedback"] == ""
    assert FEEDBACK_HEADER in second.kwargs["feedback"]
    assert "row 5 (2025-01-14, 999.99)" in second.kwargs["feedback"]
    # The finding is about the text, so the second pass reads the text again.
    assert second.kwargs["read_text_layer"] is True


async def test_a_reading_without_findings_ends_after_one_pass():
    right = _reading("10.00", "20.00", "30.00", "40.00", "50.00")
    result, mock = await _run([right], content=_pdf(PRINTED), max_attempts=3)
    assert result is right and mock.await_count == 1


async def test_a_missing_institution_starts_a_second_pass_unless_the_caller_gave_one():
    without = _reading("10.00", "20.00", "30.00", "40.00", "50.00", institution=None)
    with_name = _reading("10.00", "20.00", "30.00", "40.00", "50.00")

    result, mock = await _run([without, with_name], content=_pdf(PRINTED), max_attempts=2)
    assert result is with_name and "institution" in mock.await_args_list[1].kwargs["feedback"]

    given, mock_given = await _run([without], content=_pdf(PRINTED), max_attempts=2, institution="DBS")
    assert given is without and mock_given.await_count == 1


async def test_a_balance_gap_that_stays_reads_the_text_again_and_then_the_page_images():
    gap = _reading("10.00", "20.00", "30.00", "40.00", "50.00", opening_balance="200.00", closing_balance="40.00")

    result, mock = await _run([gap, dict(gap), dict(gap)], content=_pdf(PRINTED + " 200.00"), max_attempts=3)

    assert [call.kwargs["read_text_layer"] for call in mock.await_args_list] == [True, True, False]
    assert all(FEEDBACK_HEADER in call.kwargs["feedback"] for call in mock.await_args_list[1:])
    # No later pass had fewer findings, so the first pass stays.
    assert result is gap


async def test_the_pass_with_fewer_findings_wins():
    two = _reading("10.00", "20.00", "30.00", "40.00", "999.99", institution=None)
    one = _reading("10.00", "20.00", "30.00", "40.00", "999.99")

    kept_later, _ = await _run([two, one], content=_pdf(PRINTED), max_attempts=2)
    kept_first, _ = await _run([one, two], content=_pdf(PRINTED), max_attempts=2)

    assert kept_later is one and kept_first is one


async def test_feedback_is_part_of_the_prompt_and_an_empty_feedback_changes_no_byte():
    reply = {"institution": "DBS", "transactions": [{"amount": "50.00"}]}

    async def prompt_text(**kwargs) -> str:
        service = ExtractionService()
        service.api_key, service.multimodal_model = "test-key", "test-model"
        call = AsyncMock(return_value=reply)
        with patch.object(service, "_extract_json_with_model", call):
            await service.extract_financial_data(
                file_content=_pdf(PRINTED), institution="DBS", file_type="pdf", **kwargs
            )
        return call.await_args_list[0].kwargs["messages"][0]["content"][0]["text"]

    block = check_feedback_block(
        reading_findings(_reading("999.99", "10.00", "20.00", "30.00", "40.00"), source_text=PRINTED)
    )
    plain = await prompt_text()
    assert await prompt_text(feedback="") == plain
    with_feedback = await prompt_text(feedback=block)
    assert with_feedback == plain + block and "row 1 (2025-01-10, 999.99)" in block


async def test_an_opening_balance_that_the_document_does_not_print_is_dropped_by_the_second_pass():
    """#3112: the model computed an opening balance. The second pass returns null, and that pass wins."""
    computed = _reading("10.00", "20.00", "30.00", "40.00", "50.00", opening_balance="200.00", closing_balance="50.00")
    printed_only = {**computed, "opening_balance": None}

    result, mock = await _run([computed, printed_only], content=_pdf(PRINTED), max_attempts=2)

    assert result is printed_only
    assert (
        "The opening balance 200.00 is not a number that the document prints"
        in mock.await_args_list[1].kwargs["feedback"]
    )
