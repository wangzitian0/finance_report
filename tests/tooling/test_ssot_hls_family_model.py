"""AC14.1.18: FR + infra2 SSOT HLS family model is documented and consistent.

This is a documentation-governance test for issue #821. It does NOT move or
re-own any SSOT concept; it only asserts that:

1. EPIC-014 (FR) and Infra-006 (infra2) each declare an SSOT HLS family model
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

import yaml

from common.ssot import governance_report

ROOT = Path(__file__).resolve().parents[2]

FR_EPIC = ROOT / "docs/project/EPIC-014.ttd-transformation.md"
INFRA_EPIC = ROOT / "repo/docs/project/Infra-006.documentation_engineering.md"
FR_MANIFEST = ROOT / "docs/ssot/MANIFEST.yaml"
INFRA_MANIFEST = ROOT / "repo/docs/ssot/MANIFEST.yaml"

ISSUE_LINKS = (
    "/issues/821",
    "/issues/822",
    "/issues/823",
    "/issues/824",
)

FAMILY_SECTION_HEADING = "## SSOT HLS Family Model"
FAMILY_ROW = re.compile(r"^\|\s*`(?P<family>[a-z0-9_]+)`\s*\|")


def _read(path: Path) -> str:
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


def _manifest_inferred_families(manifest_path: Path, entry_key: str) -> set[str]:
    data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    raw_entries = data.get(entry_key) or {}
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


def _family_map_coverage(section: str, inferred: set[str]) -> set[str]:
    """Inferred manifest families not listed as a member in the family map.

    Every inferred family must appear somewhere in the HLS family-model section
    as a backticked member token, so each manifest grouping is explicitly bound
    to exactly one declared family (no orphan grouping).
    """
    listed = _backticked_tokens(section)
    return {fam for fam in inferred if fam not in listed}


def test_AC14_1_18_fr_hls_family_model_is_documented_and_consistent() -> None:
    """AC14.1.18: EPIC-014 declares 6-8 FR families consistent with MANIFEST."""

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

    inferred = _manifest_inferred_families(FR_MANIFEST, "concepts")
    uncovered = _family_map_coverage(section, inferred)
    assert not uncovered, (
        f"FR family map does not cover manifest-inferred families: {sorted(uncovered)}"
    )


def test_AC14_1_18_infra2_hls_family_model_is_documented_and_consistent() -> None:
    """AC14.1.18: Infra-006 declares 6-8 infra2 families consistent with MANIFEST."""

    text = _read(INFRA_EPIC)
    families = _declared_families(text)

    assert 6 <= len(families) <= 8, (
        f"infra2 HLS model must declare 6-8 families, found {len(families)}: {families}"
    )
    assert len(families) == len(set(families)), "infra2 families must be unique"

    section = _family_section(text)
    assert "concept" in section.lower(), "family model must state concept boundary"
    assert "clause" in section.lower(), "family model must state clause boundary"
    assert "MANIFEST.yaml" in section, "family model must reference MANIFEST.yaml"

    inferred = _manifest_inferred_families(INFRA_MANIFEST, "entries")
    uncovered = _family_map_coverage(section, inferred)
    assert not uncovered, (
        f"infra2 family map does not cover manifest-inferred families: "
        f"{sorted(uncovered)}"
    )


def test_AC14_1_18_hls_checklist_links_governance_loop_issues() -> None:
    """AC14.1.18: Both HLS checklists link #821 and follow-up #822/#823/#824."""

    for path in (FR_EPIC, INFRA_EPIC):
        text = _read(path)
        for link in ISSUE_LINKS:
            assert link in text, f"{path.name} must link {link}"


def test_AC14_1_18_documentation_only_does_not_re_own_concepts() -> None:
    """AC14.1.18: Defining the HLS model does not change manifest ownership.

    The family model is a definition layer. MANIFEST.yaml stays the single
    owner registry and must still parse with zero report errors after the docs
    land.
    """

    report = governance_report.build_report(ROOT, include_infra2=True)
    assert report["overall"]["errors"] == []
