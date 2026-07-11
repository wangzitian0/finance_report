"""Contract: cross-document SSOT concepts are anchored and registered (issue #340).

Five cross-document concepts must each be (a) registered in
``docs/ssot/MANIFEST.yaml`` with an anchored owner and (b) backed by an explicit
``<a id="...">`` HTML anchor in the owning document, so links survive
heading edits. ``tools/check_manifest.py`` already proves anchor *resolution*;
this test pins the specific cross-document concepts the issue calls out.

The owner is a repo-relative path; most live in ``docs/ssot/`` but a concept may
own its anchor from a package readme once its SSOT is internalized into the
package (migration-standard step 3) — e.g. ``extraction_confidence_tiers`` now
owns ``common/extraction/readme.md#confidence-scoring``.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SSOT = ROOT / "docs" / "ssot"
MANIFEST = SSOT / "MANIFEST.yaml"

# concept key -> (owner path relative to repo root, required explicit anchor id)
REQUIRED_CONCEPTS: dict[str, tuple[str, str]] = {
    "reconciliation_thresholds": ("common/reconciliation/readme.md", "thresholds"),
    "reconciliation_state_machine": (
        "common/reconciliation/readme.md",
        "state-machine",
    ),
    "extraction_confidence_tiers": (
        "common/extraction/readme.md",
        "confidence-scoring",
    ),
    "confirmation_workflow_states": (
        "docs/ssot/confirmation-workflow.md",
        "state-machine",
    ),
    "confidence_tier_rollup": (
        "docs/ssot/confirmation-workflow.md",
        "confidence-tier-rollup",
    ),
}

_ANCHOR_RE = re.compile(r"<a\s+id=[\"']([^\"']+)[\"']\s*>")


def _explicit_anchors(path: Path) -> set[str]:
    return set(_ANCHOR_RE.findall(path.read_text(encoding="utf-8")))


def test_AC8_13_133_concepts_registered_in_manifest_with_anchored_owner() -> None:
    """AC-testing.governance.9: AC8.13.133: each cross-document concept owns an anchored MANIFEST entry."""
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    concepts = data["concepts"]
    for key, (owner_path, anchor) in REQUIRED_CONCEPTS.items():
        assert key in concepts, f"MANIFEST missing concept '{key}'"
        owner = concepts[key]["owner"]
        assert owner == f"{owner_path}#{anchor}", (
            f"concept '{key}' owner must be {owner_path}#{anchor}, got {owner}"
        )


def test_AC8_13_133_owning_docs_carry_explicit_html_anchors() -> None:
    """AC8.13.133: the owning doc carries the explicit <a id> anchor."""
    for key, (owner_path, anchor) in REQUIRED_CONCEPTS.items():
        anchors = _explicit_anchors(ROOT / owner_path)
        assert anchor in anchors, (
            f"{owner_path} must define explicit <a id=\"{anchor}\"> for concept '{key}'"
        )
