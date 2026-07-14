"""AC-meta.residue.1 — the EPIC residue ratchet (#1719, #1416 DoD addition).

The package migration (#1416/#1663) drained the EPIC tables into package
``roadmap``s; what remains in ``docs/project/EPIC-*.md`` is **residue** that
stays EPIC-owned on purpose. "Genuinely EPIC-owned" must be machine-checkable,
not a judgment call (#1719 DoD addition, 2026-07-11), so every surviving EPIC
AC definition line (a ``| ACx.y.z | ... |`` table row or a checklist bullet)
carries an explicit ``<!-- epic-owned: CATEGORY -->`` marker with one of the
categories in :data:`common.meta.extension.generate_ac_registry.
EPIC_RESIDUE_CATEGORIES`:

- ``fe-only`` — frontend-only proof (Vitest/Playwright); permanent residue —
  the governance gate resolves Python tests only (#1719 ruling).
- ``fe-half`` — the frontend half of a dual-proof AC whose backend half lives
  in a package roadmap; the row keeps an in-row pointer to the migrated half.
- ``horizontal`` — confirmed cross-module/infra scope (phase-0 scaffolding,
  infra2 submodule content, CI/CD tooling, archive-residual ownership rows).
- ``pending-package`` — stays EPIC-owned until a named blocker clears (the
  advisor be-cutover, an owner decision, missing coverage); NOT permanent —
  tracked for the post-migration backlog.

What CI enforces:

1. **Unmarked EPIC AC rows == 0** (hard, not baselined) — the umbrella's
   scoreboard metric. A definition line without a valid category marker fails.
2. **Census == baseline** (``docs/ssot/epic-residue-baseline.json``): per
   EPIC file, the per-category marked-row counts must equal the checked-in
   baseline exactly (the fk-cascade idiom). Silent growth is impossible;
   adding residue requires raising the baseline in the same PR, where the
   diff makes the choice reviewable; removed/migrated rows must prune the
   baseline so the burndown is visible.
3. **The EPIC file set only shrinks**: an EPIC file on disk that is not in
   the baseline fails (new EPIC files are minted only with a same-PR baseline
   edit — and the migration standard says: don't); a baseline entry with no
   file on disk must be pruned.
4. **Zero-residue files declare themselves**: an EPIC file with no marked
   rows must carry an explicit ``<!-- epic-file: design-doc -->`` or
   ``<!-- epic-file: goal-stub -->`` justification marker (the #1719 DoD's
   "deleted or carries an explicit design-doc justification").

The registry generator (``generate_ac_registry``) feeds the AC registry from
marked rows only, so an unmarked row is invisible to the registry AND fails
this gate — defense in depth, one vocabulary.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from common.meta.extension.generate_ac_registry import (
    EPIC_DIR,
    EPIC_RESIDUE_CATEGORIES,
    _epic_files,
    _extract_ac_definition,
)

REPO = Path(__file__).resolve().parents[2]
BASELINE_PATH = REPO / "docs/ssot/epic-residue-baseline.json"

#: Row-level residue marker. Kept in sync with the generator's parser by
#: sourcing the CATEGORY vocabulary from the same module constant.
RESIDUE_MARKER_RE = re.compile(r"<!--\s*epic-owned:\s*([a-z][a-z-]*)\s*-->")

#: File-level justification marker for EPIC files that keep zero AC rows.
FILE_MARKER_RE = re.compile(r"<!--\s*epic-file:\s*(design-doc|goal-stub)\s*-->")


def _census() -> tuple[dict[str, dict[str, int]], list[str], list[str]]:
    """Scan every EPIC doc for AC definition lines and their residue markers.

    Returns ``(per_file, unmarked, invalid)`` where ``per_file`` maps the EPIC
    file name to its ``{category: marked-row-count}`` (every file appears,
    even with zero rows), ``unmarked`` lists ``file:line ACid`` for definition
    lines with no marker, and ``invalid`` lists lines whose marker category is
    outside :data:`EPIC_RESIDUE_CATEGORIES`.
    """
    per_file: dict[str, dict[str, int]] = {}
    unmarked: list[str] = []
    invalid: list[str] = []
    for path in _epic_files(REPO / EPIC_DIR):
        counts: dict[str, int] = {}
        with open(path, encoding="utf-8") as handle:
            for lineno, line in enumerate(handle, 1):
                definition = _extract_ac_definition(line)
                if definition is None:
                    continue
                marker = RESIDUE_MARKER_RE.search(line)
                anchor = f"{path.name}:{lineno} {definition[0]}"
                if marker is None:
                    unmarked.append(anchor)
                elif marker.group(1) not in EPIC_RESIDUE_CATEGORIES:
                    invalid.append(f"{anchor} (category {marker.group(1)!r})")
                else:
                    counts[marker.group(1)] = counts.get(marker.group(1), 0) + 1
        per_file[path.name] = dict(sorted(counts.items()))
    return per_file, unmarked, invalid


def test_AC_meta_residue_1_census_is_nonvacuous() -> None:
    """Guard non-vacuity (#1416 DoD-addition 1): the scan must see the known set.

    At sanction time the EPIC directory holds 20+ EPIC docs. The sentinel was
    originally pinned to one always-large file (EPIC-016, then EPIC-022), but
    #1821 Wave B's whole point is draining every large fe-only/fe-half file
    down to a handful of documented exceptions -- pinning to any single file
    just means re-editing this test every PR as that file empties out. Sum
    across every file instead: `horizontal` and `pending-package` residue is
    permanent by design (EPIC-007 alone carries 30+ horizontal rows), so a
    real scan of the real root will always find a large total even after
    every fe-only/fe-half row is migrated. A census that sees fewer than 15
    files or a total under 40 residue definitions is scanning the wrong root,
    not a drained migration. If a future closeout genuinely deletes below the
    sentinel, lower it in that PR -- with the shrunken census in the same diff.
    """
    per_file, unmarked, invalid = _census()
    assert len(per_file) >= 15, (
        f"sentinel missing: expected >= 15 EPIC docs under {EPIC_DIR}, saw "
        f"{len(per_file)}; the census is scanning the wrong root"
    )
    total_definitions = (
        sum(sum(counts.values()) for counts in per_file.values())
        + len(unmarked)
        + len(invalid)
    )
    assert total_definitions >= 40, (
        f"sentinel missing: expected >= 40 AC definition lines total across all "
        f"EPIC docs, saw {total_definitions}; the definition parser is not "
        "matching the known row set"
    )


def test_AC_meta_residue_1_unmarked_epic_ac_rows_is_zero() -> None:
    per_file, unmarked, invalid = _census()
    assert not unmarked, (
        "unmarked EPIC AC rows found — every AC definition that stays in an "
        "EPIC doc must declare why with a trailing residue marker "
        "(AC-meta.residue.1; #1719). Append `<!-- epic-owned: "
        + "|".join(EPIC_RESIDUE_CATEGORIES)
        + " -->` to the line, or migrate the AC into its owning package's "
        "contract.py roadmap and delete the row. If the line is prose that "
        "merely mentions an AC id (a ghost match), reword it so it no longer "
        "parses as a definition.\n"
        f"unmarked ({len(unmarked)}):\n  " + "\n  ".join(unmarked)
    )
    assert not invalid, (
        "unknown residue categories — the marker vocabulary is "
        f"{EPIC_RESIDUE_CATEGORIES} (AC-meta.residue.1).\n"
        f"invalid ({len(invalid)}):\n  " + "\n  ".join(invalid)
    )


def test_AC_meta_residue_1_census_equals_baseline_and_files_only_shrink() -> None:
    assert BASELINE_PATH.exists(), (
        f"missing {BASELINE_PATH.name}: check in the residue baseline "
        "(docs/ssot/epic-residue-baseline.json) so the census is ratcheted"
    )
    payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    baseline: dict[str, dict[str, int]] = payload["files"]
    per_file, _unmarked, _invalid = _census()

    new_files = sorted(set(per_file) - set(baseline))
    assert not new_files, (
        "new EPIC file(s) — the EPIC file set may only shrink from the "
        "#1719 sanction (new ACs belong in a package contract.py roadmap, "
        "never a new EPIC table). If this file is genuinely sanctioned, add "
        "it to docs/ssot/epic-residue-baseline.json in this same PR so the "
        f"choice is visible in review.\nnew: {new_files}"
    )
    stale_files = sorted(set(baseline) - set(per_file))
    assert not stale_files, (
        "the baseline over-counts — EPIC file(s) were deleted (good!); "
        "prune docs/ssot/epic-residue-baseline.json in the same PR so the "
        f"ratchet stays tight.\nstale: {stale_files}"
    )

    drift = {
        name: (baseline[name], per_file[name])
        for name in sorted(per_file)
        if per_file[name] != baseline[name]
    }
    assert not drift, (
        "the marked-residue census drifted from "
        "docs/ssot/epic-residue-baseline.json — update the baseline in this "
        "same PR so residue growth is a reviewable choice and migration "
        "shrink stays visible (AC-meta.residue.1).\n"
        f"drift (baseline, actual): {json.dumps(drift, indent=2)}"
    )


def test_AC_meta_residue_1_zero_residue_files_declare_their_justification() -> None:
    per_file, _unmarked, _invalid = _census()
    missing: list[str] = []
    for path in _epic_files(REPO / EPIC_DIR):
        if sum(per_file.get(path.name, {}).values()) > 0:
            continue
        if not FILE_MARKER_RE.search(path.read_text(encoding="utf-8")):
            missing.append(path.name)
    assert not missing, (
        "EPIC file(s) with zero marked AC rows and no justification — the "
        "#1719 DoD requires each 0-row file to be deleted or carry an "
        "explicit `<!-- epic-file: design-doc -->` / `<!-- epic-file: "
        "goal-stub -->` marker explaining why it stays.\n"
        f"missing: {missing}"
    )
