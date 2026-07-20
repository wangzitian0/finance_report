from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from common.meta.base.governance_control import (
    DetectorObservation,
    EnforcementObservation,
    GovernanceGuarantee,
    GovernanceInitiative,
    IssueObservation,
    ProofObservation,
)
from common.meta.base.package_contract import ACRecord, PackageContract
from common.meta.data.governance_control import governance_control_index
from common.meta.data.projection import contract_index
from common.meta.extension.governance_control_report import render_governance_markdown
from common.meta.extension.generate_ac_registry import _package_roadmap_acs
from common.testing import package_governance


TARGET_SHA = "a" * 40
NOW = datetime(2026, 7, 20, tzinfo=UTC)


def _contract(*, ac_status: str = "done") -> PackageContract:
    ac = ACRecord(
        id="AC-demo.control.1",
        statement="The control remains exact.",
        test="tests/demo/test_control.py::test_control",
        priority="P0",
        status=ac_status,
        proof_kind="exact",
        vision_anchor="axiom-e-production-trust",
    )
    guarantee = GovernanceGuarantee(
        id="exact-control",
        statement="The declared control is current and enforced.",
        affected_acs=[ac.id],
        detector="demo-detector",
        target="zero findings",
        lock="ci.demo",
        proof="demo-proof",
        required_proof_strength="exact",
        enforcing_gate="ci.demo",
    )
    return PackageContract(
        name="demo",
        klass="domain",
        tier="CODE-ONLY",
        depends_on=[],
        interface=[],
        events=[],
        invariants=[],
        roadmap=[ac],
        governance=[
            GovernanceInitiative(
                id="control-plane",
                title="Demo control plane",
                issue="https://github.com/example/repo/issues/1",
                guarantees=[guarantee],
            )
        ],
    )


def _observations(
    *,
    proof_sha: str = TARGET_SHA,
    proof_strength: str = "exact",
    workflow_required: bool = True,
    live_required: bool = True,
    issue_state: str = "OPEN",
) -> tuple[list[DetectorObservation], list[ProofObservation], list[EnforcementObservation], list[IssueObservation]]:
    return (
        [DetectorObservation(guarantee_id="demo/exact-control", current=0, target=0, findings=[])],
        [
            ProofObservation(
                guarantee_id="demo/exact-control",
                proof_id="demo-proof",
                result="passed",
                strength=proof_strength,
                target_sha=proof_sha,
                occurred_at=NOW,
                evidence_url="https://github.com/example/repo/actions/runs/1",
                gate_id="ci.demo",
            )
        ],
        [
            EnforcementObservation(
                gate_id="ci.demo",
                declared_blocking=True,
                workflow_required=workflow_required,
                live_required=live_required,
                required_context="finish" if live_required else None,
                observed_at=NOW,
            )
        ],
        [
            IssueObservation(
                issue="https://github.com/example/repo/issues/1",
                state=issue_state,
                observed_at=NOW,
            )
        ],
    )


def _index(**overrides: object) -> dict[str, object]:
    detectors, proofs, enforcement, issues = _observations(**overrides)
    return governance_control_index(
        [_contract()],
        target_sha=TARGET_SHA,
        detector_observations=detectors,
        proof_observations=proofs,
        enforcement_observations=enforcement,
        issue_observations=issues,
        observed_at=NOW,
    )


def test_AC_meta_governance_control_1_contract_and_roadmap_projection_are_lossless(
    tmp_path: Path,
) -> None:
    """AC-meta.governance-control.1: declarations project losslessly and uniquely."""
    contract = _contract(ac_status="open")
    projected = contract_index([contract])

    assert projected["roadmap"]["AC-demo.control.1"] == {
        "owner": "demo",
        "statement": "The control remains exact.",
        "test": "tests/demo/test_control.py::test_control",
        "priority": "P0",
        "status": "open",
        "proof_kind": "exact",
        "vision_anchor": "axiom-e-production-trust",
    }
    assert len(projected["roadmap"]) == len(contract.roadmap)
    assert projected["governance"]["demo/control-plane"]["owner"] == "demo"

    duplicate = contract.roadmap[0].model_copy()
    with pytest.raises(ValueError, match="duplicate roadmap AC"):
        contract.model_copy(update={"roadmap": [contract.roadmap[0], duplicate]}).model_validate(
            contract.model_dump() | {"roadmap": [contract.roadmap[0], duplicate]}
        )

    (tmp_path / "docs/project").mkdir(parents=True)
    source = """
from common.meta.package_contract import ACRecord, PackageContract
CONTRACT = PackageContract(
    name={name!r}, klass="domain", tier="CODE-ONLY", depends_on=[],
    interface=[], events=[], invariants=[],
    roadmap=[ACRecord(id="AC-dup.control.1", statement="{name}",
        test="tests/test_dup.py::test_dup", priority="P0", status="open")],
)
"""
    for name in ("first", "second"):
        path = tmp_path / "common" / name / "contract.py"
        path.parent.mkdir(parents=True)
        path.write_text(source.format(name=name), encoding="utf-8")
    with pytest.raises(ValueError, match="refuses last-write-wins"):
        _package_roadmap_acs(tmp_path / "docs/project")


def test_AC_meta_governance_control_2_completion_is_derived_from_joined_facts() -> None:
    """AC-meta.governance-control.2: completion is derived from joined facts."""
    index = _index()
    initiative = index["initiatives"]["demo/control-plane"]
    guarantee = index["guarantees"]["demo/exact-control"]

    assert initiative["state"] == "enforced"
    assert initiative["current"] == 0
    assert initiative["target"] == 0
    assert initiative["open_guarantees"] == 0
    assert guarantee["state"] == "enforced"
    assert guarantee["findings"] == []


def test_AC_meta_governance_control_3_report_exposes_summary_and_exact_detail() -> None:
    """AC-meta.governance-control.3: summaries drill into exact evidence detail."""
    markdown = render_governance_markdown(_index())

    assert "| demo | Demo control plane | 0 / 0 | 0 | 0 | enforced |" in markdown
    assert "## demo/control-plane" in markdown
    assert "demo/exact-control" in markdown
    assert TARGET_SHA in markdown
    assert "2026-07-20T00:00:00Z" in markdown
    assert "https://github.com/example/repo/actions/runs/1" in markdown
    assert "ci.demo -> finish" in markdown


@pytest.mark.parametrize(
    ("overrides", "finding"),
    [
        ({"proof_strength": "report-only"}, "proof-strength-mismatch"),
        ({"proof_sha": "b" * 40}, "stale-proof"),
        ({"workflow_required": False}, "gate-not-in-workflow-aggregation"),
    ],
)
def test_AC_meta_governance_control_4_weak_stale_and_non_required_proof_stays_red(
    overrides: dict[str, object], finding: str
) -> None:
    """AC-meta.governance-control.4: weak or stale proof cannot become green."""
    guarantee = _index(**overrides)["guarantees"]["demo/exact-control"]

    assert guarantee["state"] != "enforced"
    assert finding in {item["code"] for item in guarantee["findings"]}


@pytest.mark.parametrize(
    ("overrides", "finding"),
    [
        ({"live_required": False}, "gate-not-live-required"),
        ({"issue_state": "CLOSED"}, "closed-issue-has-active-initiative"),
    ],
)
def test_AC_meta_governance_control_5_enforcement_reconciliation_fails_closed(
    overrides: dict[str, object], finding: str
) -> None:
    """AC-meta.governance-control.5: enforcement and work truth fail closed."""
    initiative = _index(**overrides)["initiatives"]["demo/control-plane"]

    assert initiative["state"] != "enforced"
    assert finding in {item["code"] for item in initiative["findings"]}

    detectors, proofs, _enforcement, issues = _observations()
    missing = governance_control_index(
        [_contract()],
        target_sha=TARGET_SHA,
        detector_observations=detectors,
        proof_observations=proofs,
        enforcement_observations=[],
        issue_observations=issues,
        observed_at=NOW,
    )
    findings = missing["initiatives"]["demo/control-plane"]["findings"]
    assert "missing-enforcement-observation" in {item["code"] for item in findings}


def test_governance_declarations_reject_vacuous_duplicate_and_foreign_edges() -> None:
    """AC-meta.governance-control.1: invalid package-owned declarations fail closed."""
    guarantee = _contract().governance[0].guarantees[0]
    guarantee_data = guarantee.model_dump()
    for update, message in (
        ({"id": " "}, "non-empty"),
        ({"affected_acs": []}, "at least one AC"),
        ({"affected_acs": ["AC-demo.control.1"] * 2}, "duplicate affected"),
    ):
        with pytest.raises(ValueError, match=message):
            GovernanceGuarantee.model_validate(guarantee_data | update)

    initiative = _contract().governance[0]
    initiative_data = initiative.model_dump()
    for update, message in (
        ({"title": " "}, "non-empty"),
        ({"guarantees": []}, "must declare guarantees"),
        ({"guarantees": [guarantee, guarantee]}, "duplicate guarantee"),
    ):
        with pytest.raises(ValueError, match=message):
            GovernanceInitiative.model_validate(initiative_data | update)

    contract_data = _contract().model_dump()
    duplicate_initiative = initiative.model_copy(update={"id": "other"})
    with pytest.raises(ValueError, match="duplicate governance initiative"):
        PackageContract.model_validate(
            contract_data | {"governance": [initiative, initiative]}
        )
    with pytest.raises(ValueError, match="duplicate governance guarantee"):
        PackageContract.model_validate(
            contract_data | {"governance": [initiative, duplicate_initiative]}
        )
    foreign = guarantee.model_copy(update={"affected_acs": ["AC-other.control.1"]})
    with pytest.raises(ValueError, match="references unowned ACs"):
        PackageContract.model_validate(
            contract_data
            | {
                "governance": [
                    initiative.model_copy(update={"guarantees": [foreign]})
                ]
            }
        )


def test_joined_projection_exposes_every_missing_and_regressed_edge() -> None:
    """AC-meta.governance-control.2: missing and contradictory joins stay visible."""
    missing = governance_control_index(
        [_contract(ac_status="open")],
        target_sha=TARGET_SHA,
        detector_observations=[],
        proof_observations=[],
        enforcement_observations=[],
        issue_observations=[],
        observed_at=NOW,
    )
    codes = {
        item["code"]
        for item in missing["initiatives"]["demo/control-plane"]["findings"]
    }
    assert {
        "missing-issue-observation",
        "open-acceptance-criteria",
        "missing-detector-observation",
        "missing-proof-observation",
        "missing-enforcement-observation",
    } <= codes

    detectors, proofs, enforcement, issues = _observations()
    detectors[0] = detectors[0].model_copy(
        update={"current": 2, "findings": ["two findings remain"]}
    )
    proofs[0] = proofs[0].model_copy(
        update={"proof_id": "wrong", "result": "failed", "gate_id": "wrong-gate"}
    )
    enforcement[0] = enforcement[0].model_copy(update={"declared_blocking": False})
    regressed = governance_control_index(
        [_contract()],
        target_sha=TARGET_SHA,
        detector_observations=detectors,
        proof_observations=proofs,
        enforcement_observations=enforcement,
        issue_observations=issues,
        observed_at=NOW,
    )
    row = regressed["guarantees"]["demo/exact-control"]
    assert row["state"] == "regressed"
    assert regressed["initiatives"]["demo/control-plane"]["state"] == "regressed"
    assert {
        "detector-finding",
        "target-not-met",
        "wrong-proof",
        "proof-not-passed",
        "proof-not-on-declared-gate",
        "gate-not-declared-blocking",
    } <= {item["code"] for item in row["findings"]}

    with pytest.raises(ValueError, match="duplicate detector observation"):
        governance_control_index(
            [_contract()],
            target_sha=TARGET_SHA,
            detector_observations=detectors * 2,
            proof_observations=proofs,
            enforcement_observations=enforcement,
            issue_observations=issues,
            observed_at=NOW,
        )


def test_package_governance_cli_reads_observations_and_writes_both_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-meta.governance-control.3: the CLI materializes JSON and Markdown detail."""
    detectors, proofs, enforcement, issues = _observations()
    observations = tmp_path / "observations.json"
    observations.write_text(
        json.dumps(
            {
                "target_sha": TARGET_SHA,
                "observed_at": NOW.isoformat(),
                "detectors": [item.model_dump(mode="json") for item in detectors],
                "proofs": [item.model_dump(mode="json") for item in proofs],
                "enforcement": [item.model_dump(mode="json") for item in enforcement],
                "issues": [item.model_dump(mode="json") for item in issues],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        package_governance,
        "discover_packages",
        lambda _root: [SimpleNamespace(contract=_contract())],
    )
    json_out = tmp_path / "report.json"
    markdown_out = tmp_path / "report.md"
    assert package_governance.main(
        [
            "--repo-root",
            str(tmp_path),
            "--observations",
            str(observations),
            "--json-out",
            str(json_out),
            "--markdown-out",
            str(markdown_out),
        ]
    ) == 0
    assert "demo/control-plane" in json_out.read_text(encoding="utf-8")
    assert "# Package Governance" in markdown_out.read_text(encoding="utf-8")

    monkeypatch.setattr(package_governance, "_head_sha", lambda _root: TARGET_SHA)
    assert package_governance.main(["--repo-root", str(tmp_path)]) == 0
    assert "# Package Governance" in capsys.readouterr().out
