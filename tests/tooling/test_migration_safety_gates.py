"""Migration-safety gates for the package-model AC migration (issue #1355).

Covers the three gates that must hold before the legacy EPIC ACs are migrated
into package roadmaps:

- 1b ``check_tier_ast_literal`` — a shipped package's tier must be an AST-readable
  literal (else the registry untags it while the model keeps a tier).
- 1c ``check_epic_package_dual`` — an AC id must not live in both an EPIC table
  and a package roadmap (move ⇒ delete the EPIC row).
- 1e ``check_draft_packages`` — a draft package must carry no done ACs and must
  be registered.

These are SSOT/tooling-hardening tests (they protect the migration gates) and are
classified, not AC-owned, in docs/analysis/traceability-exceptions.md.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from common.ssot import check_draft_packages as g_draft
from common.ssot import check_epic_package_dual as g_dual
from common.ssot import check_tier_ast_literal as g_tier


def _write_contract(repo: Path, name: str, body: str) -> None:
    pkg = repo / "common" / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "contract.py").write_text(textwrap.dedent(body), encoding="utf-8")


def _active(name: str, *, tier: str = '"PC"', roadmap: str = "") -> str:
    return f"""
    from common.governance.package_contract import PackageContract, ACRecord
    CONTRACT = PackageContract(
        name="{name}", klass="kernel", status="active", tier={tier},
        depends_on=[], interface=[], events=[], invariants=[], roadmap=[{roadmap}])
    """


# --- 1b: tier must be an AST-readable literal ---------------------------------


def test_1b_passes_for_literal_tier(tmp_path: Path) -> None:
    _write_contract(tmp_path, "good", _active("good"))
    assert g_tier.violations(tmp_path) == []


def test_1b_flags_non_literal_tier_on_shipped_package(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        "bad",
        """
        from common.governance.package_contract import PackageContract
        T = "PC"
        CONTRACT = PackageContract(
            name="bad", klass="kernel", status="active", tier=T,
            depends_on=[], interface=[], events=[], invariants=[], roadmap=[])
        """,
    )
    errors = g_tier.violations(tmp_path)
    assert len(errors) == 1 and "AST-readable literal" in errors[0]


def test_1b_allows_undecided_tier_only_for_draft(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        "wip",
        """
        from common.governance.package_contract import PackageContract
        CONTRACT = PackageContract(
            name="wip", klass="kernel", status="draft",
            depends_on=[], interface=[], events=[], invariants=[], roadmap=[])
        """,
    )
    assert g_tier.violations(tmp_path) == []


# --- 1c: no AC id defined in both an EPIC table and a package -----------------


def _epic_and_package(tmp_path: Path, *, roadmap_id: str) -> Path:
    """An EPIC table defining AC99.1.1 and a package whose roadmap holds roadmap_id.

    The realistic dual-definition during migration is moving a legacy *numeric*
    id into a roadmap without deleting its EPIC row (the registry's EPIC parser
    only recognizes numeric ids), so the collision case keeps the numeric id.
    """
    epic_dir = tmp_path / "docs" / "project"
    epic_dir.mkdir(parents=True)
    (epic_dir / "EPIC-099.demo.md").write_text(
        "| AC99.1.1 | Some legacy AC | t | f | P0 |\n", encoding="utf-8"
    )
    _write_contract(
        tmp_path,
        "demo",
        _active(
            "demo",
            roadmap=(
                f'ACRecord(id="{roadmap_id}", statement="s", test="t::f", '
                'priority="P0", status="done"),'
            ),
        ),
    )
    return tmp_path


def test_1c_flags_dual_definition(tmp_path: Path) -> None:
    # Same numeric id left in the EPIC table AND moved into the roadmap.
    repo = _epic_and_package(tmp_path, roadmap_id="AC99.1.1")
    assert g_dual.dual_defined_ids(repo) == ["AC99.1.1"]


def test_1c_passes_when_disjoint(tmp_path: Path) -> None:
    # EPIC row deleted / renumbered: roadmap uses a distinct package-scoped id.
    repo = _epic_and_package(tmp_path, roadmap_id="AC-demo.1.1")
    assert g_dual.dual_defined_ids(repo) == []


# --- 1e: draft hygiene --------------------------------------------------------


def test_1e_flags_done_ac_in_draft(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        "wip",
        """
        from common.governance.package_contract import PackageContract, ACRecord
        CONTRACT = PackageContract(
            name="wip", klass="kernel", status="draft",
            depends_on=[], interface=[], events=[], invariants=[], roadmap=[
            ACRecord(id="AC-wip.1.1", statement="s", test="t::f",
                     priority="P0", status="done")])
        """,
    )
    baseline = tmp_path / "bl.json"
    baseline.write_text('{"draft_packages": ["wip"]}', encoding="utf-8")
    errors = g_draft.violations(tmp_path, baseline)
    assert any("done AC" in e for e in errors)


def test_1e_flags_unregistered_draft(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        "wip",
        """
        from common.governance.package_contract import PackageContract
        CONTRACT = PackageContract(
            name="wip", klass="kernel", status="draft",
            depends_on=[], interface=[], events=[], invariants=[], roadmap=[])
        """,
    )
    baseline = tmp_path / "bl.json"
    baseline.write_text('{"draft_packages": []}', encoding="utf-8")
    errors = g_draft.violations(tmp_path, baseline)
    assert any("not registered" in e for e in errors)


def test_1e_passes_for_registered_draft_without_done(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        "wip",
        """
        from common.governance.package_contract import PackageContract, ACRecord
        CONTRACT = PackageContract(
            name="wip", klass="kernel", status="draft",
            depends_on=[], interface=[], events=[], invariants=[], roadmap=[
            ACRecord(id="AC-wip.1.1", statement="s", test="t::f",
                     priority="P0", status="open")])
        """,
    )
    baseline = tmp_path / "bl.json"
    baseline.write_text('{"draft_packages": ["wip"]}', encoding="utf-8")
    assert g_draft.violations(tmp_path, baseline) == []
