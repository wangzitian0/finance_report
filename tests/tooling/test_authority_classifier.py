"""Tests for the CODE/LLM authority classifier + counter (EPIC-026 AC26.9)."""

from __future__ import annotations

from pathlib import Path

from common.meta.extension.authority_classifier import (
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
    llm_file.write_text("from src.llm.extension.cassette import CassetteMode\n", encoding="utf-8")
    code_file = tmp_path / "test_y.py"
    code_file.write_text("def test_y():\n    assert 1 + 1 == 2\n", encoding="utf-8")
    index = {"test_x_replay.py": [llm_file], "test_y.py": [code_file]}
    cache: dict[Path, bool] = {}

    assert is_llm_test(llm_file, cache) is True
    assert is_llm_test(code_file, cache) is False
    assert classify_test_files(["reporting/test_x_replay.py"], index, cache) == "LLM"
    assert classify_test_files(["test_y.py"], index, cache) == "CODE"
    assert classify_test_files(["does_not_exist.py"], index, cache) == "unknown"
    # If any referenced test is an LLM test, the AC is LLM (worst-case wins).
    assert classify_test_files(["test_y.py", "test_x_replay.py"], index, cache) == "LLM"


def test_AC26_9_1_basename_collisions_disambiguate_or_stay_unknown(tmp_path: Path) -> None:
    """AC26.9.1: colliding basenames resolve by path suffix; bare-basename ties -> unknown."""
    # Sibling dirs so neither path is a suffix of the other (a true collision).
    a = tmp_path / "apps" / "test_dup.py"
    b = tmp_path / "web" / "test_dup.py"
    a.parent.mkdir(parents=True)
    b.parent.mkdir(parents=True)
    a.write_text("from src.llm.extension.cassette import CassetteMode\n", encoding="utf-8")  # LLM
    b.write_text("def test_dup():\n    assert True\n", encoding="utf-8")  # CODE
    index = {"test_dup.py": [a, b]}
    cache: dict[Path, bool] = {}

    # A directory-qualified token disambiguates to the right file.
    assert classify_test_files(["apps/test_dup.py"], index, cache) == "LLM"
    assert classify_test_files(["web/test_dup.py"], index, cache) == "CODE"
    # A bare colliding basename is ambiguous -> unknown, never a silent wrong pick.
    assert classify_test_files(["test_dup.py"], index, cache) == "unknown"


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
    # No LLM-row sanity assertion here: classify_repo only scans EPIC-doc AC
    # tables, not package roadmaps, and rows keep migrating out of EPIC docs
    # into package roadmaps (#1663 / #1715) — the real repo can legitimately
    # reach zero surviving LLM rows. That invariant is instead proven
    # deterministically against a synthetic repo below.


def test_AC26_9_1_counter_detects_llm_row_in_synthetic_repo(tmp_path: Path) -> None:
    """AC26.9.1: classify_repo detects a surviving LLM-classified AC row.

    Uses a synthetic tmp_path repo (not the live repo) so this stays true
    regardless of how far the live EPIC-doc-to-package-roadmap migration has
    progressed — see the comment on the real-repo test above.
    """
    epic_dir = tmp_path / "docs" / "project"
    epic_dir.mkdir(parents=True)
    (epic_dir / "EPIC-999.fake.md").write_text(
        "| AC999.1.1 | LLM test | tests/test_fake_llm.py |\n"
        "| AC999.1.2 | Code test | tests/test_fake_code.py |\n",
        encoding="utf-8",
    )
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_fake_llm.py").write_text(
        "from src.llm.extension.cassette import CassetteMode\n", encoding="utf-8"
    )
    (tests_dir / "test_fake_code.py").write_text(
        "def test_fake_code():\n    assert 1 + 1 == 2\n", encoding="utf-8"
    )

    result = classify_repo(root=tmp_path)

    assert result["overall"]["llm"] == 1
    assert result["overall"]["code"] == 1
    assert result["packages"]["EPIC-999"]["band"] == LLM_LED


def test_AC26_9_1_counter_renders_live_table(tmp_path: Path) -> None:
    """AC26.9.1: the runnable counter renders a live table and runs print-only.

    The committed snapshot was removed (it was ungated derived data); the live
    check_authority_reconcile gate is the enforced check, this counter is the
    on-demand human view.
    """
    from tools.authority_counter import main, render_table

    table = render_table(classify_repo())
    assert "band" in table and "ALL" in table
    assert main([]) == 0  # print-only mode
