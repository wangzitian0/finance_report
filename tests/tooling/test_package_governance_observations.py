from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest
import yaml

import common.testing.package_governance_observations as observation_adapter

from common.audit.extension import TraceRecordCodec
from common.meta.base.governance_control import (
    GovernanceGuarantee,
    GovernanceInitiative,
)
from common.testing.ac_proof import PROOF_ATTR, AcProof, ac_proof
from common.testing.executed_proof import record_executed_proof
from common.meta.base.package_contract import ACRecord, PackageContract
from common.testing.package_governance_observations import (
    ObservationInputError,
    build_observation_bundle,
    collect_github_snapshot,
    discover_package_detector_payloads,
    junit_proof_payload,
    validate_observation_bundle_payload,
)

TARGET_SHA = "a" * 40
NOW = datetime(2026, 7, 27, tzinfo=UTC)
ISSUE_URL = "https://github.com/example/repo/issues/1"
REPOSITORY = "example/repo"
EXECUTION_ID = "10.1"


def _executed_proof_record(
    *,
    proof_id: str = "demo-proof",
    scenario_id: str = "AC-demo.governance.1",
    target_sha: str = TARGET_SHA,
    governance_strength: str = "exact",
    oracle_kind: str = "deterministic_contract",
):
    def proof_test() -> None:
        pass

    setattr(
        proof_test,
        PROOF_ATTR,
        AcProof(
            proof_id=proof_id,
            ac_ids=("AC-demo.governance.1",),
            stage="github_ci.merge_authority",
            task_category="critical_behavioral",
            scope="behavioral",
            ci_tier="pr_ci",
            scenario_id=scenario_id,
            oracle_kind=oracle_kind,
            governance_strength=governance_strength,
        ),
    )
    item = SimpleNamespace(
        obj=proof_test,
        nodeid="tests/demo/test_live.py::test_live",
        user_properties=[],
    )
    report = SimpleNamespace(when="call", passed=True, wasxfail=None)
    record = record_executed_proof(
        item,
        report,
        environ={
            **os.environ,
            "GITHUB_ACTIONS": "true",
            "GITHUB_REPOSITORY": REPOSITORY,
            "GITHUB_SHA": target_sha,
            "GITHUB_RUN_ID": "10",
            "GITHUB_RUN_ATTEMPT": "1",
        },
        occurred_at=NOW,
    )
    assert record is not None
    return record, item.user_properties


def _write_executed_proof_junit(
    path: Path,
    *,
    proof_id: str = "demo-proof",
    scenario_id: str = "AC-demo.governance.1",
    target_sha: str = TARGET_SHA,
    governance_strength: str = "exact",
    oracle_kind: str = "deterministic_contract",
) -> None:
    _record, user_properties = _executed_proof_record(
        proof_id=proof_id,
        scenario_id=scenario_id,
        target_sha=target_sha,
        governance_strength=governance_strength,
        oracle_kind=oracle_kind,
    )
    suite = ElementTree.Element("testsuite")
    case = ElementTree.SubElement(
        suite,
        "testcase",
        classname="tests.demo.test_live",
        name="test_live",
    )
    properties = ElementTree.SubElement(case, "properties")
    for name, value in user_properties:
        ElementTree.SubElement(properties, "property", name=name, value=value)
    ElementTree.ElementTree(suite).write(path, encoding="unicode")


def _contract(*, required_strength: str = "exact") -> PackageContract:
    ac = ACRecord(
        id="AC-demo.governance.1",
        statement="The live observation is exact.",
        test="tests/demo/test_live.py::test_live",
        priority="P0",
        status="done",
        proof_kind="exact",
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
                id="live",
                title="Live observation",
                issue=ISSUE_URL,
                guarantees=[
                    GovernanceGuarantee(
                        id="real-input",
                        statement="Only real inputs can satisfy governance.",
                        affected_acs=[ac.id],
                        detector="demo-detector",
                        target="zero findings",
                        lock="ci.demo",
                        proof="demo-proof",
                        required_proof_strength=required_strength,
                        enforcing_gate="ci.demo",
                    )
                ],
            )
        ],
    )


def _proof_profiles(
    *, strength: str = "exact", oracle_kind: str = "deterministic_contract"
) -> dict[str, dict[str, object]]:
    return {
        "demo/real-input": {
            "ac_ids": ["AC-demo.governance.1"],
            "oracle_kind": oracle_kind,
            "scenario_id": "AC-demo.governance.1",
            "stage": "github_ci.merge_authority",
            "task_category": "critical_behavioral",
            "governance_strength": strength,
        }
    }


def _inputs() -> dict[str, object]:
    record, _properties = _executed_proof_record()
    return {
        "contracts": [_contract()],
        "target_sha": TARGET_SHA,
        "observed_at": NOW,
        "detector_payloads": [
            {
                "source": "package-detector",
                "target_sha": TARGET_SHA,
                "detectors": [
                    {
                        "guarantee_id": "demo/real-input",
                        "current": 0,
                        "target": 0,
                        "findings": [],
                    }
                ],
            }
        ],
        "proof_payloads": [
            {
                "source": "junit-executed-proof",
                "target_sha": TARGET_SHA,
                "proofs": [
                    {
                        "guarantee_id": "demo/real-input",
                        "proof_id": "demo-proof",
                        "result": "passed",
                        "strength": "exact",
                        "target_sha": TARGET_SHA,
                        "occurred_at": NOW.isoformat(),
                        "evidence_url": "https://github.com/example/repo/actions/runs/10",
                        "gate_id": "ci.demo",
                        "scenario_id": "AC-demo.governance.1",
                        "ac_ids": ["AC-demo.governance.1"],
                        "oracle_kind": "deterministic_contract",
                        "stage": "github_ci.merge_authority",
                        "task_category": "critical_behavioral",
                        "repository": REPOSITORY,
                        "execution_id": EXECUTION_ID,
                        "assertion_version": record.assertion.version,
                        "trace_record": TraceRecordCodec.encode(record),
                    }
                ],
            }
        ],
        "gate_inventory": {
            "branch_required_status_contexts": ["finish"],
            "gates": [
                {
                    "id": "ci.demo",
                    "job": "demo",
                    "required_by_finish": True,
                    "blocks_workflow": True,
                }
            ],
        },
        "workflow": {
            "jobs": {
                "finish": {
                    "needs": ["demo"],
                    "steps": [
                        {
                            "name": "Check job status",
                            "run": (
                                'if [[ "${{ needs.demo.result }}" != "success" ]]; then\n'
                                "  exit 1\n"
                                "fi\n"
                            ),
                        }
                    ],
                }
            }
        },
        "rulesets": [
            {
                "target": "branch",
                "enforcement": "active",
                "conditions": {
                    "ref_name": {"exclude": [], "include": ["~DEFAULT_BRANCH"]}
                },
                "rules": [
                    {
                        "type": "required_status_checks",
                        "parameters": {
                            "required_status_checks": [{"context": "finish"}]
                        },
                    }
                ],
            }
        ],
        "issue_payloads": [
            {
                "html_url": ISSUE_URL,
                "state": "open",
                "updated_at": NOW.isoformat(),
            }
        ],
    }


@ac_proof(
    "package-governance-observation-bundle",
    ac_ids=["AC-testing.governance.23"],
    ci_tier="pr_ci",
    scenario_id="AC-testing.governance.23",
    oracle_kind="deterministic_contract",
)
def test_AC_testing_governance_23_builds_only_from_real_inputs() -> None:
    """AC-testing.governance.23: current independent inputs form one bundle."""
    bundle = build_observation_bundle(**_inputs())

    assert bundle["target_sha"] == TARGET_SHA
    assert bundle["detectors"][0]["guarantee_id"] == "demo/real-input"
    assert bundle["proofs"][0]["source"] == "junit-executed-proof"
    assert bundle["enforcement"] == [
        {
            "gate_id": "ci.demo",
            "declared_blocking": True,
            "workflow_required": True,
            "live_required": True,
            "required_context": "finish",
            "observed_at": NOW.isoformat(),
        }
    ]
    assert bundle["issues"][0]["state"] == "OPEN"

    self_certified = _inputs()
    self_certified["detector_payloads"][0]["proofs"] = []
    with pytest.raises(ObservationInputError, match="detector payload.*proof"):
        build_observation_bundle(**self_certified)

    stale = _inputs()
    stale["proof_payloads"][0]["target_sha"] = "b" * 40
    with pytest.raises(ObservationInputError, match="target SHA"):
        build_observation_bundle(**stale)

    with pytest.raises(ObservationInputError, match="stale"):
        validate_observation_bundle_payload(
            bundle,
            expected_target_sha=TARGET_SHA,
            now=datetime(2026, 7, 27, 2, tzinfo=UTC),
            max_age_seconds=60,
        )


def test_junit_proof_is_bound_to_the_declared_test_and_target_sha(
    tmp_path: Path,
) -> None:
    """AC-testing.governance.23: only an executed declared testcase supplies proof."""
    junit = tmp_path / "tooling.xml"
    junit.write_text(
        '<testsuite><testcase classname="tests.demo.test_live" name="test_live"/></testsuite>',
        encoding="utf-8",
    )
    with pytest.raises(ObservationInputError, match="canonical executed proof"):
        junit_proof_payload(
            contracts=[_contract()],
            issue_states={ISSUE_URL: "open"},
            junit_lanes={"ci.demo": [junit]},
            target_sha=TARGET_SHA,
            observed_at=NOW,
            evidence_url="https://github.com/example/repo/actions/runs/10",
            repository=REPOSITORY,
            execution_id=EXECUTION_ID,
        )

    _write_executed_proof_junit(junit)
    payload = junit_proof_payload(
        contracts=[_contract()],
        issue_states={ISSUE_URL: "open"},
        junit_lanes={"ci.demo": [junit]},
        target_sha=TARGET_SHA,
        observed_at=NOW,
        evidence_url="https://github.com/example/repo/actions/runs/10",
        repository=REPOSITORY,
        execution_id=EXECUTION_ID,
    )
    assert payload["source"] == "junit-executed-proof"
    assert payload["proofs"][0]["result"] == "passed"

    junit.write_text(
        '<testsuite><testcase classname="tests.demo.test_live" name="other"/></testsuite>',
        encoding="utf-8",
    )
    with pytest.raises(
        ObservationInputError, match="canonical executed proof is missing"
    ):
        junit_proof_payload(
            contracts=[_contract()],
            issue_states={ISSUE_URL: "open"},
            junit_lanes={"ci.demo": [junit]},
            target_sha=TARGET_SHA,
            observed_at=NOW,
            evidence_url="evidence",
            repository=REPOSITORY,
            execution_id=EXECUTION_ID,
        )

    _write_executed_proof_junit(junit, target_sha="b" * 40)
    with pytest.raises(ObservationInputError, match="canonical executed proof"):
        junit_proof_payload(
            contracts=[_contract()],
            issue_states={ISSUE_URL: "open"},
            junit_lanes={"ci.demo": [junit]},
            target_sha=TARGET_SHA,
            observed_at=NOW,
            evidence_url="evidence",
            repository=REPOSITORY,
            execution_id=EXECUTION_ID,
        )

    assert (
        junit_proof_payload(
            contracts=[_contract()],
            issue_states={ISSUE_URL: "closed"},
            junit_lanes={"ci.demo": [junit]},
            target_sha=TARGET_SHA,
            observed_at=NOW,
            evidence_url="evidence",
            repository=REPOSITORY,
            execution_id=EXECUTION_ID,
        )["proofs"]
        == []
    )

    junit.write_text("not xml", encoding="utf-8")
    with pytest.raises(ObservationInputError, match="invalid JUnit"):
        junit_proof_payload(
            contracts=[_contract()],
            issue_states={ISSUE_URL: "open"},
            junit_lanes={"ci.demo": [junit]},
            target_sha=TARGET_SHA,
            observed_at=NOW,
            evidence_url="evidence",
            repository=REPOSITORY,
            execution_id=EXECUTION_ID,
        )

    contract = _contract()
    strong = (
        contract.governance[0]
        .guarantees[0]
        .model_copy(update={"required_proof_strength": "concurrency"})
    )
    strong_contract = contract.model_copy(
        update={
            "governance": [
                contract.governance[0].model_copy(update={"guarantees": [strong]})
            ]
        }
    )
    _write_executed_proof_junit(junit)
    with pytest.raises(ObservationInputError, match="strength profile"):
        junit_proof_payload(
            contracts=[strong_contract],
            issue_states={ISSUE_URL: "open"},
            junit_lanes={"ci.demo": [junit]},
            target_sha=TARGET_SHA,
            observed_at=NOW,
            evidence_url="evidence",
            repository=REPOSITORY,
            execution_id=EXECUTION_ID,
        )


@ac_proof(
    "package-governance-live-enforcement",
    ac_ids=["AC-testing.governance.24"],
    ci_tier="pr_ci",
    scenario_id="AC-testing.governance.24",
    oracle_kind="deterministic_contract",
)
def test_AC_testing_governance_24_derives_live_enforcement_from_raw_facts() -> None:
    """AC-testing.governance.24: live enforcement is derived, never supplied."""
    inputs = _inputs()
    bundle = build_observation_bundle(**inputs)
    assert bundle["enforcement"][0]["live_required"] is True

    inputs["rulesets"][0]["enforcement"] = "disabled"
    with pytest.raises(ObservationInputError, match="required status contexts"):
        build_observation_bundle(**inputs)

    wrong_ref = _inputs()
    wrong_ref["rulesets"][0]["target"] = "tag"
    with pytest.raises(ObservationInputError, match="required status contexts"):
        build_observation_bundle(**wrong_ref)

    ignored = _inputs()
    ignored["workflow"]["jobs"]["finish"]["steps"] = [
        {"run": 'echo "${{ needs.demo.result }}"'}
    ]
    with pytest.raises(ObservationInputError, match="does not block"):
        build_observation_bundle(**ignored)

    for bypass in (
        'if [[ "${{ needs.demo.result }}" != "success" ]]; then\n  exit 1 || true\nfi\n',
        'if [[ "${{ needs.demo.result }}" != "success" ]]; then\n  # exit 1\nfi\n',
        (
            'if [[ "${{ needs.demo.result }}" != "success" ]]; then\n'
            "  if false; then\n    exit 1\n  fi\n"
            "fi\n"
        ),
    ):
        bypassed = _inputs()
        bypassed["workflow"]["jobs"]["finish"]["steps"] = [{"run": bypass}]
        with pytest.raises(ObservationInputError, match="does not block"):
            build_observation_bundle(**bypassed)


def test_control_detector_never_synthesizes_green_for_missing_raw_facts() -> None:
    """AC-testing.governance.23: proofs cannot reverse-certify their detector."""
    contract = _contract().model_copy(update={"name": "testing"})
    workflow = _inputs()["workflow"]
    workflow["jobs"]["finish"]["steps"][0]["run"] = (
        'if [[ "${{ needs.demo.result }}" != "success" ]]; then\n  exit 1 || true\nfi\n'
    )
    payload = observation_adapter._control_detector_payload(
        contracts=[contract],
        open_issue_urls={ISSUE_URL},
        existing_payloads=[],
        target_sha=TARGET_SHA,
        gate_inventory=_inputs()["gate_inventory"],
        workflow=workflow,
        rulesets=_inputs()["rulesets"],
        issue_payloads=_inputs()["issue_payloads"],
    )

    assert payload["detectors"][0]["current"] > 0
    assert "gate-failure-not-blocked-by-finish" in payload["detectors"][0]["findings"]


def test_mixed_parameterized_skip_cannot_reuse_a_passing_trace_record(
    tmp_path: Path,
) -> None:
    """AC-testing.governance.23: every case sharing the declared test must pass."""
    junit = tmp_path / "mixed.xml"
    _write_executed_proof_junit(junit)
    tree = ElementTree.parse(junit)
    passed = next(tree.iter("testcase"))
    passed.set("name", "test_live[passed]")
    skipped = ElementTree.SubElement(
        tree.getroot(),
        "testcase",
        classname="tests.demo.test_live",
        name="test_live[skipped]",
    )
    ElementTree.SubElement(skipped, "skipped")
    tree.write(junit, encoding="unicode")

    with pytest.raises(ObservationInputError, match="testcase did not pass"):
        junit_proof_payload(
            contracts=[_contract()],
            issue_states={ISSUE_URL: "open"},
            junit_lanes={"ci.demo": [junit]},
            target_sha=TARGET_SHA,
            observed_at=NOW,
            evidence_url="evidence",
            repository=REPOSITORY,
            execution_id=EXECUTION_ID,
        )


@ac_proof(
    "package-governance-detector-discovery",
    ac_ids=["AC-testing.governance.26"],
    ci_tier="pr_ci",
    scenario_id="AC-testing.governance.26",
    oracle_kind="deterministic_contract",
)
def test_AC_testing_governance_26_discovers_only_package_owned_detectors(
    tmp_path: Path,
) -> None:
    """AC-testing.governance.26: package providers expose detector facts only."""
    provider = tmp_path / "common/demo/extension/governance_detector.py"
    provider.parent.mkdir(parents=True)
    provider.write_text(
        """
def detect_governance(*, repo_root):
    assert repo_root.name
    return [{
        "guarantee_id": "demo/real-input",
        "current": 0,
        "target": 0,
        "findings": [],
    }]
""",
        encoding="utf-8",
    )

    payloads = discover_package_detector_payloads(
        contracts=[_contract()],
        repo_root=tmp_path,
        target_sha=TARGET_SHA,
    )

    assert payloads == [
        {
            "source": "package-detector",
            "target_sha": TARGET_SHA,
            "detectors": [
                {
                    "guarantee_id": "demo/real-input",
                    "current": 0,
                    "target": 0,
                    "findings": [],
                }
            ],
        }
    ]

    provider.write_text(
        provider.read_text(encoding="utf-8").replace(
            "demo/real-input", "reconciliation/foreign"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ObservationInputError, match="owning package"):
        discover_package_detector_payloads(
            contracts=[_contract()],
            repo_root=tmp_path,
            target_sha=TARGET_SHA,
        )


@pytest.mark.parametrize(
    ("provider_body", "message"),
    [
        (
            "raise RuntimeError('detector failed')",
            "provider failed",
        ),
        (
            "return {'guarantee_id': 'demo/real-input'}",
            "must return a list",
        ),
        (
            """return [{
                'guarantee_id': 'demo/real-input',
                'current': 0,
                'target': 0,
                'findings': [],
                'proofs': [{'result': 'passed'}],
            }]""",
            "observation is invalid",
        ),
    ],
)
def test_AC_testing_governance_26_provider_fails_closed_on_invalid_output(
    tmp_path: Path,
    provider_body: str,
    message: str,
) -> None:
    """AC-testing.governance.26: providers cannot smuggle proof-bearing data."""
    provider = tmp_path / "common/demo/extension/governance_detector.py"
    provider.parent.mkdir(parents=True)
    provider.write_text(
        "def detect_governance(*, repo_root):\n    "
        + provider_body.replace("\n", "\n    ")
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ObservationInputError, match=message):
        discover_package_detector_payloads(
            contracts=[_contract()],
            repo_root=tmp_path,
            target_sha=TARGET_SHA,
        )


def test_open_guarantee_requires_a_current_issue_observation(tmp_path: Path) -> None:
    """AC-testing.governance.26: absent issue state cannot become current proof."""
    junit = tmp_path / "proof.xml"
    _write_executed_proof_junit(junit)

    with pytest.raises(ObservationInputError, match="issue state is missing"):
        junit_proof_payload(
            contracts=[_contract()],
            issue_states={},
            junit_lanes={"ci.demo": [junit]},
            target_sha=TARGET_SHA,
            observed_at=NOW,
            evidence_url="evidence",
            repository=REPOSITORY,
            execution_id=EXECUTION_ID,
        )


@ac_proof(
    "package-governance-historical-proof-refresh",
    ac_ids=["AC-testing.governance.27"],
    ci_tier="pr_ci",
    scenario_id="AC-testing.governance.27",
    oracle_kind="deterministic_contract",
)
def test_AC_testing_governance_27_refreshes_closed_initiative_proof(
    tmp_path: Path,
) -> None:
    """AC-testing.governance.27: closure, strength, and lane stay independent."""
    proof_file = tmp_path / "tests/demo/test_live.py"
    proof_file.parent.mkdir(parents=True)
    proof_file.write_text(
        """
from common.testing.ac_proof import ac_proof

@ac_proof(
    "demo-proof",
    ac_ids=["AC-demo.governance.1"],
    ci_tier="pr_ci",
    scenario_id="AC-demo.governance.1",
    oracle_kind="database_two_session",
    governance_strength="concurrency",
)
def test_live():
    pass
""",
        encoding="utf-8",
    )
    concurrency_profile = observation_adapter._governance_proof_profiles(
        contracts=[_contract(required_strength="concurrency")],
        repo_root=tmp_path,
    )
    assert concurrency_profile["demo/real-input"]["oracle_kind"] == (
        "database_two_session"
    )
    proof_file.write_text(
        proof_file.read_text(encoding="utf-8").replace(
            'governance_strength="concurrency"', 'governance_strength="exact"'
        ),
        encoding="utf-8",
    )
    with pytest.raises(ObservationInputError, match="profile disagrees"):
        observation_adapter._governance_proof_profiles(
            contracts=[_contract(required_strength="concurrency")],
            repo_root=tmp_path,
        )

    junit = tmp_path / "proof.xml"
    _write_executed_proof_junit(
        junit,
        governance_strength="concurrency",
        oracle_kind="database_two_session",
    )
    payload = junit_proof_payload(
        contracts=[_contract(required_strength="concurrency")],
        issue_states={ISSUE_URL: "closed"},
        junit_lanes={"ci.demo": [junit]},
        target_sha=TARGET_SHA,
        observed_at=NOW,
        evidence_url="evidence",
        repository=REPOSITORY,
        execution_id=EXECUTION_ID,
        proof_profiles=concurrency_profile,
    )

    assert payload["proofs"][0]["strength"] == "concurrency"
    assert payload["proofs"][0]["gate_id"] == "ci.demo"

    assert (
        junit_proof_payload(
            contracts=[_contract(required_strength="concurrency")],
            issue_states={ISSUE_URL: "closed"},
            junit_lanes={"ci.other": [junit]},
            target_sha=TARGET_SHA,
            observed_at=NOW,
            evidence_url="evidence",
            repository=REPOSITORY,
            execution_id=EXECUTION_ID,
            proof_profiles=concurrency_profile,
        )["proofs"]
        == []
    )
    with pytest.raises(ObservationInputError, match="declared gate lane"):
        junit_proof_payload(
            contracts=[_contract(required_strength="concurrency")],
            issue_states={ISSUE_URL: "open"},
            junit_lanes={"ci.other": [junit]},
            target_sha=TARGET_SHA,
            observed_at=NOW,
            evidence_url="evidence",
            repository=REPOSITORY,
            execution_id=EXECUTION_ID,
            proof_profiles=concurrency_profile,
        )

    _write_executed_proof_junit(junit, governance_strength="exact")
    with pytest.raises(ObservationInputError, match="strength profile"):
        junit_proof_payload(
            contracts=[_contract(required_strength="concurrency")],
            issue_states={ISSUE_URL: "open"},
            junit_lanes={"ci.demo": [junit]},
            target_sha=TARGET_SHA,
            observed_at=NOW,
            evidence_url="evidence",
            repository=REPOSITORY,
            execution_id=EXECUTION_ID,
            proof_profiles=concurrency_profile,
        )


def test_github_collector_retains_only_current_redacted_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-testing.governance.24: authenticated collection does not archive issue prose."""
    responses = {
        "repos/example/repo/rulesets": [{"id": 7}],
        "repos/example/repo/rulesets/7": {
            "id": 7,
            "name": "main",
            "target": "branch",
            "enforcement": "active",
            "updated_at": NOW.isoformat(),
            "conditions": {"ref_name": {"exclude": [], "include": ["~DEFAULT_BRANCH"]}},
            "rules": [],
            "bypass_actors": [{"actor_id": 1}],
        },
        "repos/example/repo/issues/1": {
            "html_url": ISSUE_URL,
            "state": "open",
            "updated_at": NOW.isoformat(),
            "body": "must not enter the evidence artifact",
        },
    }

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(stdout=json.dumps(responses[command[-1]]))

    monkeypatch.setattr(
        "common.testing.package_governance_observations.subprocess.run", fake_run
    )
    snapshot = collect_github_snapshot(
        repository="example/repo", issue_urls={ISSUE_URL}
    )

    assert snapshot["issues"] == [
        {"html_url": ISSUE_URL, "state": "open", "updated_at": NOW.isoformat()}
    ]
    assert set(snapshot["rulesets"][0]) == {
        "id",
        "name",
        "enforcement",
        "target",
        "conditions",
        "updated_at",
        "rules",
    }

    monkeypatch.setattr(
        "common.testing.package_governance_observations.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="{}"),
    )
    with pytest.raises(ObservationInputError, match="ruleset list"):
        collect_github_snapshot(repository="example/repo", issue_urls=set())

    monkeypatch.setattr(
        "common.testing.package_governance_observations.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="[]"),
    )
    with pytest.raises(ObservationInputError, match="outside"):
        collect_github_snapshot(
            repository="example/repo",
            issue_urls={"https://github.com/other/repo/issues/1"},
        )
    with pytest.raises(ObservationInputError, match="malformed"):
        collect_github_snapshot(
            repository="example/repo",
            issue_urls={"https://github.com/example/repo/issues/not-a-number"},
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda data: data["detector_payloads"][0].update(source="authored"),
            "untrusted source",
        ),
        (
            lambda data: data["detector_payloads"][0].update(target_sha="b" * 40),
            "does not match bundle",
        ),
        (
            lambda data: data["detector_payloads"][0]["detectors"][0].update(
                guarantee_id="demo/unknown"
            ),
            "unknown guarantee",
        ),
        (
            lambda data: data["detector_payloads"][0]["detectors"][0].update(
                proofs=[{"result": "passed"}]
            ),
            "invalid observation",
        ),
        (
            lambda data: data["proof_payloads"][0].update(source="detector"),
            "independent",
        ),
        (
            lambda data: data["proof_payloads"][0]["proofs"][0].update(
                target_sha="b" * 40
            ),
            "does not match bundle",
        ),
        (
            lambda data: data["proof_payloads"][0]["proofs"][0].update(
                guarantee_id="demo/unknown"
            ),
            "unknown guarantee",
        ),
        (
            lambda data: data["issue_payloads"][0].update(
                html_url="https://github.com/example/repo/issues/2"
            ),
            "unknown initiative",
        ),
        (lambda data: data["issue_payloads"][0].update(state="draft"), "unknown state"),
    ],
)
def test_bundle_rejects_untrusted_or_foreign_inputs(mutation, message: str) -> None:
    """AC-testing.governance.23: input provenance and ownership fail closed."""
    inputs = _inputs()
    mutation(inputs)
    with pytest.raises(ObservationInputError, match=message):
        build_observation_bundle(**inputs)


@pytest.mark.parametrize(
    "collection",
    ["detector_payloads", "proof_payloads", "issue_payloads"],
)
def test_bundle_rejects_duplicate_observations(collection: str) -> None:
    """AC-testing.governance.23: repeated evidence cannot overwrite truth."""
    inputs = _inputs()
    inputs[collection].append(inputs[collection][0])

    with pytest.raises(ObservationInputError, match="duplicate"):
        build_observation_bundle(**inputs)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda bundle: bundle.update(schema_version=1), "schema_version"),
        (lambda bundle: bundle.update(target_sha="b" * 40), "does not match"),
        (lambda bundle: bundle.update(observed_at="invalid"), "invalid observed_at"),
        (
            lambda bundle: bundle.update(observed_at="2026-07-27T00:00:00"),
            "timezone-aware",
        ),
        (
            lambda bundle: bundle["proofs"][0].update(source="detector"),
            "JUnit provenance",
        ),
        (
            lambda bundle: bundle["proofs"][0].pop("trace_record"),
            "canonical TraceRecord",
        ),
        (
            lambda bundle: bundle["proofs"][0].update(trace_record="{}"),
            "canonical TraceRecord",
        ),
        (
            lambda bundle: bundle["proofs"][0].update(repository="other/repo"),
            "does not match its coordinates",
        ),
        (
            lambda bundle: bundle["proofs"][0].update(strength="concurrency"),
            "strength profile",
        ),
        (
            lambda bundle: bundle["proofs"][0].update(target_sha="b" * 40),
            "does not match expected",
        ),
        (
            lambda bundle: bundle["detectors"].append(bundle["detectors"][0]),
            "duplicate detector",
        ),
        (
            lambda bundle: bundle["proofs"].append(bundle["proofs"][0]),
            "duplicate proof",
        ),
        (
            lambda bundle: bundle["issues"].append(bundle["issues"][0]),
            "duplicate issue",
        ),
    ],
)
def test_bundle_validation_rejects_forged_coordinates(mutation, message: str) -> None:
    """AC-testing.governance.23: a serialized bundle cannot bypass validation."""
    bundle = build_observation_bundle(**_inputs())
    mutation(bundle)
    with pytest.raises(ObservationInputError, match=message):
        validate_observation_bundle_payload(
            bundle,
            expected_target_sha=TARGET_SHA,
            now=NOW,
        )


def test_bundle_accepts_scalar_finish_needs_and_ignores_unrelated_rules() -> None:
    """AC-testing.governance.24: raw workflow/ruleset parsing is exact but tolerant."""
    inputs = _inputs()
    inputs["workflow"]["jobs"]["finish"]["needs"] = "demo"
    inputs["rulesets"][0]["rules"].insert(0, {"type": "deletion"})
    assert build_observation_bundle(**inputs)["enforcement"][0]["workflow_required"]

    with pytest.raises(ObservationInputError, match="exact target SHA"):
        validate_observation_bundle_payload(
            build_observation_bundle(**inputs),
            expected_target_sha="short",
            now=NOW,
        )


def test_payload_reader_rejects_invalid_or_non_object_json(tmp_path: Path) -> None:
    """AC-testing.governance.23: serialized producer artifacts fail closed."""
    payload = tmp_path / "payload.json"
    payload.write_text("not json", encoding="utf-8")
    with pytest.raises(ObservationInputError, match="invalid observation payload"):
        observation_adapter._read_payload(payload)
    payload.write_text("[]", encoding="utf-8")
    with pytest.raises(ObservationInputError, match="not an object"):
        observation_adapter._read_payload(payload)

    inputs = _inputs()
    inputs["gate_inventory"]["gates"][0]["required_by_finish"] = False
    with pytest.raises(ObservationInputError, match="finish reachability disagree"):
        build_observation_bundle(**inputs)

    inputs = _inputs()
    inputs["rulesets"][0]["rules"][0]["parameters"]["required_status_checks"] = []
    with pytest.raises(ObservationInputError, match="required status contexts"):
        build_observation_bundle(**inputs)


@ac_proof(
    "package-governance-existing-finish-policy",
    ac_ids=["AC-testing.governance.25"],
    ci_tier="pr_ci",
    scenario_id="AC-testing.governance.25",
    oracle_kind="deterministic_contract",
)
def test_AC_testing_governance_25_existing_finish_path_blocks_false_green() -> None:
    """AC-testing.governance.25: the existing finish path consumes the exact bundle."""
    workflow = yaml.safe_load(
        (Path(__file__).parents[2] / ".github/workflows/ci.yml").read_text(
            encoding="utf-8"
        )
    )
    jobs = workflow["jobs"]
    finish_needs = jobs["finish"]["needs"]
    assert finish_needs.count("ac-traceability") == 1

    package_step = next(
        step
        for step in jobs["ac-traceability"]["steps"]
        if "report_package_governance.py" in str(step.get("run", ""))
    )
    command = package_step["run"]
    required_arguments = (
        "--observations",
        "--expected-target-sha",
        "${{ github.sha }}",
    )
    assert all(command.count(argument) >= 1 for argument in required_arguments)

    tooling_conftest = (
        Path(__file__).parents[2] / "tests/tooling/conftest.py"
    ).read_text(encoding="utf-8")
    assert (
        'pytest_plugins = ("common.testing.executed_proof_plugin",)' in tooling_conftest
    )
    tooling_command = next(
        str(step.get("run", ""))
        for step in jobs["tooling-coverage"]["steps"]
        if "pytest tests/tooling/" in str(step.get("run", ""))
    )
    assert "-p common.testing.executed_proof_plugin" not in tooling_command


def test_observation_adapter_main_writes_live_bundle_and_redacted_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-testing.governance.25: the workflow command has an executable adapter."""
    junit_root = tmp_path / "junit"
    junit_root.mkdir()
    tooling_junit = junit_root / "tooling/tooling-junit.xml"
    tooling_junit.parent.mkdir()
    _write_executed_proof_junit(tooling_junit)
    inventory = tmp_path / "inventory.yaml"
    inventory.write_text(yaml.safe_dump(_inputs()["gate_inventory"]), encoding="utf-8")
    workflow_path = tmp_path / ".github/workflows/ci.yml"
    workflow_path.parent.mkdir(parents=True)
    workflow_path.write_text(yaml.safe_dump(_inputs()["workflow"]), encoding="utf-8")
    github = {
        "rulesets": _inputs()["rulesets"],
        "issues": _inputs()["issue_payloads"],
    }
    monkeypatch.setattr(
        observation_adapter,
        "discover_packages",
        lambda _root: [
            SimpleNamespace(contract=_contract().model_copy(update={"name": "testing"}))
        ],
    )
    monkeypatch.setattr(
        observation_adapter,
        "collect_github_snapshot",
        lambda **_kwargs: github,
    )

    def demo_junit_lanes(root: Path) -> dict[str, list[Path]]:
        paths = sorted(root.rglob("*.xml"))
        if not paths:
            raise ObservationInputError("no JUnit evidence was supplied")
        return {"ci.demo": paths}

    monkeypatch.setattr(observation_adapter, "_junit_lanes", demo_junit_lanes)
    monkeypatch.setattr(
        observation_adapter,
        "_governance_proof_profiles",
        lambda **_kwargs: _proof_profiles(),
    )
    monkeypatch.setenv("GITHUB_RUN_ID", "10")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    output = tmp_path / "bundle.json"
    raw = tmp_path / "github.json"

    assert (
        observation_adapter.main(
            [
                "--repo-root",
                str(tmp_path),
                "--repository",
                "example/repo",
                "--target-sha",
                TARGET_SHA,
                "--junit-root",
                str(junit_root),
                "--gate-inventory",
                str(inventory),
                "--output",
                str(output),
                "--raw-github-out",
                str(raw),
            ]
        )
        == 0
    )
    bundle = json.loads(output.read_text(encoding="utf-8"))
    assert bundle["target_sha"] == TARGET_SHA
    assert bundle["detectors"][0]["guarantee_id"] == "testing/real-input"
    assert json.loads(raw.read_text(encoding="utf-8")) == github

    empty = tmp_path / "empty"
    empty.mkdir()
    assert (
        observation_adapter.main(
            [
                "--repo-root",
                str(tmp_path),
                "--repository",
                "example/repo",
                "--target-sha",
                TARGET_SHA,
                "--junit-root",
                str(empty),
                "--gate-inventory",
                str(inventory),
                "--output",
                str(output),
                "--raw-github-out",
                str(raw),
            ]
        )
        == 1
    )


def test_AC_testing_governance_27_classifies_actual_junit_artifact_lanes(
    tmp_path: Path,
) -> None:
    """AC-testing.governance.27: proof lanes come from CI artifact layout."""
    junit_root = tmp_path / "governance-inputs/junit"
    paths = {
        "ci.backend": [
            junit_root
            / "backend/backend-shard-1-test-context/test-results/backend-shard-1.xml",
            junit_root
            / "backend/backend-shard-5-test-context/test-results/backend-shard-5.xml",
        ],
        "ci.backend_integration": [
            junit_root
            / "backend/backend-integration-test-context/backend-integration.xml"
        ],
        "ci.backend_e2e_tier1": [
            junit_root / "backend/backend-tier1-e2e-test-context/backend-tier1-e2e.xml"
        ],
        "ci.frontend_vitest": [junit_root / "frontend/test-results/vitest-junit.xml"],
        "ci.tooling_coverage": [junit_root / "tooling/tooling-junit.xml"],
    }
    for lane_paths in paths.values():
        for path in lane_paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("<testsuite />", encoding="utf-8")

    assert observation_adapter._junit_lanes(junit_root) == paths

    unknown = junit_root / "unknown/unowned.xml"
    unknown.parent.mkdir()
    unknown.write_text("<testsuite />", encoding="utf-8")
    with pytest.raises(ObservationInputError, match="JUnit.*lane"):
        observation_adapter._junit_lanes(junit_root)
