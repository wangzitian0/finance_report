from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from textwrap import dedent

import yaml

from common.meta.extension import governance_report
from common.meta.extension.check_manifest import load_computed_concepts

ROOT = Path(__file__).resolve().parents[2]


def _write(path: Path, content: str = "content\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip(), encoding="utf-8")
    return path


def _write_yaml(path: Path, payload: dict[str, object]) -> Path:
    return _write(path, yaml.safe_dump(payload, sort_keys=False))


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _write_demo_contract(
    repo: Path, *, description: str, family: str | None, kind: str | None
) -> None:
    _write(
        repo / "common/demo/contract.py",
        f"""
        from common.meta.package_contract import ConceptRecord, PackageContract
        CONTRACT = PackageContract(
            name="demo", klass="domain", status="draft",
            depends_on=[], interface=[], events=[], invariants=[], roadmap=[],
            concepts=[ConceptRecord(
                key="demo_concept", owner="common/demo/readme.md",
                description={description!r}, family={family!r}, kind={kind!r},
            )],
        )
        """,
    )
    _write(repo / "common/demo/__init__.py", "")
    _write(repo / "common/demo/readme.md", "# Demo\n")


def _seed_computed_registry_repo(
    tmp_path: Path, *, family: str | None, kind: str | None
) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    shutil.copytree(
        ROOT / "common/meta",
        repo / "common/meta",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    _write(repo / "common/__init__.py", "")
    _write(
        repo / "common/meta/data/MANIFEST.yaml",
        """
        concepts:
          residual_concept:
            owner: common/meta/readme.md
            description: Residual concept remains shaped.
            family: platform
            kind: concept
        """,
    )
    _write_demo_contract(
        repo, description="Base package concept.", family=family, kind=kind
    )
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "governance-test@example.invalid")
    _git(repo, "config", "user.name", "Governance Test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    return repo, _git(repo, "rev-parse", "HEAD")


def _source(report: dict[str, object], system: str) -> dict[str, object]:
    sources = report["sources"]
    assert isinstance(sources, list)
    return next(s for s in sources if s["system"] == system)


def test_AC14_1_12_report_covers_finance_manifest_shape(tmp_path: Path) -> None:
    """AC-meta.ssot-governance.2: SSOT governance metrics report Finance Report's manifest."""
    for rel in (
        "docs/ssot/accounting.md",
        "docs/ssot/deployment.md",
        "common/meta/data/migration-risk.yaml",
        "docs/ssot/orphan.md",
        "docs/ssot/schema.md",
        "tools/check_deployment.py",
    ):
        _write(tmp_path / rel)
    _write(
        tmp_path / "common/meta/data/MANIFEST.yaml",
        """
        concepts:
          decimal_rule:
            owner: docs/ssot/accounting.md
            description: Decimal monetary rule.
          duplicate_decimal_rule:
            owner: docs/ssot/accounting.md
            description: Intentional duplicate.
          migration_matrix:
            owner: common/meta/data/migration-risk.yaml
            description: Migration risk matrix.
            kind: matrix
            cross_refs: [docs/ssot/schema.md]
          deployment_contract:
            owner: docs/ssot/deployment.md
            description: Deployment environment contract.
            family: ops
            kind: concept
            cross_refs: [tools/check_deployment.py]
          deployment_clause_without_parent:
            owner: docs/ssot/deployment.md#clause
            description: Explicit clause missing parent.
            family: ops
            kind: clause
        """,
    )
    report = governance_report.build_report(tmp_path)
    finance = _source(report, "finance_report")
    assert report["report_only"] is True and report["overall"]["entry_count"] == 5
    assert finance["entry_count"] == 5 and finance["owner_count"] == 4
    assert finance["duplicate_owner_groups"] == [
        {
            "owner": "docs/ssot/accounting.md",
            "keys": ["decimal_rule", "duplicate_decimal_rule"],
        }
    ]
    assert finance["orphan_ssot_files"] == [
        "docs/ssot/orphan.md",
        "docs/ssot/schema.md",
    ]
    assert finance["machine_owner_entries"]["missing_proof"] == ["migration_matrix"]
    markdown = governance_report.render_markdown(report)
    assert "| finance_report | 5 | 4 | 1 | 2 | 3 | 2 | 1 | 2 |" in markdown


def test_AC14_1_13_incremental_gate_only_blocks_changed_ssot_debt(
    tmp_path: Path,
) -> None:
    """AC-meta.ssot-governance.3: SSOT governance gates block new debt without legacy cleanup."""
    for rel in (
        "docs/ssot/legacy-orphan.md",
        "docs/ssot/new-orphan.md",
        "docs/ssot/new-owned.md",
        "docs/ssot/migration-risk.md",
        "tests/tooling/test_new_owned.py",
        "tests/tooling/test_migration_risk.py",
    ):
        _write(tmp_path / rel)
    _write(
        tmp_path / "common/meta/data/MANIFEST.yaml",
        """
        concepts:
          legacy_without_family:
            owner: docs/ssot/legacy-owned.md
            description: Legacy entry remains report-only debt.
          new_owned:
            owner: docs/ssot/new-owned.md
            description: New governed concept.
            family: tdd
            cross_refs: [tests/tooling/test_new_owned.py]
          new_clause:
            owner: docs/ssot/new-owned.md#clause
            description: New clause with parent.
            family: tdd
            kind: clause
            parent: new_owned
          migration_risk:
            owner: docs/ssot/migration-risk.md
            description: Migration gate proof.
            family: schema
            cross_refs: [tests/tooling/test_migration_risk.py]
          missing_family:
            owner: docs/ssot/new-owned.md#missing-family
            description: New scoreable concept missing family.
          missing_parent:
            owner: docs/ssot/new-owned.md#missing-parent
            description: New clause missing parent.
            family: tdd
            kind: clause
          high_risk_without_proof:
            owner: docs/ssot/migration-risk.md#without-proof
            description: Migration deployment secret policy.
            family: schema
        """,
    )
    base_manifest = "concepts:\n  legacy_without_family:\n    owner: docs/ssot/legacy-owned.md\n    description: Legacy entry.\n"
    changed = [
        "common/meta/data/MANIFEST.yaml",
        "docs/ssot/new-orphan.md",
        "docs/ssot/new-owned.md",
        "docs/ssot/migration-risk.md",
    ]
    gate = governance_report.evaluate_incremental_gate(
        tmp_path,
        changed,
        base_manifest_texts={"finance_report": base_manifest},
        include_infra2=False,
    )
    pairs = {(v["code"], v["target"]) for v in gate["violations"]}
    assert gate["enabled"] is True and gate["violation_count"] == 8
    assert {
        ("changed_ssot_file_without_owner", "finance_report:docs/ssot/new-orphan.md"),
        ("new_manifest_entry_missing_family", "finance_report:manifest:missing_family"),
        ("new_clause_missing_parent", "finance_report:manifest:missing_parent"),
        (
            "changed_high_risk_entry_missing_proof",
            "finance_report:manifest:high_risk_without_proof",
        ),
    } <= pairs
    _write(
        tmp_path / "common/meta/data/governance-exceptions.yaml",
        """
        version: 1
        exceptions:
          - target: finance_report:manifest:missing_family
            issue: https://github.com/wangzitian0/finance_report/issues/823
            reason: Temporary fixture exception.
            remove_when: The fixture replacement gate is active.
        """,
    )
    gate_exc = governance_report.evaluate_incremental_gate(
        tmp_path,
        changed,
        base_manifest_texts={"finance_report": base_manifest},
        include_infra2=False,
    )
    assert (
        gate_exc["violation_count"] == gate["violation_count"] - 1
        and gate_exc["exception_count"] == 1
    )


def test_AC14_1_16_ssot_governance_ratios_cannot_regress(tmp_path: Path) -> None:
    """AC-meta.ssot-governance.6: #823 gate keeps protected SSOT governance ratios from falling."""
    for rel in (
        "docs/ssot/shaped.md",
        "docs/ssot/legacy-kind.md",
        "docs/ssot/new-family-only.md",
        "common/meta/data/migration-risk.yaml",
        "docs/ssot/migration-risk-reviewed.yaml",
        "tests/tooling/test_migration_risk.py",
    ):
        _write(tmp_path / rel)
    base_manifest = dedent(
        """
        concepts:
          shaped: {owner: docs/ssot/shaped.md, description: Fully shaped., family: tdd, kind: concept}
          legacy_kind_gap: {owner: docs/ssot/legacy-kind.md, description: Existing debt., family: tdd}
          migration_reviewed: {owner: docs/ssot/migration-risk-reviewed.yaml, description: Reviewed., family: schema, kind: matrix, proofs: [tests/tooling/test_migration_risk.py]}
          migration_unreviewed: {owner: common/meta/data/migration-risk.yaml, description: Unreviewed., family: schema, kind: matrix}
        """
    ).lstrip()
    _write(
        tmp_path / "common/meta/data/MANIFEST.yaml",
        base_manifest
        + "  new_family_only: {owner: docs/ssot/new-family-only.md, description: Lowers kind ratio., family: tdd}\n",
    )
    gate = governance_report.evaluate_incremental_gate(
        tmp_path,
        ["common/meta/data/MANIFEST.yaml", "docs/ssot/new-family-only.md"],
        base_manifest_texts={"finance_report": base_manifest},
        include_infra2=False,
    )
    assert {(v["code"], v["target"]) for v in gate["violations"]} == {
        ("governance_ratio_decreased", "finance_report:ratio:manifest_kind_coverage"),
        ("governance_debt_increased", "finance_report:debt:missing_kind"),
    }


def test_AC_meta_ssot_governance_9_base_and_head_use_same_computed_concepts(
    tmp_path: Path,
) -> None:
    """AC-meta.ssot-governance.9: unchanged package debt is not a false delta."""
    repo, base_ref = _seed_computed_registry_repo(tmp_path, family=None, kind=None)
    _write_demo_contract(
        repo,
        description="HEAD changes only the package concept description.",
        family=None,
        kind=None,
    )
    gate = governance_report.evaluate_incremental_gate(
        repo, ["common/demo/contract.py"], base_ref=base_ref, include_infra2=False
    )
    assert gate["trend_check_count"] == 8 and gate["violation_count"] == 0


def test_AC14_1_14_finance_report_orphan_ssot_files_are_manifest_owned() -> None:
    """AC-meta.ssot-governance.4: #824 cleanup binds finance_report orphan SSOT files."""
    report = governance_report.build_report(ROOT, include_infra2=False)
    finance = _source(report, "finance_report")
    assert (
        report["overall"]["errors"] == []
        and finance["errors"] == []
        and finance["orphan_ssot_files"] == []
    )
    concepts = load_computed_concepts(ROOT, ROOT / "common/meta/data/MANIFEST.yaml")
    assert (
        concepts["statement_parsing_model_selection_logging"]["parent"]
        == "observability_logging"
    )
    assert concepts["protection_count_floor"]["parent"] == "tdd_workflow"


def test_AC14_1_15_machine_owned_ssot_entries_have_explicit_shape_and_proof() -> None:
    """AC-meta.ssot-governance.5: #824 migrates machine-owned FR SSOT entries by example."""
    report = governance_report.build_report(ROOT, include_infra2=False)
    assert (
        _source(report, "finance_report")["machine_owner_entries"]["missing_proof"]
        == []
    )
    concepts = load_computed_concepts(ROOT, ROOT / "common/meta/data/MANIFEST.yaml")
    assert concepts["extraction_failed_case_registry"]["proofs"] == [
        "tests/tooling/test_extraction_failed_case_registry.py"
    ]
    assert concepts["source_capability_proof_join"]["proofs"] == [
        "tests/tooling/test_source_capability_proof.py",
        "tools/check_ac_index.py",
    ]


def test_AC14_1_23_high_risk_ssot_entries_bind_proof_under_platform_family() -> None:
    """AC-meta.ssot-governance.8: #824 threshold cleanup drives high_risk_entries_missing_proof to zero."""
    report = governance_report.build_report(ROOT, include_infra2=False)
    assert _source(report, "finance_report")["high_risk_entries"]["missing_proof"] == []
    concepts = load_computed_concepts(ROOT, ROOT / "common/meta/data/MANIFEST.yaml")
    assert concepts["container_naming"]["proofs"] == [
        "tests/tooling/test_issue_489_deployment_contracts.py"
    ]
    assert concepts["test_optimization"]["proofs"] == [
        "apps/backend/tests/unit/infra/test_test_lifecycle.py",
        "tests/tooling/test_github_workflow_timing_summary.py",
    ]
