"""Real-corpus re-verification against live extraction (#1744 item c).

compare_scores/reverify_case are pure/DI-seamed: no live provider or real PDF
needed to test the comparison logic itself — that's the point (#1744 found
that verifying this loop even works had zero coverage anywhere).
"""

from __future__ import annotations

import json
from pathlib import Path

from common.testing.reverify_real_corpus import (
    ReverifyResult,
    compare_scores,
    render_report,
    reverify_case,
)

_TRUTH = {
    "opening_balance": "100.00",
    "closing_balance": "130.00",
    "transactions": [
        {"date": "2026-01-02", "description": "Coffee shop", "amount": "-5.00"},
        {"date": "2026-01-05", "description": "Salary credit", "amount": "50.00"},
    ],
}


def _perfect() -> dict:
    return json.loads(json.dumps(_TRUTH))


# --------------------------------------------------------------------------- #
# compare_scores — pure comparison logic
# --------------------------------------------------------------------------- #
def test_compare_scores_no_change_when_fresh_matches_committed() -> None:
    result = compare_scores(
        "case-1", old_extracted=_perfect(), new_extracted=_perfect(), truth=_TRUTH
    )
    assert result.verdict == "no_change"
    assert result.old_score == result.new_score == 1.0


def test_compare_scores_flags_a_real_regression() -> None:
    old = _perfect()
    new = _perfect()
    new["transactions"][0]["amount"] = "-500.00"  # a field now wrong
    result = compare_scores(
        "case-1", old_extracted=old, new_extracted=new, truth=_TRUTH
    )
    assert result.verdict == "regressed"
    assert result.new_score < result.old_score


def test_compare_scores_flags_an_improvement() -> None:
    old = _perfect()
    old["transactions"][0]["amount"] = "-500.00"  # committed floor is currently wrong
    new = _perfect()
    result = compare_scores(
        "case-1", old_extracted=old, new_extracted=new, truth=_TRUTH
    )
    assert result.verdict == "improved"
    assert result.new_score > result.old_score


def test_compare_scores_recording_failed_is_distinct_from_regression() -> None:
    """A None new_extracted (no key, empty reply) must not read as a score of 0
    — that would look identical to a real regression and mislead an operator."""
    result = compare_scores(
        "case-1", old_extracted=_perfect(), new_extracted=None, truth=_TRUTH
    )
    assert result.verdict == "recording_failed"
    assert result.new_score is None


def test_compare_scores_epsilon_absorbs_float_jitter() -> None:
    old = _perfect()
    new = _perfect()
    result = compare_scores(
        "case-1", old_extracted=old, new_extracted=new, truth=_TRUTH, epsilon=1e-6
    )
    assert result.verdict == "no_change"


# --------------------------------------------------------------------------- #
# reverify_case — orchestration (reads real files, DI-seamed live call)
# --------------------------------------------------------------------------- #
def _write_case_files(
    tmp_path: Path, case_id: str, *, extracted: dict, truth: dict
) -> None:
    cassette_dir = tmp_path / "cassettes"
    ground_truth_dir = cassette_dir / "ground_truth"
    ground_truth_dir.mkdir(parents=True)
    (cassette_dir / f"{case_id}.json").write_text(
        json.dumps(
            {
                "fingerprint": case_id,
                "role": "vision",
                "tag": "flow-only",
                "request": {},
                "response": {"stream_text": json.dumps(extracted)},
            }
        ),
        encoding="utf-8",
    )
    (ground_truth_dir / f"{case_id}.truth.json").write_text(
        json.dumps(
            {
                "synthetic": True,
                "modality": "vision",
                "institution_class": "bank",
                "edge_condition": "happy_path",
                "source": "test",
                "balance_reconciles": True,
                "expected": truth,
            }
        ),
        encoding="utf-8",
    )


def test_reverify_case_reads_committed_cassette_and_calls_live_extractor(
    tmp_path: Path,
) -> None:
    _write_case_files(tmp_path, "case-1", extracted=_perfect(), truth=_TRUTH)
    calls: list[Path] = []

    def fake_live(pdf_path: Path) -> dict:
        calls.append(pdf_path)
        return _perfect()

    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")
    result = reverify_case(
        "case-1",
        pdf_path,
        fake_live,
        cassette_dir=tmp_path / "cassettes",
        ground_truth_dir=tmp_path / "cassettes" / "ground_truth",
    )
    assert calls == [pdf_path]
    assert result.verdict == "no_change"


def test_reverify_case_never_mutates_the_committed_cassette(tmp_path: Path) -> None:
    """AC-llm.14.4: the whole point — this is read-only comparison, never a write."""
    _write_case_files(tmp_path, "case-1", extracted=_perfect(), truth=_TRUTH)
    cassette_path = tmp_path / "cassettes" / "case-1.json"
    before = cassette_path.read_text(encoding="utf-8")

    def fake_live(pdf_path: Path) -> dict:
        regressed = _perfect()
        regressed["closing_balance"] = "0.00"
        return regressed

    pdf_path = tmp_path / "statement.pdf"
    pdf_path.write_bytes(b"%PDF-fake")
    result = reverify_case(
        "case-1",
        pdf_path,
        fake_live,
        cassette_dir=tmp_path / "cassettes",
        ground_truth_dir=tmp_path / "cassettes" / "ground_truth",
    )
    assert result.verdict == "regressed"
    assert cassette_path.read_text(encoding="utf-8") == before


def test_reverify_case_missing_cassette_raises_not_a_silent_pass(
    tmp_path: Path,
) -> None:
    import pytest

    with pytest.raises(FileNotFoundError):
        reverify_case(
            "nope",
            tmp_path / "statement.pdf",
            lambda _pdf: _perfect(),
            cassette_dir=tmp_path / "cassettes",
            ground_truth_dir=tmp_path / "cassettes" / "ground_truth",
        )


# --------------------------------------------------------------------------- #
# render_report
# --------------------------------------------------------------------------- #
def test_render_report_includes_every_result_and_flags_non_no_change() -> None:
    results = [
        ReverifyResult("a", 1.0, 1.0, "no_change", "matches"),
        ReverifyResult("b", 1.0, 0.5, "regressed", "regressed detail text"),
    ]
    report = render_report(results)
    for result in results:
        assert result.case_id in report
    detail_text = results[1].detail
    assert detail_text in report
