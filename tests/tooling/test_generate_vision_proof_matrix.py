"""Tests for the generated vision-to-proof matrix.

AC14.1.19: The vision -> AC -> test proof matrix is mechanically generated from
vision.md anchors, EPIC ``Vision Anchor`` declarations, the AC registries, and
test references; it is published as a parseable YAML artifact plus a MkDocs page;
and ``--check`` fails on drift so the matrix cannot silently rot.
"""

from __future__ import annotations

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


def test_AC14_1_19_checked_in_artifacts_exist_and_are_generated() -> None:
    """AC14.1.19: the YAML + MkDocs page are checked in and marked generated."""
    yaml_text = gvpm.YAML_OUTPUT_PATH.read_text(encoding="utf-8")
    md_text = gvpm.MD_OUTPUT_PATH.read_text(encoding="utf-8")
    assert "DO NOT edit" in yaml_text
    assert "generate_vision_proof_matrix.py" in yaml_text
    assert "Vision-to-Proof Matrix" in md_text
    assert "generate_vision_proof_matrix.py" in md_text


def test_AC14_1_19_check_passes_when_artifacts_are_current(tmp_path) -> None:
    """AC14.1.19: --check passes when both artifacts match the generator."""
    yaml_out = tmp_path / "matrix.yaml"
    md_out = tmp_path / "matrix.md"
    assert gvpm.main(["--yaml-output", str(yaml_out), "--md-output", str(md_out)]) == 0
    assert (
        gvpm.main(
            [
                "--yaml-output",
                str(yaml_out),
                "--md-output",
                str(md_out),
                "--check",
            ]
        )
        == 0
    )


def test_AC14_1_19_check_fails_on_drift(tmp_path, capsys) -> None:
    """AC14.1.19: --check exits non-zero when an artifact is stale."""
    yaml_out = tmp_path / "matrix.yaml"
    md_out = tmp_path / "matrix.md"
    assert gvpm.main(["--yaml-output", str(yaml_out), "--md-output", str(md_out)]) == 0
    yaml_out.write_text("version: stale\n", encoding="utf-8")

    assert (
        gvpm.main(
            [
                "--yaml-output",
                str(yaml_out),
                "--md-output",
                str(md_out),
                "--check",
            ]
        )
        == 1
    )
    assert "stale" in capsys.readouterr().err.lower()


def test_AC14_1_19_check_fails_when_artifact_missing(tmp_path, capsys) -> None:
    """AC14.1.19: --check fails closed when an artifact is missing."""
    assert (
        gvpm.main(
            [
                "--yaml-output",
                str(tmp_path / "missing.yaml"),
                "--md-output",
                str(tmp_path / "missing.md"),
                "--check",
            ]
        )
        == 1
    )
    assert "missing" in capsys.readouterr().err.lower()


def test_AC14_1_19_wrapped_vision_anchor_continuation_is_captured(
    tmp_path, monkeypatch
) -> None:
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
