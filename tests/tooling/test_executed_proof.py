"""Executed semantic proof contract for scenario-bound PR-CI tests."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from xml.etree import ElementTree
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from common.audit.base import (
    TraceAuthorityProfile,
    TraceCausality,
    TraceDecisionOutcome,
    TraceRecord,
    TraceRecordType,
    TraceResult,
    TraceScopeKind,
    TraceTargetClass,
    VersionedTraceRef,
)
from common.audit.extension import TraceJUnitAdapter, TraceRecordCodec
from common.testing.ac_proof import ac_proof
from common.testing import check_pr_ci_evidence
from common.testing.check_pr_ci_evidence import collect_executed_proofs
from common.testing.executed_proof import (
    ExecutedProofError,
    executed_proof_matches,
    record_executed_proof,
    register_executed_proof_consumer,
)

COMMIT_SHA = "a" * 40
OCCURRED_AT = datetime(2026, 7, 20, tzinfo=UTC)
CI_ENV = {
    "GITHUB_ACTIONS": "true",
    "GITHUB_REPOSITORY": "wangzitian0/finance_report",
    "GITHUB_SHA": COMMIT_SHA,
    "GITHUB_RUN_ID": "123456789",
    "GITHUB_RUN_ATTEMPT": "2",
}
EXECUTION_ID = "123456789.2"
REPO_ROOT = Path(__file__).resolve().parents[2]


@ac_proof(
    "scenario-proof",
    ac_ids=["AC-testing.capability-proof.1"],
    ci_tier="pr_ci",
    trust_mode="deterministic_pr",
    scenario_id="trusted-year-v0",
    oracle_kind="independent_decimal",
)
def _scenario_proof() -> None:
    pass


@dataclass
class _Item:
    obj: Any = _scenario_proof
    nodeid: str = "tests/integration/test_scenario.py::test_terminal"
    user_properties: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class _Report:
    when: str = "call"
    passed: bool = True
    skipped: bool = False
    failed: bool = False
    wasxfail: str | None = None
    user_properties: list[tuple[str, str]] = field(default_factory=list)


def test_pass_is_bound_to_exact_ci_coordinates() -> None:
    item = _Item()
    report = _Report()

    record = record_executed_proof(
        item,
        report,
        environ=CI_ENV,
        occurred_at=OCCURRED_AT,
    )

    assert record is not None
    assert item.user_properties[0][0] == TraceJUnitAdapter.PROPERTY_KEY
    decoded = TraceRecordCodec.decode(item.user_properties[0][1])
    assert decoded == record
    assert decoded.record_type is TraceRecordType.OBSERVATION
    assert decoded.result is TraceResult.PASS
    assert decoded.scope.kind is TraceScopeKind.REPOSITORY
    assert decoded.scope.id == CI_ENV["GITHUB_REPOSITORY"]
    assert decoded.target.kind == "terminal_scenario"
    assert decoded.target.id == "trusted-year-v0"
    assert decoded.target.version == COMMIT_SHA
    assert decoded.assertion.kind == "executed_proof"
    assert decoded.assertion.id == "scenario-proof"
    assert decoded.execution_id == EXECUTION_ID
    assert decoded.authority.package == "testing"
    assert decoded.authority.execution_stage == "github_ci.merge_authority"
    assert executed_proof_matches(
        decoded,
        proof_id="scenario-proof",
        scenario_id="trusted-year-v0",
        repository_id=CI_ENV["GITHUB_REPOSITORY"],
        commit_sha=COMMIT_SHA,
        execution_id=EXECUTION_ID,
    )


def test_pytest_hook_records_the_resolved_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from common.testing import executed_proof_plugin

    captured: list[tuple[object, object]] = []
    monkeypatch.setattr(
        executed_proof_plugin,
        "record_executed_proof",
        lambda item, report: captured.append((item, report)),
    )
    item = _Item()
    report = _Report()
    outcome = SimpleNamespace(get_result=lambda: report)

    hook = executed_proof_plugin.pytest_runtest_makereport(item, object())
    next(hook)
    with pytest.raises(StopIteration):
        hook.send(outcome)

    assert captured == [(item, report)]


def test_AC_testing_capability_proof_1_pytest_junit_binds_exact_ci_coordinates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-testing.capability-proof.1: real pytest outcome survives JUnit exactly."""
    test_file = tmp_path / "test_scenario.py"
    test_file.write_text(
        textwrap.dedent(
            """
            from common.testing.ac_proof import ac_proof

            @ac_proof(
                "scenario-proof",
                ac_ids=["AC-testing.capability-proof.1"],
                ci_tier="pr_ci",
                trust_mode="deterministic_pr",
                scenario_id="trusted-year-v0",
                oracle_kind="independent_decimal",
            )
            def test_terminal():
                assert 2 + 2 == 4
            """
        ),
        encoding="utf-8",
    )
    junit = tmp_path / "junit.xml"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(test_file),
            "-p",
            "common.testing.executed_proof_plugin",
            "-p",
            "no:xdist",
            "-o",
            "addopts=",
            "-q",
            f"--junit-xml={junit}",
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            **CI_ENV,
            "PYTHONPATH": os.pathsep.join(
                filter(None, (str(REPO_ROOT), os.environ.get("PYTHONPATH", "")))
            ),
        },
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    records, malformed = collect_executed_proofs([junit])
    assert malformed == set()
    record = next(record for group in records.values() for record in group)
    assert executed_proof_matches(
        record,
        proof_id="scenario-proof",
        scenario_id="trusted-year-v0",
        repository_id=CI_ENV["GITHUB_REPOSITORY"],
        commit_sha=COMMIT_SHA,
        execution_id=EXECUTION_ID,
    )

    proof = {
        "id": "scenario-proof",
        "scope": "behavioral",
        "ci_tier": "pr_ci",
        "file": "test_scenario.py",
        "test": "test_terminal",
        "ac_ids": ["AC-testing.capability-proof.1"],
        "scenario_id": "trusted-year-v0",
        "oracle_kind": "independent_decimal",
        "stage": "github_ci.merge_authority",
        "task_category": "critical_behavioral",
    }
    import common.testing.ac_graph as ac_graph
    import common.testing.generate_critical_proof_matrix as proof_matrix

    monkeypatch.setattr(ac_graph, "build_proofs_only", lambda: object())
    monkeypatch.setattr(
        proof_matrix,
        "build_matrix_from_graph",
        lambda _graph: {"proofs": [proof]},
    )
    monkeypatch.setattr(
        check_pr_ci_evidence,
        "classify_stage",
        lambda _path: next(iter(check_pr_ci_evidence.PR_EVIDENCE_STAGES)),
    )
    for name, value in CI_ENV.items():
        monkeypatch.setenv(name, value)
    assert check_pr_ci_evidence.run_check([junit]) == 0

    tree = ElementTree.parse(junit)
    for properties in tree.iter("properties"):
        properties.clear()
    missing_trace = tmp_path / "missing-trace.xml"
    tree.write(missing_trace, encoding="utf-8", xml_declaration=True)
    assert check_pr_ci_evidence.run_check([missing_trace]) == 1


def _terminal_observation(proof: TraceRecord) -> TraceRecord:
    return TraceRecord.observation(
        scope=proof.scope,
        target=proof.target,
        target_class=TraceTargetClass.GENERAL,
        assertion=VersionedTraceRef("terminal_audit", proof.target.id, "b" * 64),
        authority=TraceAuthorityProfile(
            package="audit",
            tier="CODE-ONLY",
            proof_kind="exact",
            provenance="deterministic",
            execution_stage=proof.authority.execution_stage,
            assertion_owner_digest="c" * 64,
            producer_version=f"git@{proof.target.version}",
        ),
        result=TraceResult.PASS,
        execution_id=proof.execution_id,
        evidence_manifest_digest="d" * 64,
        occurred_at=proof.occurred_at,
        score=None,
        reason_code="terminal_audit_passed",
    )


def _terminal_decision(proof: TraceRecord) -> TraceRecord:
    @dataclass(frozen=True)
    class _Policy:
        assertion: VersionedTraceRef = VersionedTraceRef(
            "terminal_policy", "invalid", "v1"
        )
        authority: TraceAuthorityProfile = TraceAuthorityProfile(
            package="audit",
            tier="CODE-ONLY",
            proof_kind="exact",
            provenance="deterministic",
            execution_stage="github_ci.merge_authority",
            assertion_owner_digest="e" * 64,
            producer_version="fixture@1",
        )
        causality: TraceCausality = TraceCausality.DIRECT
        target_class: TraceTargetClass = TraceTargetClass.GENERAL

        def fold(self, _parents) -> TraceDecisionOutcome:
            return TraceDecisionOutcome(
                TraceResult.AUTHORITATIVE, "invalid_terminal_decision"
            )

    return TraceRecord.decision(
        scope=proof.scope,
        target=proof.target,
        policy=_Policy(),
        execution_id=proof.execution_id,
        occurred_at=proof.occurred_at,
        parents=(proof,),
    )


def test_AC_testing_capability_proof_3_post_call_consumer_is_single_and_fail_closed() -> (
    None
):
    """AC-testing.capability-proof.3: post-call composition has one fail-closed seam."""
    item = _Item()
    consumed: list[TraceRecord] = []

    def consume(proof: TraceRecord) -> TraceRecord:
        consumed.append(proof)
        return _terminal_observation(proof)

    register_executed_proof_consumer(item, consume)
    with pytest.raises(ExecutedProofError, match="already registered"):
        register_executed_proof_consumer(item, consume)

    proof = record_executed_proof(
        item, _Report(), environ=CI_ENV, occurred_at=OCCURRED_AT
    )

    assert proof is not None
    assert consumed == [proof]
    records = [TraceRecordCodec.decode(value) for name, value in item.user_properties]
    assert [record.assertion.kind for record in records] == [
        "executed_proof",
        "terminal_audit",
    ]
    assert records[1] == _terminal_observation(proof)

    failed_item = _Item()
    register_executed_proof_consumer(failed_item, consume)
    assert (
        record_executed_proof(
            failed_item,
            _Report(passed=False, failed=True),
            environ=CI_ENV,
            occurred_at=OCCURRED_AT,
        )
        is None
    )
    assert consumed == [proof]
    assert failed_item.user_properties == []

    invalid_item = _Item()
    register_executed_proof_consumer(invalid_item, _terminal_decision)
    with pytest.raises(ExecutedProofError, match="OBSERVATION"):
        record_executed_proof(
            invalid_item, _Report(), environ=CI_ENV, occurred_at=OCCURRED_AT
        )
    assert len(invalid_item.user_properties) == 1

    failed_consumer_item = _Item()

    def fail_consumer(_proof: TraceRecord) -> TraceRecord:
        raise RuntimeError("terminal consumer failed")

    register_executed_proof_consumer(failed_consumer_item, fail_consumer)
    with pytest.raises(RuntimeError, match="terminal consumer failed"):
        record_executed_proof(
            failed_consumer_item,
            _Report(),
            environ=CI_ENV,
            occurred_at=OCCURRED_AT,
        )
    assert len(failed_consumer_item.user_properties) == 1


@pytest.mark.parametrize(
    ("when", "passed", "skipped", "failed", "wasxfail"),
    (
        ("setup", True, False, False, None),
        ("teardown", True, False, False, None),
        ("call", False, True, False, None),
        ("call", False, False, True, None),
        ("call", True, False, False, "reason"),
    ),
)
def test_executed_proof_rejects_non_pass_call_outcomes(
    when: str,
    passed: bool,
    skipped: bool,
    failed: bool,
    wasxfail: str | None,
) -> None:
    report = _Report(
        when=when,
        passed=passed,
        skipped=skipped,
        failed=failed,
        wasxfail=wasxfail,
    )
    item = _Item()

    assert (
        record_executed_proof(
            item,
            report,
            environ=CI_ENV,
            occurred_at=OCCURRED_AT,
        )
        is None
    )
    assert item.user_properties == []
    assert report.user_properties == []


def test_executed_proof_requires_scenario_metadata() -> None:
    @ac_proof("ordinary-proof", ac_ids=["AC-testing.capability-proof.1"])
    def ordinary_proof() -> None:
        pass

    item = _Item(obj=ordinary_proof)
    report = _Report()

    assert (
        record_executed_proof(
            item,
            report,
            environ=CI_ENV,
            occurred_at=OCCURRED_AT,
        )
        is None
    )
    assert item.user_properties == []
    assert report.user_properties == []


@pytest.mark.parametrize(
    "changed",
    ("proof_id", "scenario_id", "repository_id", "commit_sha", "execution_id"),
)
def test_executed_proof_matcher_fails_closed_on_coordinate_mismatch(
    changed: str,
) -> None:
    record = record_executed_proof(
        _Item(),
        _Report(),
        environ=CI_ENV,
        occurred_at=OCCURRED_AT,
    )
    assert record is not None
    expected = {
        "proof_id": "scenario-proof",
        "scenario_id": "trusted-year-v0",
        "repository_id": CI_ENV["GITHUB_REPOSITORY"],
        "commit_sha": COMMIT_SHA,
        "execution_id": EXECUTION_ID,
    }
    expected[changed] = "wrong"

    assert not executed_proof_matches(record, **expected)
