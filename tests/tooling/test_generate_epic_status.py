"""AC14.1.22: README EPIC status is generated from registries + test reports.

These tests pin the behavior required by issue #455: EPIC status/completion is
*derived* from canonical sources (not hand-written), reports the four debt
categories separately, omits mutable live CI/deploy run status, and is guarded
by a generate-with-``--check`` drift gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from common.testing import generate_epic_status as ges
from common.testing.analyze_test_ac_coverage import ACRecord, AnalysisResult


def _result_with(registry: dict[str, ACRecord], **buckets: set[str]) -> AnalysisResult:
    """Build a minimal AnalysisResult for rendering tests."""
    return AnalysisResult(
        registry=registry,
        references={},
        source_file_counts={},
        source_real_ref_counts={},
        source_placeholder_ref_counts={},
        source_stub_ref_counts={},
        covered_ids=buckets.get("covered", set()),
        placeholder_only_ids=buckets.get("placeholder_only", set()),
        stub_only_ids=buckets.get("stub_only", set()),
        untested_ids=sorted(buckets.get("untested", set())),
        invalid_real_refs={},
        invalid_placeholder_refs={},
        invalid_stub_refs={},
        deprecated_ids=buckets.get("deprecated", set()),
    )


def _registry() -> dict[str, ACRecord]:
    return {
        "AC1.1.1": ACRecord("AC1.1.1", 1, "phase0-setup", "covered ac"),
        "AC1.1.2": ACRecord("AC1.1.2", 1, "phase0-setup", "placeholder ac"),
        "AC1.1.3": ACRecord("AC1.1.3", 1, "phase0-setup", "stub ac"),
        "AC1.1.4": ACRecord("AC1.1.4", 1, "phase0-setup", "manual-gate ac"),
        "AC1.1.5": ACRecord("AC1.1.5", 1, "phase0-setup", "blocker ac"),
        "AC1.1.6": ACRecord(
            "AC1.1.6", 1, "phase0-setup", "~~deprecated~~", deprecated=True
        ),
    }


def test_AC14_1_22_completions_split_four_categories_separately() -> None:
    """AC14.1.22: completion is split into four separately reported buckets."""
    registry = _registry()
    result = _result_with(
        registry,
        covered={"AC1.1.1"},
        placeholder_only={"AC1.1.2"},
        stub_only={"AC1.1.3"},
        untested={"AC1.1.2", "AC1.1.3", "AC1.1.4", "AC1.1.5"},
        deprecated={"AC1.1.6"},
    )

    completions = ges.build_completions(result, manual_gate_ids={"AC1.1.4"})

    assert len(completions) == 1
    epic = completions[0]
    assert epic.active == 5
    assert epic.automated_covered == 1
    assert epic.placeholder_stub_debt == 2  # placeholder + stub, counted apart
    assert epic.manual_gate_debt == 1
    assert epic.blockers == 1
    assert epic.deprecated == 1
    # The four debt/proof categories must sum to active (MECE over active ACs).
    assert (
        epic.automated_covered
        + epic.placeholder_stub_debt
        + epic.manual_gate_debt
        + epic.blockers
        == epic.active
    )


def test_AC14_1_22_render_block_has_separate_columns_and_no_live_run_status() -> None:
    """AC14.1.22: rendered block names the four categories and omits live status."""
    registry = _registry()
    result = _result_with(
        registry,
        covered={"AC1.1.1"},
        placeholder_only={"AC1.1.2"},
        stub_only={"AC1.1.3"},
        deprecated={"AC1.1.6"},
    )
    completions = ges.build_completions(result, manual_gate_ids={"AC1.1.4"})

    block = ges.render_block(completions, coverage_percent=97.3)

    assert ges.BEGIN_MARKER in block and ges.END_MARKER in block
    assert "Automated covered" in block
    assert "Placeholder/stub debt" in block
    assert "Manual-gate debt" in block
    assert "Blockers" in block
    # Does not duplicate mutable live CI/deploy run status in static docs.
    assert "Live CI and deploy run status are intentionally omitted" in block
    assert "97.3%" in block


def test_AC14_1_22_render_block_tolerates_absent_unified_coverage() -> None:
    """AC14.1.22: a missing unified-coverage.json renders gracefully, not crash."""
    completions = ges.build_completions(
        _result_with(_registry(), covered={"AC1.1.1"}), manual_gate_ids=set()
    )
    block = ges.render_block(completions, coverage_percent=None)
    assert "unified-coverage.json absent" in block


def test_AC14_1_22_load_unified_coverage_read_if_present(tmp_path: Path) -> None:
    """AC14.1.22: unified coverage is consumed when present, tolerated when not."""
    assert ges.load_unified_coverage(tmp_path / "missing.json") is None

    good = tmp_path / "unified-coverage.json"
    good.write_text('{"coverage_percent": 97.33}', encoding="utf-8")
    assert ges.load_unified_coverage(good) == pytest.approx(97.33)

    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert ges.load_unified_coverage(bad) is None


def test_AC14_1_22_splice_requires_markers() -> None:
    """AC14.1.22: splicing fails closed when the generated markers are absent."""
    with pytest.raises(ValueError):
        ges.splice_block("no markers here", "BLOCK")

    document = f"before\n{ges.BEGIN_MARKER}\nold\n{ges.END_MARKER}\nafter\n"
    new_block = f"{ges.BEGIN_MARKER}\nnew\n{ges.END_MARKER}"
    spliced = ges.splice_block(document, new_block)
    assert "old" not in spliced
    assert "new" in spliced
    assert spliced.startswith("before\n")
    assert spliced.endswith("after\n")


def test_AC14_1_22_check_passes_when_block_current(tmp_path: Path) -> None:
    """AC14.1.22: --check passes when the committed README holds the stable pointer.

    The EPIC-status numbers are a derived (not committed) view, so --check now
    compares the STABLE pointer block, never the live numbers.
    """
    pointer = ges.render_pointer_block()
    doc = tmp_path / "README.md"
    doc.write_text(f"intro\n{pointer}\noutro\n", encoding="utf-8")

    assert ges.main(["--output", str(doc), "--check"]) == 0


def test_AC14_1_22_check_fails_on_drift(tmp_path: Path, capsys) -> None:
    """AC-meta.generated-refs.3: --check fails when the committed pointer block is malformed/stale."""
    doc = tmp_path / "README.md"
    doc.write_text(
        f"intro\n{ges.BEGIN_MARKER}\nSTALE numbers\n{ges.END_MARKER}\noutro\n",
        encoding="utf-8",
    )

    assert ges.main(["--output", str(doc), "--check"]) == 1
    assert "pointer block" in capsys.readouterr().err.lower()


def test_AC14_1_22_check_fails_when_markers_missing(tmp_path: Path, capsys) -> None:
    """AC14.1.22: --check fails when the document has no generated block."""
    doc = tmp_path / "README.md"
    doc.write_text("no markers\n", encoding="utf-8")

    assert ges.main(["--output", str(doc), "--check"]) == 1
    assert "markers" in capsys.readouterr().err.lower()


def test_AC14_1_22_committed_readme_block_is_current() -> None:
    """AC14.1.22: the committed README EPIC status pointer block is drift-free."""
    repo_root = Path(__file__).resolve().parents[2]
    readme = repo_root / "README.md"
    document = readme.read_text(encoding="utf-8")
    assert ges.BEGIN_MARKER in document, "README is missing the generated EPIC block"

    # The committed block is the STABLE pointer (no live numbers), so a shifted
    # AC total never makes it stale.
    pointer = ges.render_pointer_block()
    assert ges.splice_block(document, pointer) == document
    # And the live numeric table still renders on demand (derived view).
    live = ges.generate_block(repo_root=repo_root)
    assert "| EPIC-001 |" in live
