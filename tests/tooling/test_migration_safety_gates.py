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
classified, not AC-owned, in docs/project/traceability-exceptions.md.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from common.authority import check_authority_reconcile as g_reconcile
from common.ssot import check_draft_packages as g_draft
from common.ssot import check_epic_package_dual as g_dual
from common.authority import check_tier_ast_literal as g_tier


def _write_contract(repo: Path, name: str, body: str) -> None:
    pkg = repo / "common" / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "contract.py").write_text(textwrap.dedent(body), encoding="utf-8")


def _active(name: str, *, tier: str = '"CODE-ONLY"', roadmap: str = "") -> str:
    return f"""
    from common.meta.package_contract import PackageContract, ACRecord
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
        from common.meta.package_contract import PackageContract
        T = "CODE-ONLY"
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
        from common.meta.package_contract import PackageContract
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
        from common.meta.package_contract import PackageContract, ACRecord
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
        from common.meta.package_contract import PackageContract
        CONTRACT = PackageContract(
            name="wip", klass="kernel", status="draft",
            depends_on=[], interface=[], events=[], invariants=[], roadmap=[])
        """,
    )
    baseline = tmp_path / "bl.json"
    baseline.write_text('{"draft_packages": []}', encoding="utf-8")
    errors = g_draft.violations(tmp_path, baseline)
    assert any("not registered" in e for e in errors)


def test_1e_flags_unreadable_status_in_draft(tmp_path: Path) -> None:
    # status written as a non-literal must not silently bypass the done check.
    _write_contract(
        tmp_path,
        "wip",
        """
        from common.meta.package_contract import PackageContract, ACRecord
        S = "done"
        CONTRACT = PackageContract(
            name="wip", klass="kernel", status="draft",
            depends_on=[], interface=[], events=[], invariants=[], roadmap=[
            ACRecord(id="AC-wip.1.1", statement="s", test="t::f",
                     priority="P0", status=S)])
        """,
    )
    baseline = tmp_path / "bl.json"
    baseline.write_text('{"draft_packages": ["wip"]}', encoding="utf-8")
    errors = g_draft.violations(tmp_path, baseline)
    assert any("not an AST-readable literal" in e for e in errors)


def test_1e_load_baseline_rejects_malformed(tmp_path: Path) -> None:
    bad = tmp_path / "bl.json"
    bad.write_text('["wip"]', encoding="utf-8")  # a list, not an object
    with pytest.raises(ValueError):
        g_draft.load_baseline(bad)


def _ac_pointing_at(test_file: str) -> str:
    return (
        f'ACRecord(id="AC-p.1.1", statement="s", test="{test_file}::t", '
        'priority="P0", status="done"),'
    )


def test_reconcile_flags_llm_test_under_code_only(tmp_path: Path) -> None:
    # A CODE-ONLY package whose AC test drives the cassette harness = a real
    # declared-vs-detected contradiction.
    (tmp_path / "cass_test.py").write_text(
        "def t():\n    cassette.replay()  # cassette marker\n", encoding="utf-8"
    )
    _write_contract(
        tmp_path, "p", _active("p", tier='"CODE-ONLY"', roadmap=_ac_pointing_at("cass_test.py"))
    )
    violations, _ = g_reconcile.reconcile(tmp_path)
    assert any("declared CODE-ONLY but" in v for v in violations)


def test_reconcile_passes_code_only_with_deterministic_test(tmp_path: Path) -> None:
    (tmp_path / "det_test.py").write_text(
        "def t():\n    assert 1 == 1\n", encoding="utf-8"
    )
    _write_contract(
        tmp_path, "p", _active("p", tier='"CODE-ONLY"', roadmap=_ac_pointing_at("det_test.py"))
    )
    violations, _ = g_reconcile.reconcile(tmp_path)
    assert violations == []


def test_reconcile_flags_code_test_under_llm_only(tmp_path: Path) -> None:
    (tmp_path / "det_test.py").write_text(
        "def t():\n    assert 1 == 1\n", encoding="utf-8"
    )
    _write_contract(
        tmp_path, "p", _active("p", tier='"LLM-ONLY"', roadmap=_ac_pointing_at("det_test.py"))
    )
    violations, _ = g_reconcile.reconcile(tmp_path)
    assert any("declared LLM-ONLY but" in v for v in violations)


def test_1e_passes_for_registered_draft_without_done(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        "wip",
        """
        from common.meta.package_contract import PackageContract, ACRecord
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
