"""Tests for the CODE/LLM authority classifier + counter (EPIC-026 AC26.9)."""

from __future__ import annotations

from pathlib import Path

from common.ssot.authority_classifier import (
    CODE_LED,
    CODE_ONLY,
    LLM_LED,
    LLM_ONLY,
    band,
    classify_repo,
    classify_test_files,
    is_llm_test,
)


def test_AC26_9_1_band_boundaries() -> None:
    """AC26.9.1: LLM-share maps to the four bands at 0 / 50 / 100 boundaries."""
    assert band(0) == CODE_ONLY
    assert band(0.1) == CODE_LED
    assert band(49.9) == CODE_LED
    assert band(50) == LLM_LED
    assert band(99.9) == LLM_LED
    assert band(100) == LLM_ONLY


def test_AC26_9_1_test_shape_classifies_code_vs_llm(tmp_path: Path) -> None:
    """AC26.9.1: a cassette/replay test is LLM; a structured test is CODE; missing is unknown."""
    llm_file = tmp_path / "test_x_replay.py"
    llm_file.write_text("from src.llm.cassette import CassetteMode\n", encoding="utf-8")
    code_file = tmp_path / "test_y.py"
    code_file.write_text("def test_y():\n    assert 1 + 1 == 2\n", encoding="utf-8")
    index = {"test_x_replay.py": llm_file, "test_y.py": code_file}
    cache: dict[Path, bool] = {}

    assert is_llm_test(llm_file, cache) is True
    assert is_llm_test(code_file, cache) is False
    assert classify_test_files(["reporting/test_x_replay.py"], index, cache) == "LLM"
    assert classify_test_files(["test_y.py"], index, cache) == "CODE"
    assert classify_test_files(["does_not_exist.py"], index, cache) == "unknown"
    # If any referenced test is an LLM test, the AC is LLM (worst-case wins).
    assert classify_test_files(["test_y.py", "test_x_replay.py"], index, cache) == "LLM"


def test_AC26_9_1_counter_runs_over_repo_and_is_well_formed() -> None:
    """AC26.9.1: the counter classifies the real repo into valid per-package bands."""
    result = classify_repo()
    overall = result["overall"]
    assert overall["total"] > 0
    assert overall["total"] == overall["code"] + overall["llm"] + overall["unknown"]
    assert overall["band"] in {CODE_ONLY, CODE_LED, LLM_LED, LLM_ONLY}
    for epic, bucket in result["packages"].items():
        assert epic.startswith("EPIC-")
        assert bucket["total"] == bucket["code"] + bucket["llm"] + bucket["unknown"]
        assert bucket["band"] in {CODE_ONLY, CODE_LED, LLM_LED, LLM_ONLY}
        # llm_share is computed over KNOWN (code+llm), so 0..100.
        assert 0 <= bucket["llm_share"] <= 100
    # Sanity: the AI-heavy extraction/provider EPICs are detected as carrying LLM ACs.
    assert result["packages"].get("EPIC-006", {}).get("llm", 0) > 0
