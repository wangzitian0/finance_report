"""AC14.1.22: the README EPIC status block is a generated, checked pointer.

The per-EPIC numbers are a derived view of the AC graph and are not committed.
The README carries a fixed pointer block that ``--check`` verifies, so the
block never goes stale on a shifted AC total.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from common.testing import generate_epic_status as ges


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
    # The pointer names the on-demand per-EPIC table and carries no numbers.
    assert "tools/build_ac_traceability.py" in pointer
    assert "| EPIC-001 |" not in pointer
