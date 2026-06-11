from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
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


def _assert_file_mentions(path: str, expected: list[str]) -> None:
    text = (ROOT / path).read_text(encoding="utf-8")
    for marker in expected:
        assert marker in text, f"{path} must mention {marker}"


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

    rendered_with_gate_edges = governance_report.render_markdown(
        {
            "sources": [
                {
                    "system": "field-coverage-edge",
                    "entry_count": 1,
                    "owner_count": 1,
                    "duplicate_owner_groups": [],
                    "orphan_ssot_files": [],
                    "field_coverage": "bad-shape",
                    "machine_owner_entries": {},
                    "high_risk_entries": {},
                    "future_gate_candidates": [],
                }
            ],
            "gate": {
                "changed_file_count": 1,
                "exception_count": 0,
                "violations": "bad-shape",
            },
        }
    )
    assert "| field-coverage-edge | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |" in (
        rendered_with_gate_edges
    )
    assert "- Result: PASS" in rendered_with_gate_edges

    rendered_with_bad_violation = governance_report.render_markdown(
        {
            "sources": [],
            "gate": {
                "changed_file_count": 1,
                "exception_count": 0,
                "violations": [
                    "bad-shape",
                    {
                        "code": "sample",
                        "target": "finance_report:manifest:sample",
                        "message": "sample",
                    },
                ],
            },
        }
    )
    assert "`sample` `finance_report:manifest:sample`: sample" in (
        rendered_with_bad_violation
    )


def test_AC14_1_12_ci_publishes_report_without_fail_on_error() -> None:
    """AC14.1.12: CI publishes baseline metrics without hard-failing report debt."""

    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "SSOT Governance Report" in workflow
    block = workflow.split("- name: SSOT Governance Report", 1)[1].split("- name:", 1)[
        0
    ]

    assert "tools/report_ssot_governance.py" in block
    assert "$GITHUB_STEP_SUMMARY" in block
    assert "--fail-on-error" not in block


def test_AC14_1_13_incremental_gate_only_blocks_changed_ssot_debt(
    tmp_path: Path,
) -> None:
    """AC14.1.13: SSOT governance gates block new debt without legacy cleanup."""

    _write(tmp_path / "docs/ssot/legacy-orphan.md")
    _write(tmp_path / "docs/ssot/new-orphan.md")
    _write(tmp_path / "docs/ssot/new-owned.md")
    _write(tmp_path / "docs/ssot/migration-risk.md")
    _write(tmp_path / "tests/tooling/test_new_owned.py")
    _write(tmp_path / "tests/tooling/test_migration_risk.py")
    _write_yaml(
        tmp_path / "docs/ssot/MANIFEST.yaml",
        {
            "concepts": {
                "legacy_without_family": {
                    "owner": "docs/ssot/legacy-owned.md",
                    "description": "Legacy entry remains report-only debt.",
                },
                "new_owned": {
                    "owner": "docs/ssot/new-owned.md",
                    "description": "New governed concept.",
                    "family": "tdd",
                    "cross_refs": ["tests/tooling/test_new_owned.py"],
                },
                "new_clause": {
                    "owner": "docs/ssot/new-owned.md#clause",
                    "description": "New clause with parent.",
                    "family": "tdd",
                    "kind": "clause",
                    "parent": "new_owned",
                },
                "migration_risk": {
                    "owner": "docs/ssot/migration-risk.md",
                    "description": "Migration gate proof.",
                    "family": "schema",
                    "cross_refs": ["tests/tooling/test_migration_risk.py"],
                },
                "missing_family": {
                    "owner": "docs/ssot/new-owned.md#missing-family",
                    "description": "New scoreable concept missing family.",
                },
                "missing_parent": {
                    "owner": "docs/ssot/new-owned.md#missing-parent",
                    "description": "New clause missing parent.",
                    "family": "tdd",
                    "kind": "clause",
                },
                "high_risk_without_proof": {
                    "owner": "docs/ssot/migration-risk.md#without-proof",
                    "description": "Migration deployment secret policy.",
                    "family": "schema",
                },
            }
        },
    )

    base_manifest = dedent(
        """
        concepts:
          legacy_without_family:
            owner: docs/ssot/legacy-owned.md
            description: Legacy entry remains report-only debt.
        """
    ).lstrip()
    changed_files = [
        "docs/ssot/MANIFEST.yaml",
        "docs/ssot/new-orphan.md",
        "docs/ssot/new-owned.md",
        "docs/ssot/migration-risk.md",
    ]

    gate = governance_report.evaluate_incremental_gate(
        tmp_path,
        changed_files,
        base_manifest_texts={"finance_report": base_manifest},
        include_infra2=False,
    )

    assert gate["enabled"] is True
    violation_pairs = {
        (violation["code"], violation["target"]) for violation in gate["violations"]
    }
    changed_surface_violations = {
        ("changed_ssot_file_without_owner", "finance_report:docs/ssot/new-orphan.md"),
        ("new_manifest_entry_missing_family", "finance_report:manifest:missing_family"),
        ("new_clause_missing_parent", "finance_report:manifest:missing_parent"),
        (
            "changed_high_risk_entry_missing_proof",
            "finance_report:manifest:high_risk_without_proof",
        ),
    }
    assert gate["violation_count"] == 8
    assert changed_surface_violations <= violation_pairs
    assert (
        "governance_ratio_decreased",
        "finance_report:ratio:high_risk_proof_coverage",
    ) in violation_pairs
    assert (
        "governance_debt_increased",
        "finance_report:debt:missing_family",
    ) in violation_pairs
    assert all(
        "github.com/wangzitian0/finance_report/issues/823" in violation["issue"]
        for violation in gate["violations"]
    )
    assert all("HLS" in violation["hls_rule"] for violation in gate["violations"])

    _write_yaml(
        tmp_path / "docs/ssot/governance-exceptions.yaml",
        {
            "version": 1,
            "exceptions": [
                {
                    "target": "finance_report:manifest:missing_family",
                    "issue": "https://github.com/wangzitian0/finance_report/issues/823",
                    "reason": "Temporary fixture exception.",
                }
            ],
        },
    )
    gate_with_exception = governance_report.evaluate_incremental_gate(
        tmp_path,
        changed_files,
        base_manifest_texts={"finance_report": base_manifest},
        include_infra2=False,
    )
    assert gate_with_exception["exception_path"] == (
        "docs/ssot/governance-exceptions.yaml"
    )
    assert gate_with_exception["violation_count"] == gate["violation_count"] - 1
    assert gate_with_exception["exception_count"] == 1
    assert all(
        violation["target"] != "finance_report:manifest:missing_family"
        for violation in gate_with_exception["violations"]
    )

    _write_yaml(
        tmp_path / "custom-governance-exceptions.yaml",
        {
            "version": 1,
            "exceptions": [
                {
                    "target": "finance_report:manifest:missing_family",
                    "issue": "https://github.com/wangzitian0/finance_report/issues/823",
                    "reason": "Temporary fixture exception.",
                }
            ],
        },
    )
    gate_with_custom_exception_path = governance_report.evaluate_incremental_gate(
        tmp_path,
        changed_files,
        base_manifest_texts={"finance_report": base_manifest},
        include_infra2=False,
        exceptions_path=Path("custom-governance-exceptions.yaml"),
    )
    assert (
        gate_with_custom_exception_path["exception_path"]
        == "custom-governance-exceptions.yaml"
    )
    assert gate_with_custom_exception_path["exception_count"] == 1


def test_AC14_1_13_gate_helper_edges_remain_incremental(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC14.1.13: Gate helper edge cases stay scoped to changed surfaces."""

    outside_root = tmp_path.parent / "outside-root"
    outside_path = outside_root / "docs/ssot/outside.md"
    assert (
        governance_report._source_relative_path(outside_path, tmp_path)
        == outside_path.as_posix()
    )

    finance_source = governance_report.ManifestSource(
        system="finance_report",
        source_root=tmp_path,
        manifest_path=tmp_path / "docs/ssot/MANIFEST.yaml",
        entry_key="concepts",
    )
    outside_source = governance_report.ManifestSource(
        system="outside",
        source_root=outside_root,
        manifest_path=outside_root / "docs/ssot/MANIFEST.yaml",
        entry_key="concepts",
    )
    assert governance_report._source_changed_files(
        outside_source,
        tmp_path,
        ["docs/ssot/root.md", "repo/docs/ssot/infra.md"],
    ) == ["docs/ssot/root.md"]

    infra_source = governance_report.ManifestSource(
        system="infra2",
        source_root=tmp_path / "repo",
        manifest_path=tmp_path / "repo/docs/ssot/MANIFEST.yaml",
        entry_key="entries",
    )
    assert governance_report._source_changed_files(
        infra_source,
        tmp_path,
        ["docs/ssot/root.md", "repo/docs/ssot/infra-risk.md"],
    ) == ["docs/ssot/infra-risk.md"]
    assert governance_report._changed_ssot_files(
        ["docs/readme.md", "docs/ssot/README.md", "docs/ssot/owned.md"]
    ) == ["docs/ssot/owned.md"]
    assert (
        governance_report._source_manifest_repo_path(
            outside_source,
            tmp_path,
        )
        == outside_source.manifest_path.as_posix()
    )

    assert (
        governance_report._read_base_manifest_text(
            tmp_path,
            finance_source,
            None,
        )
        is None
    )

    monkeypatch.setattr(
        governance_report.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=""),
    )
    assert (
        governance_report._read_base_manifest_text(
            tmp_path,
            finance_source,
            "missing-base",
        )
        is None
    )

    monkeypatch.setattr(
        governance_report.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="concepts: {}\n"),
    )
    assert (
        governance_report._read_base_manifest_text(
            tmp_path,
            finance_source,
            "base",
        )
        == "concepts: {}\n"
    )

    exceptions_path = tmp_path / "docs/ssot/governance-exceptions.yaml"
    _write(exceptions_path, "[]\n")
    assert (
        governance_report._load_exception_targets(
            tmp_path,
            Path("docs/ssot/governance-exceptions.yaml"),
        )
        == set()
    )
    _write_yaml(exceptions_path, {"exceptions": "bad-shape"})
    assert (
        governance_report._load_exception_targets(
            tmp_path,
            Path("docs/ssot/governance-exceptions.yaml"),
        )
        == set()
    )
    _write_yaml(
        exceptions_path,
        {
            "exceptions": [
                "bad-shape",
                {"target": 1, "issue": "https://github.com/wangzitian0/x/issues/1"},
                {"target": "finance_report:manifest:no-issue", "issue": "not-an-issue"},
                {
                    "target": "finance_report:manifest:valid",
                    "issue": "https://github.com/wangzitian0/finance_report/issues/823",
                },
            ]
        },
    )
    assert governance_report._load_exception_targets(
        tmp_path,
        Path("docs/ssot/governance-exceptions.yaml"),
    ) == {"finance_report:manifest:valid"}

    malformed_exceptions_path = tmp_path / "bad-governance-exceptions.yaml"
    _write(malformed_exceptions_path, "exceptions: [\n")
    with pytest.raises(RuntimeError, match="Invalid SSOT governance exceptions YAML"):
        governance_report._load_exception_targets(
            tmp_path,
            Path("bad-governance-exceptions.yaml"),
        )

    _write(tmp_path / "docs/ssot/deployment.md")
    _write_yaml(
        tmp_path / "docs/ssot/MANIFEST.yaml",
        {
            "concepts": {
                "deployment_policy": {
                    "owner": "docs/ssot/deployment.md",
                    "description": "Deployment environment policy.",
                    "family": "deployment",
                }
            }
        },
    )
    gate = governance_report.evaluate_incremental_gate(
        tmp_path,
        ["docs/ssot/deployment.md", "docs/ssot/MANIFEST.yaml"],
        include_infra2=False,
    )
    assert gate["violation_count"] == 1
    assert gate["violations"][0]["code"] == "changed_high_risk_ssot_file_missing_proof"


def test_AC14_1_13_cli_and_ci_enable_gradual_gate(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC14.1.13: CLI/CI fail only on incremental SSOT gate violations."""

    _write(tmp_path / "docs/ssot/new-orphan.md")
    _write_yaml(tmp_path / "docs/ssot/MANIFEST.yaml", {"concepts": {}})
    changed_files = tmp_path / "changed-files.txt"
    changed_files.write_text("docs/ssot/new-orphan.md\n", encoding="utf-8")

    assert (
        governance_report.main(
            [
                "--repo-root",
                str(tmp_path),
                "--no-infra2",
                "--changed-files",
                str(changed_files),
            ]
        )
        == 0
    )
    assert (
        governance_report.main(
            [
                "--repo-root",
                str(tmp_path),
                "--no-infra2",
                "--changed-files",
                str(changed_files),
                "--fail-on-gate",
            ]
        )
        == 1
    )

    malformed_exceptions = tmp_path / "bad-governance-exceptions.yaml"
    malformed_exceptions.write_text("exceptions: [\n", encoding="utf-8")
    assert (
        governance_report.main(
            [
                "--repo-root",
                str(tmp_path),
                "--no-infra2",
                "--changed-files",
                str(changed_files),
                "--exceptions",
                str(malformed_exceptions),
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert "ERROR: Invalid SSOT governance exceptions YAML" in captured.err

    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "--fail-on-gate" in workflow
    assert "ssot-changed-files.txt" in workflow

    rendered = governance_report.render_markdown(
        {
            "sources": [],
            "gate": {
                "hls_rule": governance_report.GATE_HLS_RULE,
                "changed_file_count": 1,
                "exception_path": "custom-governance-exceptions.yaml",
                "exception_count": 0,
                "violations": [
                    {
                        "code": "sample",
                        "target": "finance_report:manifest:sample",
                        "message": "sample",
                    }
                ],
            },
        }
    )
    assert "github.com/wangzitian0/finance_report/issues/823" in rendered
    assert "- Exception registry: `custom-governance-exceptions.yaml`" in rendered


def test_AC14_1_16_ssot_governance_ratios_cannot_regress(
    tmp_path: Path,
) -> None:
    """AC14.1.16: #823 gate keeps protected SSOT governance ratios from falling."""

    for relative_path in (
        "docs/ssot/shaped.md",
        "docs/ssot/legacy-kind.md",
        "docs/ssot/new-family-only.md",
        "docs/ssot/migration-risk.yaml",
        "docs/ssot/migration-risk-reviewed.yaml",
        "tests/tooling/test_migration_risk.py",
    ):
        _write(tmp_path / relative_path)

    base_manifest = dedent(
        """
        concepts:
          shaped:
            owner: docs/ssot/shaped.md
            description: Fully shaped concept.
            family: tdd
            kind: concept
          legacy_kind_gap:
            owner: docs/ssot/legacy-kind.md
            description: Existing kind debt remains advisory.
            family: tdd
          migration_reviewed:
            owner: docs/ssot/migration-risk-reviewed.yaml
            description: Migration risk matrix with proof.
            family: schema
            kind: matrix
            proofs:
              - tests/tooling/test_migration_risk.py
          migration_unreviewed:
            owner: docs/ssot/migration-risk.yaml
            description: Existing migration risk matrix proof debt.
            family: schema
            kind: matrix
        """
    ).lstrip()
    _write_yaml(
        tmp_path / "docs/ssot/MANIFEST.yaml",
        {
            "concepts": {
                "shaped": {
                    "owner": "docs/ssot/shaped.md",
                    "description": "Fully shaped concept.",
                    "family": "tdd",
                    "kind": "concept",
                },
                "legacy_kind_gap": {
                    "owner": "docs/ssot/legacy-kind.md",
                    "description": "Existing kind debt remains advisory.",
                    "family": "tdd",
                },
                "migration_reviewed": {
                    "owner": "docs/ssot/migration-risk-reviewed.yaml",
                    "description": "Migration risk matrix with proof.",
                    "family": "schema",
                    "kind": "matrix",
                    "proofs": ["tests/tooling/test_migration_risk.py"],
                },
                "migration_unreviewed": {
                    "owner": "docs/ssot/migration-risk.yaml",
                    "description": "Existing migration risk matrix proof debt.",
                    "family": "schema",
                    "kind": "matrix",
                },
                "new_family_only": {
                    "owner": "docs/ssot/new-family-only.md",
                    "description": "New entry keeps family but lowers kind ratio.",
                    "family": "tdd",
                },
            }
        },
    )

    gate = governance_report.evaluate_incremental_gate(
        tmp_path,
        ["docs/ssot/MANIFEST.yaml", "docs/ssot/new-family-only.md"],
        base_manifest_texts={"finance_report": base_manifest},
        include_infra2=False,
    )

    assert gate["enabled"] is True
    assert gate["trend_check_count"] == 8
    assert {
        (violation["code"], violation["target"]) for violation in gate["violations"]
    } == {
        (
            "governance_ratio_decreased",
            "finance_report:ratio:manifest_kind_coverage",
        ),
        ("governance_debt_increased", "finance_report:debt:missing_kind"),
    }
    ratio_violation = next(
        violation
        for violation in gate["violations"]
        if violation["code"] == "governance_ratio_decreased"
    )
    assert "0.7500 -> 0.6000" in ratio_violation["message"]
    assert (
        "github.com/wangzitian0/finance_report/issues/823" in ratio_violation["issue"]
    )

    _write_yaml(
        tmp_path / "docs/ssot/governance-exceptions.yaml",
        {
            "version": 1,
            "exceptions": [
                {
                    "target": "finance_report:ratio:manifest_kind_coverage",
                    "issue": "https://github.com/wangzitian0/finance_report/issues/823",
                    "reason": "Temporary fixture exception.",
                },
                {
                    "target": "finance_report:debt:missing_kind",
                    "issue": "https://github.com/wangzitian0/finance_report/issues/823",
                    "reason": "Temporary fixture exception.",
                },
            ],
        },
    )
    gate_with_exceptions = governance_report.evaluate_incremental_gate(
        tmp_path,
        ["docs/ssot/MANIFEST.yaml", "docs/ssot/new-family-only.md"],
        base_manifest_texts={"finance_report": base_manifest},
        include_infra2=False,
    )
    assert gate_with_exceptions["violation_count"] == 0
    assert gate_with_exceptions["exception_count"] == 2


def test_AC14_1_16_trend_checks_skip_invalid_or_unrelated_sources(
    tmp_path: Path,
) -> None:
    """AC14.1.16: Trend checks require valid source-local manifest data."""

    _write(tmp_path / "docs/ssot/shaped.md")
    _write_yaml(
        tmp_path / "docs/ssot/MANIFEST.yaml",
        {
            "concepts": {
                "shaped": {
                    "owner": "docs/ssot/shaped.md",
                    "description": "Fully shaped concept.",
                    "family": "tdd",
                    "kind": "concept",
                }
            }
        },
    )

    gate_with_invalid_base = governance_report.evaluate_incremental_gate(
        tmp_path,
        ["docs/ssot/MANIFEST.yaml"],
        base_manifest_texts={"finance_report": "concepts: ["},
        include_infra2=False,
    )
    assert gate_with_invalid_base["trend_check_count"] == 0
    assert gate_with_invalid_base["violation_count"] == 0

    gate_with_unrelated_change = governance_report.evaluate_incremental_gate(
        tmp_path,
        ["tests/tooling/test_unrelated.py"],
        base_manifest_texts={
            "finance_report": dedent(
                """
                concepts:
                  shaped:
                    owner: docs/ssot/shaped.md
                    description: Fully shaped concept.
                """
            ).lstrip()
        },
        include_infra2=False,
    )
    assert gate_with_unrelated_change["trend_check_count"] == 0
    assert gate_with_unrelated_change["violation_count"] == 0


def test_AC14_1_14_finance_report_orphan_ssot_files_are_manifest_owned() -> None:
    """AC14.1.14: #824 cleanup binds finance_report orphan SSOT files."""

    report = governance_report.build_report(ROOT, include_infra2=False)
    finance = _source(report, "finance_report")

    assert report["overall"]["errors"] == []
    assert finance["errors"] == []
    assert finance["entry_count"] > 0
    assert finance["orphan_ssot_files"] == []
    orphan_candidate = next(
        candidate
        for candidate in finance["future_gate_candidates"]
        if candidate["code"] == "orphan_ssot_files"
    )
    assert orphan_candidate["count"] == 0

    manifest = yaml.safe_load(
        (ROOT / "docs/ssot/MANIFEST.yaml").read_text(encoding="utf-8")
    )
    concepts = manifest["concepts"]

    assert concepts["statement_parsing_model_selection_logging"]["owner"] == (
        "docs/ssot/observability-logging.md"
    )
    assert concepts["statement_parsing_model_selection_logging"]["parent"] == (
        "observability_logging"
    )
    assert concepts["ac_score_ratchet_baseline"]["owner"] == (
        "docs/ssot/ac-score-baseline.json"
    )
    assert concepts["ac_score_ratchet_baseline"]["parent"] == "tdd_workflow"


def test_AC14_1_15_machine_owned_ssot_entries_have_explicit_shape_and_proof() -> None:
    """AC14.1.15: #824 migrates machine-owned FR SSOT entries by example."""

    report = governance_report.build_report(ROOT, include_infra2=False)
    finance = _source(report, "finance_report")

    assert report["overall"]["errors"] == []
    assert finance["errors"] == []
    assert finance["entry_count"] > 0
    assert finance["machine_owner_entries"]["missing_proof"] == []
    machine_candidate = next(
        candidate
        for candidate in finance["future_gate_candidates"]
        if candidate["code"] == "machine_owner_entries_missing_proof"
    )
    assert machine_candidate["count"] == 0

    manifest = yaml.safe_load(
        (ROOT / "docs/ssot/MANIFEST.yaml").read_text(encoding="utf-8")
    )
    concepts = manifest["concepts"]

    assert concepts["extraction_failed_case_registry"]["family"] == "extraction"
    assert concepts["extraction_failed_case_registry"]["kind"] == "registry"
    assert concepts["extraction_failed_case_registry"]["proofs"] == [
        "tests/tooling/test_extraction_failed_case_registry.py",
    ]
    assert concepts["source_coverage_matrix"]["family"] == "source"
    assert concepts["source_coverage_matrix"]["kind"] == "matrix"
    assert concepts["source_coverage_matrix"]["proofs"] == [
        "tests/tooling/test_source_coverage_matrix.py",
        "tools/check_source_coverage_matrix.py",
    ]

    inbound_refs = {
        "docs/ssot/README.md": [
            "[`extraction_failed_case_registry`](./extraction-audit-failed-cases.yaml)",
            "[`source_coverage_matrix`](./source-coverage-matrix.yaml)",
        ],
        "docs/ssot/extraction.md": [
            "[`extraction_failed_case_registry`](./extraction-audit-failed-cases.yaml)",
            "[`source_coverage_matrix`](./source-coverage-matrix.yaml)",
        ],
        "docs/project/EPIC-003.statement-parsing.md": [
            "[`extraction_failed_case_registry`](../ssot/extraction-audit-failed-cases.yaml)",
        ],
        "docs/project/EPIC-013.statement-parsing-v2.md": [
            "[`source_coverage_matrix`](../ssot/source-coverage-matrix.yaml)",
        ],
        "vision.md": [
            "[`source_coverage_matrix`](docs/ssot/source-coverage-matrix.yaml)",
        ],
        "docs/ssot/tdd.md": [
            "[`extraction_failed_case_registry`](./extraction-audit-failed-cases.yaml)",
            "[`source_coverage_matrix`](./source-coverage-matrix.yaml)",
        ],
    }
    for path, markers in inbound_refs.items():
        _assert_file_mentions(path, markers)
