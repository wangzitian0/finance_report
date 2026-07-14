"""AC-meta.residue.2 — the terminal allowlist gate (#1823, Package-ization
4/4, FINAL: "retire the center" closeout).

Package-ization dissolved two former "second homes" for cross-cutting
prose/data outside the package model:

- ``docs/ssot/`` (#1822, SSOT dissolution) — every prose doc moved into its
  owning package's ``readme.md``; every gate-data file moved into
  ``common/meta/data/`` (or another package's ``data/``); the
  concept-ownership registry (``MANIFEST.yaml``) and the EPIC residue
  ratchet baseline (``epic-residue-baseline.json``) both relocated to
  ``common/meta/data/`` in #1823. Nothing defaults to ``docs/ssot/`` anymore.
- ``docs/project/EPIC-*.md`` (#1719 + #1821, EPIC dissolution) — every AC
  migrated to a package ``contract.py`` roadmap except a documented,
  gate-tracked residue set (``tests/tooling/test_epic_residue_ratchet.py``).
  ``docs/project/`` is now a closed, shrink-only home: new work always
  starts in a package (``ac-workflow``), never a new EPIC-table row or file.

Both closures are structural claims, not just prose — this module makes them
CI-red-able so neither directory can silently regrow a parallel home for
concepts that belong in a package.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PROJECT_DIR = REPO / "docs" / "project"
SSOT_DIR = REPO / "docs" / "ssot"
EPIC_RESIDUE_BASELINE = REPO / "common" / "meta" / "data" / "epic-residue-baseline.json"

# Non-EPIC docs/project/ files frozen at the #1823 terminal snapshot. Shrink-only:
# deleting one requires pruning this set in the same PR; adding a new one requires
# a deliberate, reviewable edit here — the same fk-cascade idiom the EPIC residue
# ratchet (tests/tooling/test_epic_residue_ratchet.py) uses for EPIC-*.md counts.
NON_EPIC_DOCS_PROJECT_ALLOWLIST: frozenset[str] = frozenset(
    {
        "AC-AUDIT-2026-05-04.md",
        "AUDITS.md",
        "DECISIONS.md",
        "DELIVERY_ENGINE_RECOMMENDATIONS.md",
        "README.md",
        "traceability-exceptions.md",
    }
)


def _project_directory_violations(project_dir: Path, allowlist: set[str]) -> list[str]:
    """Return every entry under ``project_dir`` that violates the terminal freeze.

    ``docs/project/`` is flat by design and the allowlist only knows file
    names, so a subdirectory is unconditionally a violation — even an empty
    one, since its contents would otherwise be invisible to a plain
    ``path.is_file()`` scan (the gap a reviewer flagged in the first version
    of this gate: a subdirectory could smuggle in content without ever
    appearing in the file-name diff below).
    """
    entries = list(project_dir.iterdir())
    violations = [
        f"unexpected directory: {entry.name}" for entry in entries if entry.is_dir()
    ]
    actual_files = {entry.name for entry in entries if entry.is_file()}
    violations += [
        f"unexpected file: {name}" for name in sorted(actual_files - allowlist)
    ]
    return violations


def test_docs_ssot_directory_is_retired() -> None:
    """docs/ssot/ was fully retired in #1823 (Package-ization 4/4, terminal).

    MANIFEST.yaml and epic-residue-baseline.json moved to
    common/meta/data/ (the meta package's existing gate-data home);
    README.md's tombstone content is superseded by this test. Resurrecting
    the directory for any reason — even a single file — requires a
    deliberate edit here.
    """
    assert not SSOT_DIR.exists(), (
        "docs/ssot/ must not exist — it was retired in #1823 (Package-ization "
        "4/4, terminal). A package-owned concept belongs in that package's "
        "common/<pkg>/readme.md / contract.py; cross-cutting gate data "
        "belongs in common/meta/data/ (or another package's data/). If this "
        "is a deliberate, reviewed exception, update this test."
    )


def test_docs_project_directory_listing_is_frozen() -> None:
    """docs/project/'s entry set is closed: no new file OR subdirectory may
    silently appear.

    The EPIC-*.md half of the allowlist is exactly
    tests/tooling/test_epic_residue_ratchet.py's own baseline (single
    source — this test does not duplicate that vocabulary); the non-EPIC
    half is :data:`NON_EPIC_DOCS_PROJECT_ALLOWLIST`. Shrinking (deleting an
    entry) is always allowed; growing outside the allowlist, file or
    directory, is not.
    """
    payload = json.loads(EPIC_RESIDUE_BASELINE.read_text(encoding="utf-8"))
    allowlist = set(payload["files"]) | set(NON_EPIC_DOCS_PROJECT_ALLOWLIST)

    violations = _project_directory_violations(PROJECT_DIR, allowlist)
    assert not violations, (
        "docs/project/ grew outside the #1823 terminal allowlist — new work "
        "belongs in a package (ac-workflow), and docs/project/ is a closed, "
        "shrink-only home (EPIC-*.md residue rows, plus a fixed set of "
        "non-EPIC governance docs). If this is a deliberate, reviewed "
        "exception, add it to NON_EPIC_DOCS_PROJECT_ALLOWLIST (or, for a new "
        "EPIC file, to the EPIC residue baseline instead — see "
        "test_epic_residue_ratchet.py).\n"
        f"violations: {violations}"
    )


def test_project_directory_violations_catches_rogue_file_and_subdirectory(
    tmp_path: Path,
) -> None:
    """Red-path proof: an unlisted file AND an unlisted subdirectory both
    trip the gate — a subdirectory cannot smuggle in content invisibly.
    """
    (tmp_path / "README.md").write_text("allowed", encoding="utf-8")
    (tmp_path / "sneaky-new-doc.md").write_text("not allowlisted", encoding="utf-8")
    rogue_dir = tmp_path / "sneaky-subdir"
    rogue_dir.mkdir()
    (rogue_dir / "hidden.md").write_text(
        "invisible to a file-only scan", encoding="utf-8"
    )

    violations = _project_directory_violations(tmp_path, {"README.md"})

    assert "unexpected file: sneaky-new-doc.md" in violations
    assert "unexpected directory: sneaky-subdir" in violations
    assert len(violations) == 2


def test_project_directory_violations_empty_for_allowlisted_entries(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.md").write_text("allowed", encoding="utf-8")
    assert _project_directory_violations(tmp_path, {"README.md", "OTHER.md"}) == []
