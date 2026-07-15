"""Tests for the generated vision-to-proof matrix.

AC14.1.19: The vision -> AC -> test proof matrix is mechanically generated from
vision.md anchors, EPIC ``Vision Anchor`` declarations, the AC registries, and
test references. It is a DERIVED view of the one AC-keyed graph, rendered on
demand (YAML + MkDocs page) and never committed-materialized; consistency (no
dangling vision item) is gated by ``tools/check_ac_index.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from common.testing import generate_vision_proof_matrix as gvpm


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
    """AC-meta.generated-refs.2: nodes chain vision anchor -> EPIC -> AC -> test reference."""
    matrix = _build()
    by_anchor = {node["anchor"]: node for node in matrix["vision_nodes"]}

    # EPIC-017 owns decision-1, while its package roadmap directly contributes
    # the canonical AC that backs the node.
    node = by_anchor["decision-1-portfolio-self-developed"]
    assert "EPIC-017" in node["owner_epics"]
    acs = {ac["id"]: ac for ac in node["acs"]}
    migrated = acs["AC-portfolio.fe-assets2.21"]
    assert migrated["epic"] == "pkg-portfolio"
    expected_tests = {"apps/frontend/src/__tests__/holdingDetailPage.test.tsx"}
    assert expected_tests.issubset(migrated["tests"])


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
    monkeypatch.setattr(gvpm, "_epic_files", lambda epic_dir=gvpm.EPIC_DIR: [epic])

    mapping = gvpm.load_epic_anchor_map()

    # All three anchors are captured, including the one on the wrapped line.
    assert mapping.get("decision-2-event-middle-layer") == ["EPIC-099"]
    assert mapping.get("decision-3-record-layer") == ["EPIC-099"]
    assert mapping.get("decision-filter-accuracy-auditability") == ["EPIC-099"]
    # The new **Phase** field terminates the declaration; its token is not an anchor.
    assert "not-an-anchor" not in mapping


def _write_temp_vision_repo(root: Path) -> str:
    """Lay down a minimal vision.md + EPIC + registry under *root*.

    Returns a temp-only vision anchor id that exists ONLY in this checkout, so a
    test can prove the matrix was parsed from *root* (not the real repository).
    """
    anchor = "temp-only-isolated-anchor"
    (root / "vision.md").write_text(
        f'<a id="{anchor}"></a>\n\n## Temp Only Isolated Node\n',
        encoding="utf-8",
    )
    project = root / "docs" / "project"
    project.mkdir(parents=True, exist_ok=True)
    (project / "EPIC-077.temp.md").write_text(
        "# EPIC-077: Temp Isolation Fixture\n"
        "\n"
        f"> **Vision Anchor**: `{anchor}`\n"
        "\n"
        "## AC77.1.1: temp isolated criterion\n",
        encoding="utf-8",
    )
    docs = root / "docs"
    (docs / "ac_registry.yaml").write_text(
        "version: 1\n"
        "acs:\n"
        "  - id: AC77.1.1\n"
        "    epic: 77\n"
        "    epic_name: temp-isolation\n"
        "    description: temp isolated criterion\n"
        "    mandatory: true\n",
        encoding="utf-8",
    )
    (docs / "infra_registry.yaml").write_text("version: 1\nacs: []\n", encoding="utf-8")
    return anchor


def _write_temp_package_vision_contract(root: Path, anchor: str) -> None:
    package = root / "common" / "demo"
    package.mkdir(parents=True, exist_ok=True)
    (package / "contract.py").write_text(
        "from common.meta.base.package_contract import ACRecord, PackageContract\n"
        "\n"
        "CONTRACT = PackageContract(\n"
        "    name='demo',\n"
        "    klass='infra',\n"
        "    tier='CODE-ONLY',\n"
        "    depends_on=[],\n"
        "    interface=[],\n"
        "    events=[],\n"
        "    invariants=[],\n"
        "    roadmap=[\n"
        "        ACRecord(\n"
        "            id='AC-demo.vision.1',\n"
        "            statement='A package AC backs the temp vision node.',\n"
        "            test='tests/demo/test_vision.py::test_anchor',\n"
        "            priority='P0',\n"
        "            status='done',\n"
        f"            vision_anchor={anchor!r},\n"
        "        ),\n"
        "    ],\n"
        "    units=[],\n"
        ")\n",
        encoding="utf-8",
    )


def test_AC_meta_vision_anchor_2_package_ac_backs_vision_node(tmp_path: Path) -> None:
    """AC-meta.vision-anchor.2: package roadmap ACs directly back vision nodes."""
    anchor = _write_temp_vision_repo(tmp_path)
    _write_temp_package_vision_contract(tmp_path, anchor)
    gvpm.build_matrix.cache_clear()
    try:
        matrix = gvpm.build_matrix(tmp_path)
    finally:
        gvpm.build_matrix.cache_clear()

    node = next(item for item in matrix["vision_nodes"] if item["anchor"] == anchor)
    package_ac = next(ac for ac in node["acs"] if ac["id"] == "AC-demo.vision.1")
    assert package_ac["epic"] == "pkg-demo"
    assert package_ac["description"] == "A package AC backs the temp vision node."


def test_AC_meta_vision_anchor_2_unknown_package_anchor_is_rejected(
    tmp_path: Path,
) -> None:
    """AC-meta.vision-anchor.2: package declarations must resolve in vision.md."""
    _write_temp_vision_repo(tmp_path)
    _write_temp_package_vision_contract(tmp_path, "missing-vision-anchor")
    gvpm.build_matrix.cache_clear()
    try:
        with pytest.raises(ValueError, match="missing-vision-anchor.*vision.md"):
            gvpm.build_matrix(tmp_path)
    finally:
        gvpm.build_matrix.cache_clear()


def test_AC_meta_vision_anchor_2_migrated_package_acs_back_all_four_nodes() -> None:
    """AC-meta.vision-anchor.2: #1858's four residue rows stay vision-backed."""
    matrix = _build()
    by_anchor = {node["anchor"]: node for node in matrix["vision_nodes"]}
    expected = {
        "non-goals-not-robo-advisor": "AC-advisor.guardrail.1",
        "non-goals-not-budgeting-app": "AC-reporting.fe-viz-reports.33",
        "decision-5-processing-account": "AC-ledger.fe-processing.1",
        "decision-1-portfolio-self-developed": "AC-portfolio.fe-assets2.21",
    }

    for anchor, ac_id in expected.items():
        acs = {ac["id"]: ac for ac in by_anchor[anchor]["acs"]}
        assert ac_id in acs
        assert acs[ac_id]["tests"], f"{ac_id} must keep a real proof reference"


def test_AC14_1_19_build_matrix_is_sourced_from_passed_repo_root(tmp_path) -> None:
    """AC14.1.19: build_matrix(repo_root) parses vision.md from THAT root only.

    Regression guard for the root-mixing bug: when a non-default repo_root is
    passed (temp worktree / tests), the vision matrix must be read from that
    checkout, never from the real repository the module lives in.
    """
    anchor = _write_temp_vision_repo(tmp_path)
    gvpm.build_matrix.cache_clear()
    try:
        matrix = gvpm.build_matrix(tmp_path)
    finally:
        gvpm.build_matrix.cache_clear()

    anchors = {node["anchor"] for node in matrix["vision_nodes"]}
    # The temp-only anchor is present...
    assert anchor in anchors
    # ...and the real repo's anchors are NOT (proving we read the temp root).
    assert "decision-1-portfolio-self-developed" not in anchors


def test_AC14_1_19_graph_vision_items_come_from_passed_root(tmp_path) -> None:
    """AC14.1.19: build_ac_graph(repo_root=...) sources vision items from THAT root.

    The whole graph must be built from one consistent root; the vision slice was
    previously hard-wired to the module's own REPO_ROOT, so a non-default root
    silently read the real checkout. This asserts the vision items track the
    passed root.
    """
    from common.testing.ac_graph import build_ac_graph

    anchor = _write_temp_vision_repo(tmp_path)
    # build_ac_graph also needs an outcomes doc + baseline under the temp root.
    (tmp_path / "common" / "testing" / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "common" / "testing" / "data" / "critical-proof-outcomes.yaml").write_text(
        "version: '1.0'\noutcomes: []\n", encoding="utf-8"
    )
    (tmp_path / "common" / "testing" / "data" / "ac-score-baseline.jsonl").write_text("", encoding="utf-8")

    graph = build_ac_graph(tmp_path)
    vision_anchors = {item.anchor for item in graph.vision_items}
    assert anchor in vision_anchors
    assert "decision-1-portfolio-self-developed" not in vision_anchors


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
