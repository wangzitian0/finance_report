"""AC14.1.18: Finance Report's SSOT HLS family model is documented and consistent.

This is a documentation-governance test for issue #821. It does NOT move or
re-own any SSOT concept; it only asserts that:

1. EPIC-014 declares an SSOT HLS family model
   with 6-8 families plus explicit concept/clause boundary rules.
2. The declared family map is machine-parseable from the doc and is consistent
   with the existing MANIFEST.yaml groupings (every manifest entry's inferred
   family is covered by exactly one declared family).
3. The HLS governance checklist links #821 and the follow-up
   metric/gate/cleanup issues (#822, #823, #824).

The first step of #821 is documentation only; ownership stays in MANIFEST.yaml.
"""

from __future__ import annotations

import re
from pathlib import Path

from common.meta.extension import governance_report
from common.meta.extension.check_manifest import load_computed_concepts

ROOT = Path(__file__).resolve().parents[2]

FR_EPIC = ROOT / "docs/project/EPIC-014.ttd-transformation.md"
FR_MANIFEST = ROOT / "common/meta/data/MANIFEST.yaml"

ISSUE_LINKS = (
    "/issues/821",
    "/issues/822",
    "/issues/823",
    "/issues/824",
)

FAMILY_SECTION_HEADING = "## SSOT HLS Family Model"
FAMILY_ROW = re.compile(r"^\|\s*`(?P<family>[a-z0-9_]+)`\s*\|")


def _read(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Required SSOT file not found: {path}.")
    return path.read_text(encoding="utf-8")


def _family_section(text: str) -> str:
    assert FAMILY_SECTION_HEADING in text, f"missing '{FAMILY_SECTION_HEADING}' section"
    after = text.split(FAMILY_SECTION_HEADING, 1)[1]
    # Stop at the next level-2 heading.
    return after.split("\n## ", 1)[0]


def _declared_families(text: str) -> list[str]:
    section = _family_section(text)
    families: list[str] = []
    for line in section.splitlines():
        match = FAMILY_ROW.match(line.strip())
        if match:
            families.append(match.group("family"))
    return families


def _entries_inferred_families(raw_entries: dict) -> set[str]:
    families: set[str] = set()
    for key, raw in raw_entries.items():
        entry = governance_report.GovernanceEntry(
            key=str(key),
            owner=str(raw.get("owner") or ""),
            description=str(raw.get("description") or ""),
            cross_refs=(),
            proofs=(),
            family=(str(raw["family"]) if raw.get("family") else None),
            kind=str(raw["kind"]) if raw.get("kind") else None,
            parent=None,
            authority=None,
        )
        families.add(governance_report._infer_family(entry))
    return families


def _backticked_tokens(text: str) -> set[str]:
    return set(re.findall(r"`([a-z0-9_]+)`", text))


def _family_member_counts(section: str) -> dict[str, int]:
    """Count occurrences of each backticked member token in the family-map table.

    Only the *member* column (the last cell of each `| `family` | … |` table
    row) is parsed, so prose and the scope column cannot create false positives.
    A token bound under multiple declared families is counted more than once.
    """
    counts: dict[str, int] = {}
    for line in section.splitlines():
        stripped = line.strip()
        if not FAMILY_ROW.match(stripped):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        member_cell = cells[-1]
        for token in re.findall(r"`([a-z0-9_]+)`", member_cell):
            counts[token] = counts.get(token, 0) + 1
    return counts


def _family_map_coverage(section: str, inferred: set[str]) -> set[str]:
    """Inferred manifest families not bound to exactly one declared family.

    Every inferred family must appear as a member token in exactly one
    family-map row's member column, so each manifest grouping is bound to
    exactly one declared family (no orphan grouping and no duplicate binding).
    """
    counts = _family_member_counts(section)
    return {fam for fam in inferred if counts.get(fam, 0) != 1}


def test_AC14_1_18_fr_hls_family_model_is_documented_and_consistent() -> None:
    """AC-meta.ssot-governance.7: EPIC-014 declares 6-8 FR families consistent with MANIFEST."""

    text = _read(FR_EPIC)
    families = _declared_families(text)

    assert 6 <= len(families) <= 8, (
        f"FR HLS model must declare 6-8 families, found {len(families)}: {families}"
    )
    assert len(families) == len(set(families)), "FR families must be unique"

    section = _family_section(text)
    assert "concept" in section.lower(), "family model must state concept boundary"
    assert "clause" in section.lower(), "family model must state clause boundary"
    assert "MANIFEST.yaml" in section, "family model must reference MANIFEST.yaml"

    # #1799: most concepts now live in package contracts, not the residual
    # MANIFEST.yaml — use the computed union (same source check_manifest.py
    # validates) so the family-map coverage check still sees all of them.
    inferred = _entries_inferred_families(load_computed_concepts(ROOT, FR_MANIFEST))
    uncovered = _family_map_coverage(section, inferred)
    assert not uncovered, (
        "FR family map must bind each manifest-inferred family to exactly one "
        f"declared family; offending (missing or duplicated): {sorted(uncovered)}"
    )


def test_AC14_1_18_hls_checklist_links_governance_loop_issues() -> None:
    """AC14.1.18: The HLS checklist links #821 and follow-up #822/#823/#824."""

    text = _read(FR_EPIC)
    for link in ISSUE_LINKS:
        assert link in text, f"{FR_EPIC.name} must link {link}"


def test_AC14_1_18_documentation_only_does_not_re_own_concepts() -> None:
    """AC14.1.18: Defining the HLS model does not change manifest ownership.

    The family model is a definition layer. MANIFEST.yaml stays the single
    owner registry and must still parse with zero report errors after the docs
    land.
    """

    report = governance_report.build_report(ROOT, include_infra2=False)
    assert report["overall"]["errors"] == []
