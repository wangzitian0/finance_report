"""Tests for the generated vision-to-proof matrix.

AC14.1.19: The vision -> AC -> test proof matrix is mechanically generated from
vision.md anchors, EPIC ``Vision Anchor`` declarations, the AC registries, and
test references. It is a DERIVED view of the one AC-keyed graph, rendered on
demand (YAML + MkDocs page) and never committed-materialized; consistency (no
dangling vision item) is gated by ``tools/check_ac_index.py``.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from common.ssot import generate_vision_proof_matrix as gvpm


def _build():
    return gvpm.build_matrix()


def test_AC14_1_19_matrix_parses_vision_anchors_from_vision_md() -> None:
    """AC14.1.19: every node carries a real vision.md anchor id."""
    matrix = _build()
    anchor_ids = {node["anchor"] for node in matrix["vision_nodes"]}

    # Anchors that vision.md declares with <a id="..."> and EPICs reference.
    assert "decision-filter-accuracy-auditability" in anchor_ids
    assert "decision-1-portfolio-self-developed" in anchor_ids
    assert "decision-7-tech-stack" in anchor_ids

    declared = gvpm.load_vision_anchors(gvpm.VISION_PATH)
    for node in matrix["vision_nodes"]:
        assert node["anchor"] in declared, node["anchor"]


def test_AC14_1_19_matrix_maps_vision_to_ac_to_test() -> None:
    """AC14.1.19: nodes chain vision anchor -> EPIC -> AC -> test reference."""
    matrix = _build()
    by_anchor = {node["anchor"]: node for node in matrix["vision_nodes"]}

    # EPIC-017 anchors to decision-1 and owns AC17.* with real tests.
    node = by_anchor["decision-1-portfolio-self-developed"]
    assert "EPIC-017" in node["owner_epics"]
    ac_ids = {ac["id"] for ac in node["acs"]}
    assert any(ac_id.startswith("AC17.") for ac_id in ac_ids)
    # At least one AC under this vision node has a real test reference.
    assert any(ac["tests"] for ac in node["acs"])


def test_AC14_1_19_rendered_yaml_is_parseable_and_deterministic() -> None:
    """AC14.1.19: the YAML artifact round-trips and is byte-stable."""
    rendered = gvpm.render_yaml(_build())
    parsed = yaml.safe_load(rendered)
    assert parsed["version"]
    assert isinstance(parsed["vision_nodes"], list) and parsed["vision_nodes"]
    # Deterministic: regenerating yields identical bytes.
    assert gvpm.render_yaml(_build()) == rendered


def test_AC14_1_19_matrix_is_a_derived_view_not_committed() -> None:
    """AC14.1.19: the vision matrix is a DERIVED view, never committed-materialized.

    The previously-committed YAML + MkDocs page are removed; the matrix is
    rendered on demand from the AC graph and gated by tools/check_ac_index.py.
    """
    repo_root = Path(__file__).resolve().parents[2]
    assert not (repo_root / "docs/ssot/vision-proof-matrix.yaml").exists()
    assert not (repo_root / "docs/reference/vision-proof-matrix.md").exists()
    # The on-demand renderers still produce a generated, parseable artifact.
    yaml_text = gvpm.render_yaml(_build())
    md_text = gvpm.render_markdown(_build())
    assert "DO NOT edit" in yaml_text
    assert "generate_vision_proof_matrix.py" in yaml_text
    assert "Vision-to-Proof Matrix" in md_text
    assert "generate_vision_proof_matrix.py" in md_text


def test_AC14_1_19_check_builds_without_committing() -> None:
    """AC14.1.19: --check builds the matrix and never byte-compares a committed file."""
    assert gvpm.main(["--check"]) == 0


def test_AC14_1_19_on_demand_render_writes_only_when_requested(tmp_path) -> None:
    """AC14.1.19: the matrix is rendered on demand to an explicit output only."""
    yaml_out = tmp_path / "matrix.yaml"
    md_out = tmp_path / "matrix.md"
    assert gvpm.main(["--yaml-output", str(yaml_out), "--md-output", str(md_out)]) == 0
    assert yaml_out.exists() and md_out.exists()
    # Deterministic: a second render is byte-identical.
    assert gvpm.render_yaml(_build()) == yaml_out.read_text(encoding="utf-8")


def test_AC14_1_19_wrapped_vision_anchor_continuation_is_captured(tmp_path, monkeypatch) -> None:
    """AC14.1.19: anchors wrapped onto continuation blockquote lines are captured.

    A "Vision Anchor" declaration can wrap its anchor list across multiple
    blockquote lines. The parser must keep reading continuation blockquote lines
    until a new ``**Label**`` field opens, so a third anchor on the next line is
    not silently dropped. A following ``**Phase**`` field must terminate the
    declaration so unrelated backticked tokens are never mistaken for anchors.
    """
    epic = tmp_path / "EPIC-099.wrapped-anchor-fixture.md"
    epic.write_text(
        "# EPIC-099: Wrapped Anchor Fixture\n"
        "\n"
        "> **Status**: In Progress\n"
        "> **Vision Anchor**: `decision-2-event-middle-layer`, "
        "`decision-3-record-layer`,\n"
        "> `decision-filter-accuracy-auditability`\n"
        "> **Phase**: `not-an-anchor`\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(gvpm, "_epic_files", lambda: [epic])

    mapping = gvpm.load_epic_anchor_map()

    # All three anchors are captured, including the one on the wrapped line.
    assert mapping.get("decision-2-event-middle-layer") == ["EPIC-099"]
    assert mapping.get("decision-3-record-layer") == ["EPIC-099"]
    assert mapping.get("decision-filter-accuracy-auditability") == ["EPIC-099"]
    # The new **Phase** field terminates the declaration; its token is not an anchor.
    assert "not-an-anchor" not in mapping


def test_AC14_1_19_real_epic_019_wrapped_anchor_reaches_matrix() -> None:
    """AC14.1.19: EPIC-019's wrapped third anchor flows through to the matrix.

    EPIC-019 declares three Vision Anchors with the third wrapped onto the next
    blockquote line. That EPIC must be listed as an owner of the wrapped anchor
    node in the generated matrix.
    """
    epic_map = gvpm.load_epic_anchor_map()
    assert "EPIC-019" in epic_map.get("decision-filter-accuracy-auditability", [])

    matrix = _build()
    by_anchor = {node["anchor"]: node for node in matrix["vision_nodes"]}
    node = by_anchor["decision-filter-accuracy-auditability"]
    assert "EPIC-019" in node["owner_epics"]
