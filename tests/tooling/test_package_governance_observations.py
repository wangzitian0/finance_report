from __future__ import annotations

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
from common.meta.base.package_contract import ACRecord, PackageContract
from common.testing.ac_proof import PROOF_ATTR, AcProof, ac_proof
from common.testing.executed_proof import record_executed_proof
from common.testing.package_governance_observations import (
    ObservationInputError,
    build_observation_bundle,
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
    governance_strength: str = "exact",
    oracle_kind: str = "deterministic_contract",
):
    def proof_test() -> None:
        pass

    meta = yaml.safe_load(
        f"{{proof_id: demo-proof, stage: github_ci.merge_authority, task_category: critical_behavioral, scope: behavioral, ci_tier: pr_ci, scenario_id: AC-demo.governance.1, oracle_kind: {oracle_kind}, governance_strength: {governance_strength}}}"
    )
    setattr(proof_test, PROOF_ATTR, AcProof(ac_ids=("AC-demo.governance.1",), **meta))

    item = SimpleNamespace(
        obj=proof_test, nodeid="tests/demo/test_live.py::test_live", user_properties=[]
    )
    report = SimpleNamespace(when="call", passed=True, wasxfail=None)
    env = {
        **os.environ,
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_SHA": TARGET_SHA,
        "GITHUB_RUN_ID": "10",
        "GITHUB_RUN_ATTEMPT": "1",
    }
    record = record_executed_proof(item, report, environ=env, occurred_at=NOW)
    assert record is not None
    return record, item.user_properties


def _write_executed_proof_junit(
    path: Path,
    *,
    governance_strength: str = "exact",
    oracle_kind: str = "deterministic_contract",
) -> None:
    _record, user_properties = _executed_proof_record(
        governance_strength=governance_strength, oracle_kind=oracle_kind
    )
    suite = ElementTree.Element("testsuite")
    case = ElementTree.SubElement(
        suite, "testcase", classname="tests.demo.test_live", name="test_live"
    )
    props = ElementTree.SubElement(case, "properties")
    for name, value in user_properties:
        ElementTree.SubElement(props, "property", name=name, value=value)
    ElementTree.ElementTree(suite).write(path, encoding="unicode")


def _contract(*, required_strength: str = "exact") -> PackageContract:
    ac = ACRecord.model_validate(
        yaml.safe_load(
            "{id: AC-demo.governance.1, statement: Exact., test: 'tests/demo/test_live.py::test_live', priority: P0, status: done, proof_kind: exact}"
        )
    )
    g = GovernanceGuarantee.model_validate(
        yaml.safe_load(
            f"{{id: real-input, statement: Real inputs., affected_acs: [AC-demo.governance.1], detector: demo-detector, target: zero findings, lock: ci.demo, proof: demo-proof, required_proof_strength: {required_strength}, enforcing_gate: ci.demo}}"
        )
    )
    return PackageContract.model_validate(
        yaml.safe_load(
            "{name: demo, klass: domain, tier: CODE-ONLY, depends_on: [], interface: [], events: [], invariants: []}"
        )
        | {
            "roadmap": [ac],
            "governance": [
                GovernanceInitiative(
                    id="live", title="Live", issue=ISSUE_URL, guarantees=[g]
                )
            ],
        }
    )


def _inputs() -> dict[str, object]:
    record, _ = _executed_proof_record()
    raw = yaml.safe_load(
        f"""
        detector_payloads:
          - source: package-detector
            target_sha: {TARGET_SHA}
            detectors: [{{guarantee_id: demo/real-input, current: 0, target: 0, findings: []}}]
        proof_payloads:
          - source: junit-executed-proof
            target_sha: {TARGET_SHA}
            proofs:
              - guarantee_id: demo/real-input
                proof_id: demo-proof
                result: passed
                strength: exact
                target_sha: {TARGET_SHA}
                occurred_at: "{NOW.isoformat()}"
                evidence_url: https://github.com/example/repo/actions/runs/10
                gate_id: ci.demo
                scenario_id: AC-demo.governance.1
                ac_ids: [AC-demo.governance.1]
                oracle_kind: deterministic_contract
                stage: github_ci.merge_authority
                task_category: critical_behavioral
                repository: {REPOSITORY}
                execution_id: "{EXECUTION_ID}"
                assertion_version: "{record.assertion.version}"
        workflow:
          jobs:
            demo: {{}}
            finish:
              needs: [demo]
              steps: [{{name: Check job status, run: "if [[ \\"${{{{ needs.demo.result }}}}\\" != \\"success\\" ]]; then\\n  exit 1\\nfi\\n"}}]
        rulesets:
          - target: branch
            enforcement: active
            conditions: {{ref_name: {{exclude: [], include: ["~DEFAULT_BRANCH"]}}}}
            rules: [{{type: required_status_checks, parameters: {{required_status_checks: [{{context: finish}}]}}}}]
        issue_payloads:
          - {{html_url: {ISSUE_URL}, state: open, updated_at: "{NOW.isoformat()}"}}
        """
    )
    raw["proof_payloads"][0]["proofs"][0]["trace_record"] = TraceRecordCodec.encode(
        record
    )
    return {
        "contracts": [_contract()],
        "target_sha": TARGET_SHA,
        "observed_at": NOW,
        **raw,
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
    assert (
        bundle["target_sha"] == TARGET_SHA
        and bundle["detectors"][0]["guarantee_id"] == "demo/real-input"
    )
    assert (
        bundle["proofs"][0]["source"] == "junit-executed-proof"
        and bundle["issues"][0]["state"] == "OPEN"
    )
    self_certified = _inputs()
    self_certified["detector_payloads"][0]["proofs"] = []
    with pytest.raises(ObservationInputError, match="detector payload.*proof"):
        build_observation_bundle(**self_certified)
    with pytest.raises(ObservationInputError, match="stale"):
        validate_observation_bundle_payload(
            bundle,
            expected_target_sha=TARGET_SHA,
            now=datetime(2026, 7, 27, 2, tzinfo=UTC),
            max_age_seconds=60,
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
    assert build_observation_bundle(**inputs)["enforcement"][0]["live_required"] is True
    inputs["rulesets"][0]["enforcement"] = "disabled"
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
    assert jobs["finish"]["needs"].count("ac-traceability") == 1
    step = next(
        s
        for s in jobs["ac-traceability"]["steps"]
        if "report_package_governance.py" in str(s.get("run", ""))
    )
    assert all(
        arg in step["run"]
        for arg in ("--observations", "--expected-target-sha", "${{ github.sha }}")
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
        "def detect_governance(*, repo_root):\n"
        "    return [{'guarantee_id': 'demo/real-input', 'current': 0, 'target': 0, 'findings': []}]\n",
        encoding="utf-8",
    )
    payloads = discover_package_detector_payloads(
        contracts=[_contract()], repo_root=tmp_path, target_sha=TARGET_SHA
    )
    assert payloads[0]["detectors"][0]["guarantee_id"] == "demo/real-input"
    provider.write_text(
        provider.read_text(encoding="utf-8").replace(
            "demo/real-input", "reconciliation/foreign"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ObservationInputError, match="owning package"):
        discover_package_detector_payloads(
            contracts=[_contract()], repo_root=tmp_path, target_sha=TARGET_SHA
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
        "from common.testing.ac_proof import PROOF_ATTR, AcProof, ac_proof\n"
        "@ac_proof('demo-proof', ac_ids=['AC-demo.governance.1'], ci_tier='pr_ci',\n"
        "          scenario_id='AC-demo.governance.1', oracle_kind='database_two_session',\n"
        "          governance_strength='concurrency')\n"
        "def test_live():\n    pass\n",
        encoding="utf-8",
    )
    profile = observation_adapter._governance_proof_profiles(
        contracts=[_contract(required_strength="concurrency")], repo_root=tmp_path
    )
    junit = tmp_path / "proof.xml"
    _write_executed_proof_junit(
        junit, governance_strength="concurrency", oracle_kind="database_two_session"
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
        proof_profiles=profile,
    )
    assert (
        payload["proofs"][0]["strength"] == "concurrency"
        and payload["proofs"][0]["gate_id"] == "ci.demo"
    )
