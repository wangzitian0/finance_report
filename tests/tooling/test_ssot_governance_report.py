from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import pytest
import yaml

from common.ssot import governance_report


ROOT = Path(__file__).resolve().parents[2]


def _write(path: Path, content: str = "content\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip(), encoding="utf-8")
    return path


def _write_yaml(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _seed_finance_manifest(root: Path) -> None:
    for relative_path in (
        "docs/ssot/accounting.md",
        "docs/ssot/deployment.md",
        "docs/ssot/migration-risk.yaml",
        "docs/ssot/orphan.md",
        "docs/ssot/schema.md",
        "tools/check_deployment.py",
    ):
        _write(root / relative_path)

    _write_yaml(
        root / "docs/ssot/MANIFEST.yaml",
        {
            "concepts": {
                "decimal_rule": {
                    "owner": "docs/ssot/accounting.md",
                    "description": "Decimal monetary rule.",
                },
                "duplicate_decimal_rule": {
                    "owner": "docs/ssot/accounting.md",
                    "description": "Intentional duplicate for report metrics.",
                },
                "migration_matrix": {
                    "owner": "docs/ssot/migration-risk.yaml",
                    "description": "Migration risk matrix.",
                    "kind": "matrix",
                    "cross_refs": ["docs/ssot/schema.md"],
                },
                "deployment_contract": {
                    "owner": "docs/ssot/deployment.md",
                    "description": "Deployment environment contract.",
                    "family": "ops",
                    "kind": "concept",
                    "cross_refs": ["tools/check_deployment.py"],
                },
                "deployment_clause_without_parent": {
                    "owner": "docs/ssot/deployment.md#clause",
                    "description": "Explicit clause missing parent.",
                    "family": "ops",
                    "kind": "clause",
                },
            }
        },
    )


def _seed_infra_manifest(root: Path) -> None:
    for relative_path in (
        "repo/docs/ssot/ops.pipeline.md",
        "repo/docs/ssot/vault-inventory.yaml",
        "repo/libs/tests/test_pipeline.py",
    ):
        _write(root / relative_path)

    _write_yaml(
        root / "repo/docs/ssot/MANIFEST.yaml",
        {
            "entries": {
                "ops.pipeline": {
                    "owner": "docs/ssot/ops.pipeline.md",
                    "description": "CI deploy pipeline.",
                    "proofs": ["libs/tests/test_pipeline.py"],
                },
                "vault.inventory": {
                    "owner": "docs/ssot/vault-inventory.yaml",
                    "description": "Vault token inventory.",
                },
            }
        },
    )


def _source(report: dict[str, object], system: str) -> dict[str, object]:
    sources = report["sources"]
    assert isinstance(sources, list)
    matched = [source for source in sources if source["system"] == system]
    assert len(matched) == 1
    return matched[0]


def test_AC14_1_12_report_covers_finance_and_infra2_manifest_shapes(
    tmp_path: Path,
) -> None:
    """AC14.1.12: SSOT governance metrics report finance and infra2 manifests."""

    _seed_finance_manifest(tmp_path)
    _seed_infra_manifest(tmp_path)

    report = governance_report.build_report(tmp_path)

    assert report["report_only"] is True
    assert report["overall"]["entry_count"] == 7
    assert report["overall"]["errors"] == []

    finance = _source(report, "finance_report")
    assert finance["entry_key"] == "concepts"
    assert finance["entry_count"] == 5
    assert finance["owner_count"] == 4
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
    assert finance["field_coverage"]["family"]["missing"] == 3
    assert finance["field_coverage"]["kind"]["missing"] == 2
    assert finance["machine_owner_entries"]["missing_proof"] == ["migration_matrix"]
    assert "migration_matrix" in finance["high_risk_entries"]["missing_proof"]
    assert (
        "deployment_clause_without_parent"
        in finance["future_gate_candidates"][2]["sample"]
    )

    infra = _source(report, "infra2")
    assert infra["entry_key"] == "entries"
    assert infra["entry_count"] == 2
    assert infra["machine_owner_entries"]["missing_proof"] == ["vault.inventory"]
    assert infra["high_risk_entries"]["missing_proof"] == ["vault.inventory"]

    markdown = governance_report.render_markdown(report)
    assert "# SSOT Governance Report" in markdown
    assert "Report-only baseline" in markdown
    assert "| finance_report | 5 | 4 | 1 | 2 | 3 | 2 | 1 | 2 |" in markdown
    assert "`machine_owner_entries_missing_proof`" in markdown


def test_AC14_1_12_cli_writes_report_artifacts_without_blocking_findings(
    tmp_path: Path,
) -> None:
    """AC14.1.12: CLI writes report artifacts and findings remain non-blocking."""

    _seed_finance_manifest(tmp_path)
    json_out = tmp_path / "report.json"
    markdown_out = tmp_path / "report.md"

    exit_code = governance_report.main(
        [
            "--repo-root",
            str(tmp_path),
            "--no-infra2",
            "--json-out",
            str(json_out),
            "--markdown-out",
            str(markdown_out),
        ]
    )

    assert exit_code == 0
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["report_only"] is True
    assert len(payload["sources"]) == 1
    assert payload["overall"]["future_gate_candidate_count"] > 0
    assert markdown_out.read_text(encoding="utf-8").startswith(
        "# SSOT Governance Report"
    )


def test_AC14_1_12_fail_on_error_is_opt_in(tmp_path: Path) -> None:
    """AC14.1.12: Parse errors are report-only unless fail-on-error is enabled."""

    _write_yaml(tmp_path / "docs/ssot/MANIFEST.yaml", {"version": 1})

    assert governance_report.main(["--repo-root", str(tmp_path), "--no-infra2"]) == 0
    assert (
        governance_report.main(
            [
                "--repo-root",
                str(tmp_path),
                "--no-infra2",
                "--fail-on-error",
            ]
        )
        == 1
    )


def test_AC14_1_12_helper_and_error_branches_stay_report_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC14.1.12: Helper edge cases and parser errors do not become hidden gates."""

    assert governance_report._as_strings("single") == ("single",)
    assert governance_report._as_strings({"bad": "shape"}) == ()

    outside_path = tmp_path.parent / "outside.md"
    assert (
        governance_report._display_path(outside_path, tmp_path)
        == outside_path.as_posix()
    )
    assert (
        governance_report._display_ref(
            outside_path.parent,
            "docs/ssot/outside.md",
            tmp_path,
        )
        == "docs/ssot/outside.md"
    )
    assert (
        governance_report._display_ref(
            tmp_path / "repo",
            "docs/ssot/core.md",
            tmp_path,
        )
        == "repo/docs/ssot/core.md"
    )

    project_entry = governance_report.GovernanceEntry(
        key="project_policy",
        owner="docs/project/EPIC-014.ttd-transformation.md",
        description="Project policy.",
        cross_refs=(),
        proofs=(),
        family=None,
        kind=None,
        parent=None,
        authority=None,
    )
    dotted_entry = governance_report.GovernanceEntry(
        key="ops.pipeline",
        owner="",
        description="Pipeline.",
        cross_refs=(),
        proofs=(),
        family=None,
        kind=None,
        parent=None,
        authority=None,
    )
    underscored_entry = governance_report.GovernanceEntry(
        key="plain_key",
        owner="",
        description="Plain key.",
        cross_refs=(),
        proofs=(),
        family=None,
        kind=None,
        parent=None,
        authority=None,
    )
    unknown_entry = governance_report.GovernanceEntry(
        key="plain",
        owner="",
        description="Plain.",
        cross_refs=(),
        proofs=(),
        family=None,
        kind=None,
        parent=None,
        authority=None,
    )
    assert governance_report._infer_family(project_entry) == "project"
    assert governance_report._infer_family(dotted_entry) == "ops"
    assert governance_report._infer_family(underscored_entry) == "plain"
    assert governance_report._infer_family(unknown_entry) == "unknown"

    missing_source = governance_report.ManifestSource(
        system="missing",
        source_root=tmp_path,
        manifest_path=tmp_path / "docs/ssot/MANIFEST.yaml",
        entry_key="concepts",
    )
    entries, errors = governance_report._load_manifest_entries(missing_source)
    assert entries == []
    assert "manifest not found" in errors[0]
    assert "docs/ssot/MANIFEST.yaml" in errors[0]
    assert tmp_path.as_posix() not in errors[0]

    missing_root = tmp_path / "missing-root"
    _write(missing_root / "docs/ssot/orphan.md")
    missing_manifest_source = governance_report.ManifestSource(
        system="missing",
        source_root=missing_root,
        manifest_path=missing_root / "docs/ssot/MANIFEST.yaml",
        entry_key="concepts",
    )
    missing_report = governance_report.build_source_report(
        missing_manifest_source,
        tmp_path,
    )
    assert missing_report["errors"] == [
        "missing: manifest not found: docs/ssot/MANIFEST.yaml"
    ]
    assert missing_report["orphan_ssot_files"] == []
    assert missing_report["future_gate_candidates"][1]["count"] == 0

    _write(tmp_path / "docs/ssot/MANIFEST.yaml", "[1]\n")
    entries, errors = governance_report._load_manifest_entries(missing_source)
    assert entries == []
    assert "must be a YAML mapping" in errors[0]

    _write_yaml(
        tmp_path / "docs/ssot/MANIFEST.yaml",
        {"concepts": {"bad_entry": None}},
    )
    entries, errors = governance_report._load_manifest_entries(missing_source)
    assert entries == []
    assert "bad_entry" in errors[0]

    root_without_ssot = tmp_path / "empty-root"
    no_ssot_source = governance_report.ManifestSource(
        system="empty",
        source_root=root_without_ssot,
        manifest_path=root_without_ssot / "docs/ssot/MANIFEST.yaml",
        entry_key="concepts",
    )
    assert governance_report._orphan_ssot_files(no_ssot_source, [], tmp_path) == []

    (tmp_path / "docs/ssot/subdir").mkdir(parents=True)
    _write(tmp_path / "docs/ssot/README.md")
    assert governance_report._orphan_ssot_files(missing_source, [], tmp_path) == []

    monkeypatch.setattr(governance_report, "yaml", None)
    assert governance_report.main(["--repo-root", str(tmp_path), "--no-infra2"]) == 1
    captured = capsys.readouterr()
    assert "PyYAML is required" in captured.err


def test_AC14_1_12_markdown_renderer_handles_partial_report_shapes() -> None:
    """AC14.1.12: Markdown rendering is tolerant of partial advisory reports."""

    report = {
        "sources": [
            "not-a-source",
            {
                "system": "partial",
                "entry_count": 1,
                "owner_count": 1,
                "duplicate_owner_groups": [],
                "orphan_ssot_files": [],
                "field_coverage": {"family": "bad-shape", "kind": "bad-shape"},
                "machine_owner_entries": "bad-shape",
                "high_risk_entries": "bad-shape",
                "errors": ["partial: missing entries"],
                "future_gate_candidates": [
                    "not-a-candidate",
                    {
                        "code": "sample",
                        "count": 1,
                        "sample": [{"owner": "docs/ssot/sample.md"}, "other"],
                    },
                ],
            },
        ]
    }

    rendered = governance_report.render_markdown(report)

    assert "| partial | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |" in rendered
    assert "Report errors" in rendered
    assert "`sample`: 1 (sample: docs/ssot/sample.md, other)" in rendered


def test_AC14_1_12_ci_publishes_report_without_turning_it_into_a_gate() -> None:
    """AC14.1.12: CI publishes SSOT governance metrics without hard-failing debt."""

    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "SSOT Governance Report" in workflow
    block = workflow.split("- name: SSOT Governance Report", 1)[1].split("- name:", 1)[
        0
    ]

    assert "tools/report_ssot_governance.py" in block
    assert "$GITHUB_STEP_SUMMARY" in block
    assert "--fail-on-error" not in block
