"""Terminal TraceRecord proofs for #1910."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from common.audit.extension import TraceRecordCodec as CommonTraceRecordCodec
from common.testing.ac_proof import PROOF_ATTR, AcProof
from common.testing.executed_proof import (
    executed_proof_assertion_version,
    record_executed_proof,
    register_executed_proof_consumer,
)

from src.audit import (
    TERMINAL_AUDIT_POLICY_VERSION,
    TerminalAuditSpec,
    TerminalAuditVerifier,
    TraceAuthorityProfile,
    TraceCausality,
    TraceDecisionOutcome,
    TraceDecisionRef,
    TraceRecord,
    TraceRecordCodec,
    TraceRecordType,
    TraceResult,
    TraceScope,
    TraceScopeKind,
    TraceTargetClass,
    VersionedTraceRef,
)

COMMIT = "a" * 40
OCCURRED_AT = datetime(2026, 7, 20, tzinfo=UTC)
REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
PROOF_ID = "trusted-year-v0-terminal"
TRUSTED_YEAR_AC_IDS = (
    "AC-testing.trusted-year.2",
    "AC-testing.trusted-year.3",
    "AC-testing.package-lifecycle.1",
)
PROOF_ASSERTION_VERSION = executed_proof_assertion_version(
    proof_id=PROOF_ID,
    scenario_id="trusted-year-v0",
    oracle_kind="independent_decimal",
    ac_ids=TRUSTED_YEAR_AC_IDS,
    stage="github_ci.merge_authority",
    task_category="critical_behavioral",
    required_observation_kind="terminal_audit",
)


def _authority(package: str, *, stage: str = "product.runtime") -> TraceAuthorityProfile:
    return TraceAuthorityProfile(
        package=package,
        tier="CODE-ONLY",
        proof_kind="exact",
        provenance="deterministic",
        execution_stage=stage,
        assertion_owner_digest="b" * 64,
        producer_version="fixture@1",
    )


@dataclass(frozen=True, slots=True)
class _Policy:
    assertion: VersionedTraceRef
    authority: TraceAuthorityProfile
    causality: TraceCausality
    target_class: TraceTargetClass = TraceTargetClass.FINANCIAL

    def fold(self, parents):
        accepted = all(parent.result in {TraceResult.PASS, TraceResult.AUTHORITATIVE} for parent in parents)
        return TraceDecisionOutcome(
            TraceResult.AUTHORITATIVE if accepted else TraceResult.REJECTED,
            "fixture_authoritative" if accepted else "fixture_rejected",
        )


class _Repository:
    def __init__(self, records: tuple[TraceRecord, ...]) -> None:
        self.records = {record.record_id: record for record in records}
        self.fail_reads: set[UUID] = set()

    async def get(self, _scope, record_id):
        if record_id in self.fail_reads:
            raise RuntimeError("fixture read failure")
        return self.records.get(record_id)


def _ref(record: TraceRecord) -> TraceDecisionRef:
    return TraceDecisionRef(record.record_id, record.target, record.assertion)


def _construct_from(record: TraceRecord, **overrides) -> TraceRecord:
    values = {
        "record_type": record.record_type,
        "scope": record.scope,
        "target": record.target,
        "target_class": record.target_class,
        "assertion": record.assertion,
        "authority": record.authority,
        "result": record.result,
        "execution_id": record.execution_id,
        "causality": record.causality,
        "evidence_manifest_digest": record.evidence_manifest_digest,
        "occurred_at": record.occurred_at,
        "parent_ids": record.parent_ids,
        "supersedes_id": record.supersedes_id,
        "score": record.score,
        "reason_code": record.reason_code,
    }
    values.update(overrides)
    return TraceRecord._construct(**values)


def _graph():
    scope = TraceScope.tenant(UUID("10000000-0000-0000-0000-000000000001"))
    input_target = VersionedTraceRef("fixture_input", "input-1", "v1")
    input_observation = TraceRecord.observation(
        scope=scope,
        target=input_target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef("fixture_invariant", "valid", "v1"),
        authority=_authority("ledger"),
        result=TraceResult.PASS,
        execution_id="input-run-1",
        evidence_manifest_digest="c" * 64,
        occurred_at=OCCURRED_AT,
        score=None,
        reason_code="fixture_valid",
    )
    input_decision = TraceRecord.decision(
        scope=scope,
        target=input_target,
        policy=_Policy(
            assertion=VersionedTraceRef("fixture_authority", "accepted", "v1"),
            authority=_authority("ledger"),
            causality=TraceCausality.DIRECT,
        ),
        execution_id=input_observation.execution_id,
        occurred_at=OCCURRED_AT,
        parents=(input_observation,),
    )
    package_target = VersionedTraceRef("fixture_package", "package-1", "d" * 64)
    package_observation = TraceRecord.observation(
        scope=scope,
        target=package_target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef("fixture_invariant", "package-valid", "v1"),
        authority=_authority("reporting"),
        result=TraceResult.PASS,
        execution_id="package-run-1",
        evidence_manifest_digest=package_target.version,
        occurred_at=OCCURRED_AT,
        score=None,
        reason_code="fixture_valid",
    )
    package_decision = TraceRecord.decision(
        scope=scope,
        target=package_target,
        policy=_Policy(
            assertion=VersionedTraceRef("fixture_authority", "package-ready", "v1"),
            authority=_authority("reporting"),
            causality=TraceCausality.MANIFEST,
        ),
        execution_id=package_observation.execution_id,
        occurred_at=OCCURRED_AT,
        parents=(package_observation, input_decision),
    )
    repository = _Repository((input_observation, input_decision, package_observation, package_decision))
    spec = TerminalAuditSpec(
        scope=scope,
        package=_ref(package_decision),
        manifest=(_ref(input_decision),),
        repository_id="wangzitian0/finance_report",
        commit_sha=COMMIT,
        scenario_id="trusted-year-v0",
        proof=VersionedTraceRef("executed_proof", PROOF_ID, PROOF_ASSERTION_VERSION),
        execution_id="123.2",
    )
    return (
        repository,
        spec,
        input_observation,
        input_decision,
        package_observation,
        package_decision,
    )


async def test_AC_audit_terminal_trace_1_verifies_exact_frozen_graph() -> None:
    """AC-audit.terminal-trace.1: verify refs and direct decision membership."""
    repository, spec, input_observation, input_decision, _, package = _graph()
    replacement_observation = _construct_from(
        input_observation,
        target=VersionedTraceRef("fixture_input", "input-1", "v2"),
        supersedes_id=input_observation.record_id,
    )
    replacement = TraceRecord.decision(
        scope=spec.scope,
        target=replacement_observation.target,
        policy=_Policy(
            assertion=input_decision.assertion,
            authority=input_decision.authority,
            causality=TraceCausality.DIRECT,
        ),
        execution_id=replacement_observation.execution_id,
        occurred_at=OCCURRED_AT,
        parents=(replacement_observation,),
        supersedes_id=input_decision.record_id,
    )
    repository.records.update(
        {
            replacement_observation.record_id: replacement_observation,
            replacement.record_id: replacement,
        }
    )

    assert await TerminalAuditVerifier(repository).verify_graph(spec) == package


@pytest.mark.parametrize(
    "counterexample",
    [
        "missing",
        "cross_scope",
        "id_mismatch",
        "wrong_type",
        "wrong_result",
        "target",
        "assertion",
        "read_failure",
        "parent_read_failure",
        "parent_missing",
        "parent_coordinate",
        "disconnected",
    ],
)
async def test_AC_audit_terminal_trace_2_counterexamples_fail_closed(
    counterexample: str,
) -> None:
    """AC-audit.terminal-trace.2: malformed exact graphs fail with owner diagnostics."""
    repository, spec, input_observation, input_decision, package_observation, package = _graph()
    expected_owner = "ledger"
    if counterexample == "missing":
        repository.records.pop(input_decision.record_id)
        expected_owner = "unknown"
    elif counterexample == "cross_scope":
        repository.records[input_decision.record_id] = _construct_from(
            input_decision,
            scope=TraceScope.tenant(uuid4()),
        )
    elif counterexample == "id_mismatch":
        repository.records[input_decision.record_id] = _construct_from(
            input_decision,
            execution_id="different-run",
        )
    elif counterexample == "wrong_type":
        spec = replace(spec, manifest=(_ref(input_observation),))
    elif counterexample == "wrong_result":
        rejected = _construct_from(
            input_decision,
            result=TraceResult.REJECTED,
            reason_code="fixture_rejected",
        )
        repository.records[rejected.record_id] = rejected
        spec = replace(spec, manifest=(_ref(rejected),))
    elif counterexample == "target":
        wrong = replace(
            spec.manifest[0],
            target=VersionedTraceRef("fixture_input", "other", "v1"),
        )
        spec = replace(spec, manifest=(wrong,))
    elif counterexample == "assertion":
        wrong = replace(
            spec.manifest[0],
            assertion=VersionedTraceRef("fixture_authority", "other", "v1"),
        )
        spec = replace(spec, manifest=(wrong,))
    elif counterexample == "read_failure":
        repository.fail_reads.add(input_decision.record_id)
        expected_owner = "unknown"
    elif counterexample == "parent_read_failure":
        repository.fail_reads.add(package_observation.record_id)
        expected_owner = "reporting"
    elif counterexample == "parent_missing":
        repository.records.pop(package_observation.record_id)
        expected_owner = "reporting"
    elif counterexample == "parent_coordinate":
        repository.records[package_observation.record_id] = _construct_from(
            package_observation,
            scope=TraceScope.tenant(uuid4()),
        )
        expected_owner = "reporting"
    else:
        disconnected = _construct_from(
            package,
            parent_ids=(package_observation.record_id,),
        )
        repository.records[disconnected.record_id] = disconnected
        spec = replace(spec, package=_ref(disconnected))
        expected_owner = "reporting"

    with pytest.raises(RuntimeError) as raised:
        await TerminalAuditVerifier(repository).verify_graph(spec)

    assert raised.value.layer == "graph"
    assert raised.value.owner == expected_owner


def _executed_proof(spec: TerminalAuditSpec) -> TraceRecord:
    def executed_scenario() -> None:
        pass

    setattr(
        executed_scenario,
        PROOF_ATTR,
        AcProof(
            proof_id=spec.proof.id,
            ac_ids=TRUSTED_YEAR_AC_IDS,
            stage="github_ci.merge_authority",
            task_category="critical_behavioral",
            ci_tier="pr_ci",
            trust_mode="deterministic_pr",
            scenario_id=spec.scenario_id,
            oracle_kind="independent_decimal",
            required_observation_kind="terminal_audit",
        ),
    )
    item = SimpleNamespace(
        obj=executed_scenario,
        nodeid="tests/integration/test_terminal.py::test_scenario",
        user_properties=[],
    )

    def _stub_terminal_consumer(_executed_proof_record):
        stub = TraceRecord.observation(
            scope=spec.scope,
            target=spec.package.target,
            target_class=TraceTargetClass.GENERAL,
            assertion=VersionedTraceRef("terminal_audit", spec.scenario_id, TERMINAL_AUDIT_POLICY_VERSION),
            authority=TraceAuthorityProfile(
                package="audit",
                tier="CODE-ONLY",
                proof_kind="exact",
                provenance="deterministic",
                execution_stage="github_ci.merge_authority",
                assertion_owner_digest=TERMINAL_AUDIT_POLICY_VERSION,
                producer_version=f"git@{spec.commit_sha}",
            ),
            result=TraceResult.PASS,
            execution_id="123.2",
            evidence_manifest_digest="e" * 64,
            occurred_at=OCCURRED_AT,
            score=None,
            reason_code="terminal_audit_passed",
        )
        return CommonTraceRecordCodec.decode(TraceRecordCodec.encode(stub))

    register_executed_proof_consumer(item, _stub_terminal_consumer)
    report = SimpleNamespace(when="call", passed=True, wasxfail=None)
    common_record = record_executed_proof(
        item,
        report,
        environ={
            "GITHUB_ACTIONS": "true",
            "GITHUB_REPOSITORY": spec.repository_id,
            "GITHUB_SHA": spec.commit_sha,
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "2",
        },
        occurred_at=OCCURRED_AT,
    )
    assert common_record is not None
    return TraceRecordCodec.decode(item.user_properties[0][1])


async def test_AC_audit_terminal_trace_3_emits_only_canonical_trace_record() -> None:
    """AC-audit.terminal-trace.3: compose real executed proof into TraceRecord."""
    repository, spec, *_ = _graph()
    verifier = TerminalAuditVerifier(repository)
    proof = _executed_proof(spec)

    terminal = await verifier.audit(spec, proof)

    assert terminal.record_type is TraceRecordType.OBSERVATION
    assert terminal.result is TraceResult.PASS
    assert terminal.assertion == VersionedTraceRef(
        "terminal_audit",
        spec.scenario_id,
        TERMINAL_AUDIT_POLICY_VERSION,
    )
    assert terminal.authority.package == "audit"
    assert terminal.authority.producer_version == f"git@{spec.commit_sha}"
    assert TraceRecordCodec.decode(TraceRecordCodec.encode(terminal)) == terminal

    counterexamples = (
        _construct_from(
            proof,
            scope=TraceScope(TraceScopeKind.REPOSITORY, "other/repository"),
        ),
        _construct_from(
            proof,
            target=VersionedTraceRef("terminal_scenario", "other", spec.commit_sha),
        ),
        _construct_from(
            proof,
            target=VersionedTraceRef("terminal_scenario", spec.scenario_id, "f" * 40),
        ),
        _construct_from(proof, execution_id="other-run"),
        _construct_from(proof, result=TraceResult.SKIPPED),
        _construct_from(
            proof,
            authority=replace(proof.authority, execution_stage="local.advisory"),
        ),
        _construct_from(
            proof,
            assertion=replace(spec.proof, version="e" * 64),
        ),
    )
    for counterexample in counterexamples:
        with pytest.raises(RuntimeError) as raised:
            verifier.verify_executed_proof(spec, counterexample)
        assert (raised.value.layer, raised.value.owner) == ("proof", "testing")


def test_AC_audit_terminal_trace_4_deletes_audit_owned_shadow_only() -> None:
    """AC-audit.terminal-trace.4: delete the audit shadow without owner maps."""
    audit_source = REPOSITORY_ROOT / "apps/backend/src/audit"
    terminal_source = (audit_source / "extension/terminal_audit.py").read_text()

    assert not (audit_source / "extension/promotion_trace.py").exists()
    assert "PromotionTrace" not in "".join(path.read_text() for path in audit_source.rglob("*.py"))
    assert "PersonalReportPackage" not in terminal_source
    assert "scan_surfaces" not in terminal_source


async def test_AC_audit_terminal_trace_5_output_and_diagnostics_are_redaction_safe() -> None:
    """AC-audit.terminal-trace.5: terminal output carries technical coordinates only."""
    repository, spec, *_ = _graph()
    terminal = await TerminalAuditVerifier(repository).audit(spec, _executed_proof(spec))
    payload = json.loads(TraceRecordCodec.encode(terminal))

    assert set(payload) == {
        "assertion",
        "authority",
        "causality",
        "content_digest",
        "evidence_manifest_digest",
        "execution_id",
        "occurred_at",
        "parent_ids",
        "reason_code",
        "record_id",
        "record_type",
        "result",
        "schema_version",
        "scope",
        "score",
        "supersedes_id",
        "target",
        "target_class",
    }
    wire = TraceRecordCodec.encode(terminal).lower()
    assert not any(forbidden in wire for forbidden in ("amount", "source_text", "prompt", "email", "secret"))
    with pytest.raises(ValueError, match="redaction-safe"):
        replace(spec, scenario_id="secret payload with spaces")
    with pytest.raises(ValueError, match="owner/repository"):
        replace(spec, repository_id="repository")
    with pytest.raises(ValueError, match="commit SHA"):
        replace(spec, commit_sha="main")

    input_ref = spec.manifest[0]
    unsafe_owner_record = _construct_from(
        repository.records[input_ref.decision_id],
        authority=replace(
            repository.records[input_ref.decision_id].authority,
            package="private owner payload",
        ),
    )
    repository.records[input_ref.decision_id] = unsafe_owner_record
    with pytest.raises(RuntimeError) as raised:
        await TerminalAuditVerifier(repository).verify_graph(spec)
    assert raised.value.owner == "unknown"


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"scope": TraceScope(TraceScopeKind.REPOSITORY, "owner/repository")}, ValueError),
        ({"package": "not-a-ref"}, TypeError),
        ({"manifest": []}, TypeError),
        ({"manifest": ()}, ValueError),
        ({"proof": VersionedTraceRef("other", "proof", "v1")}, ValueError),
    ],
)
def test_terminal_audit_spec_rejects_ambiguous_coordinates(changes, error) -> None:
    _, spec, *_ = _graph()
    with pytest.raises(error):
        replace(spec, **changes)

    with pytest.raises(ValueError, match="unique"):
        replace(spec, manifest=(spec.manifest[0], spec.manifest[0]))
    with pytest.raises(ValueError, match="cannot be a member"):
        replace(spec, manifest=(spec.package,))
