"""Contract: cross-document SSOT concepts are anchored and registered (issue #340).

Five cross-document concepts must each be (a) registered in
``docs/ssot/MANIFEST.yaml`` with an anchored owner and (b) backed by an explicit
``<a id="...">`` HTML anchor in the owning SSOT document, so links survive
heading edits. ``tools/check_manifest.py`` already proves anchor *resolution*;
this test pins the specific cross-document concepts the issue calls out.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SSOT = ROOT / "docs" / "ssot"
MANIFEST = SSOT / "MANIFEST.yaml"

# concept key -> (owning file, required explicit anchor id)
REQUIRED_CONCEPTS: dict[str, tuple[str, str]] = {
    "reconciliation_thresholds": ("reconciliation.md", "thresholds"),
    "reconciliation_state_machine": ("reconciliation.md", "state-machine"),
    "extraction_confidence_tiers": ("extraction.md", "confidence-scoring"),
    "confirmation_workflow_states": ("confirmation-workflow.md", "state-machine"),
    "confidence_tier_rollup": ("confirmation-workflow.md", "confidence-tier-rollup"),
}

_ANCHOR_RE = re.compile(r"<a\s+id=[\"']([^\"']+)[\"']\s*>")


def _explicit_anchors(path: Path) -> set[str]:
    return set(_ANCHOR_RE.findall(path.read_text(encoding="utf-8")))


def test_AC8_13_133_concepts_registered_in_manifest_with_anchored_owner() -> None:
    """AC8.13.133: each cross-document concept owns an anchored MANIFEST entry."""
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    concepts = data["concepts"]
    for key, (filename, anchor) in REQUIRED_CONCEPTS.items():
        assert key in concepts, f"MANIFEST missing concept '{key}'"
        owner = concepts[key]["owner"]
        assert owner == f"docs/ssot/{filename}#{anchor}", (
            f"concept '{key}' owner must be docs/ssot/{filename}#{anchor}, got {owner}"
        )


def test_AC8_13_133_owning_docs_carry_explicit_html_anchors() -> None:
    """AC8.13.133: the owning SSOT doc carries the explicit <a id> anchor."""
    for key, (filename, anchor) in REQUIRED_CONCEPTS.items():
        anchors = _explicit_anchors(SSOT / filename)
        assert anchor in anchors, (
            f'docs/ssot/{filename} must define explicit <a id="{anchor}"> '
            f"for concept '{key}'"
        )
