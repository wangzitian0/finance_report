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
    """docs/project/'s file set is closed: no new file may silently appear.

    The EPIC-*.md half of the allowlist is exactly
    tests/tooling/test_epic_residue_ratchet.py's own baseline (single
    source — this test does not duplicate that vocabulary); the non-EPIC
    half is :data:`NON_EPIC_DOCS_PROJECT_ALLOWLIST`. Shrinking (deleting a
    file) is always allowed; growing outside the allowlist is not.
    """
    payload = json.loads(EPIC_RESIDUE_BASELINE.read_text(encoding="utf-8"))
    epic_allowlist: set[str] = set(payload["files"])
    allowlist = epic_allowlist | set(NON_EPIC_DOCS_PROJECT_ALLOWLIST)

    actual = {path.name for path in PROJECT_DIR.iterdir() if path.is_file()}
    unexpected = sorted(actual - allowlist)
    assert not unexpected, (
        "docs/project/ grew a file outside the #1823 terminal allowlist — new "
        "work belongs in a package (ac-workflow), and docs/project/ is a "
        "closed, shrink-only home (EPIC-*.md residue rows, plus a fixed set "
        "of non-EPIC governance docs). If this is a deliberate, reviewed "
        "exception, add it to NON_EPIC_DOCS_PROJECT_ALLOWLIST (or, for a new "
        "EPIC file, to the EPIC residue baseline instead — see "
        "test_epic_residue_ratchet.py).\n"
        f"unexpected: {unexpected}"
    )
