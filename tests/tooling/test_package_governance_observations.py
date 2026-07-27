from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import common.testing.package_governance_observations as observation_adapter

from common.meta.base.governance_control import (
    GovernanceGuarantee,
    GovernanceInitiative,
)
from common.meta.base.package_contract import ACRecord, PackageContract
from common.testing.package_governance_observations import (
    ObservationInputError,
    build_observation_bundle,
    collect_github_snapshot,
    junit_proof_payload,
    validate_observation_bundle_payload,
)

TARGET_SHA = "a" * 40
NOW = datetime(2026, 7, 27, tzinfo=UTC)
ISSUE_URL = "https://github.com/example/repo/issues/1"


def _contract() -> PackageContract:
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
                        required_proof_strength="exact",
                        enforcing_gate="ci.demo",
                    )
                ],
            )
        ],
    )


def _inputs() -> dict[str, object]:
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
        "workflow": {"jobs": {"finish": {"needs": ["demo"]}}},
        "rulesets": [
            {
                "enforcement": "active",
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


def test_junit_proof_is_bound_to_the_declared_test_and_target_sha(tmp_path: Path) -> None:
    """AC-testing.governance.23: only an executed declared testcase supplies proof."""
    junit = tmp_path / "tooling.xml"
    junit.write_text(
        '<testsuite><testcase classname="tests.demo.test_live" name="test_live"/></testsuite>',
        encoding="utf-8",
    )
    payload = junit_proof_payload(
        contracts=[_contract()],
        open_issue_urls={ISSUE_URL},
        junit_paths=[junit],
        target_sha=TARGET_SHA,
        observed_at=NOW,
        evidence_url="https://github.com/example/repo/actions/runs/10",
    )
    assert payload["source"] == "junit-executed-proof"
    assert payload["proofs"][0]["result"] == "passed"

    junit.write_text(
        '<testsuite><testcase classname="tests.demo.test_live" name="other"/></testsuite>',
        encoding="utf-8",
    )
    with pytest.raises(ObservationInputError, match="JUnit proof is missing"):
        junit_proof_payload(
            contracts=[_contract()],
            open_issue_urls={ISSUE_URL},
            junit_paths=[junit],
            target_sha=TARGET_SHA,
            observed_at=NOW,
            evidence_url="evidence",
        )

    junit.write_text(
        '<testsuite><testcase classname="tests.demo.test_live" name="test_live"><failure/></testcase></testsuite>',
        encoding="utf-8",
    )
    failed = junit_proof_payload(
        contracts=[_contract()],
        open_issue_urls={ISSUE_URL},
        junit_paths=[junit],
        target_sha=TARGET_SHA,
        observed_at=NOW,
        evidence_url="evidence",
    )
    assert failed["proofs"][0]["result"] == "failed"

    junit.write_text(
        '<testsuite><testcase classname="tests.demo.test_live" name="test_live"><skipped/></testcase></testsuite>',
        encoding="utf-8",
    )
    skipped = junit_proof_payload(
        contracts=[_contract()],
        open_issue_urls={ISSUE_URL},
        junit_paths=[junit],
        target_sha=TARGET_SHA,
        observed_at=NOW,
        evidence_url="evidence",
    )
    assert skipped["proofs"][0]["result"] == "failed"

    assert junit_proof_payload(
        contracts=[_contract()],
        open_issue_urls=set(),
        junit_paths=[junit],
        target_sha=TARGET_SHA,
        observed_at=NOW,
        evidence_url="evidence",
    )["proofs"] == []

    junit.write_text("not xml", encoding="utf-8")
    with pytest.raises(ObservationInputError, match="invalid JUnit"):
        junit_proof_payload(
            contracts=[_contract()],
            open_issue_urls={ISSUE_URL},
            junit_paths=[junit],
            target_sha=TARGET_SHA,
            observed_at=NOW,
            evidence_url="evidence",
        )

    contract = _contract()
    strong = contract.governance[0].guarantees[0].model_copy(
        update={"required_proof_strength": "concurrency"}
    )
    strong_contract = contract.model_copy(
        update={
            "governance": [
                contract.governance[0].model_copy(update={"guarantees": [strong]})
            ]
        }
    )
    junit.write_text(
        '<testsuite><testcase classname="tests.demo.test_live" name="test_live"/></testsuite>',
        encoding="utf-8",
    )
    with pytest.raises(ObservationInputError, match="strength-specific"):
        junit_proof_payload(
            contracts=[strong_contract],
            open_issue_urls={ISSUE_URL},
            junit_paths=[junit],
            target_sha=TARGET_SHA,
            observed_at=NOW,
            evidence_url="evidence",
        )


def test_AC_testing_governance_24_derives_live_enforcement_from_raw_facts() -> None:
    """AC-testing.governance.24: live enforcement is derived, never supplied."""
    inputs = _inputs()
    bundle = build_observation_bundle(**inputs)
    assert bundle["enforcement"][0]["live_required"] is True

    inputs["rulesets"][0]["enforcement"] = "disabled"
    with pytest.raises(ObservationInputError, match="required status contexts"):
        build_observation_bundle(**inputs)


def test_github_collector_retains_only_current_redacted_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-testing.governance.24: authenticated collection does not archive issue prose."""
    responses = {
        "repos/example/repo/rulesets": [{"id": 7}],
        "repos/example/repo/rulesets/7": {
            "id": 7,
            "name": "main",
            "enforcement": "active",
            "updated_at": NOW.isoformat(),
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
        (lambda data: data["detector_payloads"][0].update(source="authored"), "untrusted source"),
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
        (lambda data: data["proof_payloads"][0].update(source="detector"), "independent"),
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
        (lambda bundle: bundle.update(schema_version=2), "schema_version"),
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
    assert build_observation_bundle(**inputs)["enforcement"][0][
        "workflow_required"
    ]

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
    required_arguments = ("--observations", "--expected-target-sha", "${{ github.sha }}")
    assert all(command.count(argument) >= 1 for argument in required_arguments)


def test_observation_adapter_main_writes_live_bundle_and_redacted_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-testing.governance.25: the workflow command has an executable adapter."""
    junit_root = tmp_path / "junit"
    junit_root.mkdir()
    (junit_root / "tooling.xml").write_text(
        '<testsuite><testcase classname="tests.demo.test_live" name="test_live"/></testsuite>',
        encoding="utf-8",
    )
    inventory = tmp_path / "inventory.yaml"
    inventory.write_text(
        yaml.safe_dump(_inputs()["gate_inventory"]), encoding="utf-8"
    )
    workflow_path = tmp_path / ".github/workflows/ci.yml"
    workflow_path.parent.mkdir(parents=True)
    workflow_path.write_text(
        yaml.safe_dump(_inputs()["workflow"]), encoding="utf-8"
    )
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
