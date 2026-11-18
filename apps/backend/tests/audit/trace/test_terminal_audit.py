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
from tests._support.executed_proof import executed_proof_assertion_version, record_executed_proof, register_executed_proof_consumer

COMMIT = "a" * 40
OCCURRED_AT = datetime(2026, 7, 20, tzinfo=UTC)
REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
PROOF_ID = "trusted-year-v0-terminal"
TRUSTED_YEAR_AC_IDS = ("AC-testing.trusted-year.2", "AC-testing.trusted-year.3", "AC-testing.package-lifecycle.1")
PROOF_ASSERTION_VERSION = executed_proof_assertion_version(
    proof_id=PROOF_ID,
    scenario_id="trusted-year-v0",
    oracle_kind="independent_decimal",
    ac_ids=TRUSTED_YEAR_AC_IDS,
    stage="github_ci.merge_authority",
    task_category="critical_behavioral",
    required_observation_kind="terminal_audit",
)
_authority = lambda package, *, stage="product.runtime": TraceAuthorityProfile(
    package=package, tier="CODE-ONLY", proof_kind="exact", provenance="deterministic", execution_stage=stage, assertion_owner_digest="b" * 64, producer_version="fixture@1"
)
_ref = lambda record: TraceDecisionRef(record.record_id, record.target, record.assertion)


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


def _construct_from(record: TraceRecord, **overrides) -> TraceRecord:
    values = {f: getattr(record, f) for f in ("record_type", "scope", "target", "target_class", "assertion", "authority", "result", "execution_id", "causality", "evidence_manifest_digest", "occurred_at", "parent_ids", "supersedes_id", "score", "reason_code")}
    values.update(overrides)
    return TraceRecord._construct(**values)


def _graph():
    scope = TraceScope.tenant(UUID("10000000-0000-0000-0000-000000000001"))
    input_target = VersionedTraceRef("fixture_input", "input-1", "v1")
    input_obs = TraceRecord.observation(
        scope=scope, target=input_target, target_class=TraceTargetClass.FINANCIAL, assertion=VersionedTraceRef("fixture_invariant", "valid", "v1"),
        authority=_authority("ledger"), result=TraceResult.PASS, execution_id="input-run-1", evidence_manifest_digest="c" * 64, occurred_at=OCCURRED_AT, score=None, reason_code="fixture_valid",
    )
    input_dec = TraceRecord.decision(
        scope=scope, target=input_target, policy=_Policy(assertion=VersionedTraceRef("fixture_authority", "accepted", "v1"), authority=_authority("ledger"), causality=TraceCausality.DIRECT),
        execution_id=input_obs.execution_id, occurred_at=OCCURRED_AT, parents=(input_obs,),
    )
    pkg_target = VersionedTraceRef("fixture_package", "package-1", "d" * 64)
    pkg_obs = TraceRecord.observation(
        scope=scope, target=pkg_target, target_class=TraceTargetClass.FINANCIAL, assertion=VersionedTraceRef("fixture_invariant", "package-valid", "v1"),
        authority=_authority("reporting"), result=TraceResult.PASS, execution_id="package-run-1", evidence_manifest_digest=pkg_target.version, occurred_at=OCCURRED_AT, score=None, reason_code="fixture_valid",
    )
    pkg_dec = TraceRecord.decision(
        scope=scope, target=pkg_target, policy=_Policy(assertion=VersionedTraceRef("fixture_authority", "package-ready", "v1"), authority=_authority("reporting"), causality=TraceCausality.MANIFEST),
        execution_id=pkg_obs.execution_id, occurred_at=OCCURRED_AT, parents=(pkg_obs, input_dec),
    )
    spec = TerminalAuditSpec(
        scope=scope, package=_ref(pkg_dec), manifest=(_ref(input_dec),), repository_id="wangzitian0/finance_report",
        commit_sha=COMMIT, scenario_id="trusted-year-v0", proof=VersionedTraceRef("executed_proof", PROOF_ID, PROOF_ASSERTION_VERSION), execution_id="123.2",
    )
    return (_Repository((input_obs, input_dec, pkg_obs, pkg_dec)), spec, input_obs, input_dec, pkg_obs, pkg_dec)


async def test_AC_audit_terminal_trace_1_verifies_exact_frozen_graph() -> None:
    repository, spec, input_obs, input_dec, _, package = _graph()
    rep_obs = _construct_from(input_obs, target=VersionedTraceRef("fixture_input", "input-1", "v2"), supersedes_id=input_obs.record_id)
    rep_dec = TraceRecord.decision(
        scope=spec.scope, target=rep_obs.target, policy=_Policy(assertion=input_dec.assertion, authority=input_dec.authority, causality=TraceCausality.DIRECT),
        execution_id=rep_obs.execution_id, occurred_at=OCCURRED_AT, parents=(rep_obs,), supersedes_id=input_dec.record_id,
    )
    repository.records.update({rep_obs.record_id: rep_obs, rep_dec.record_id: rep_dec})
    assert await TerminalAuditVerifier(repository).verify_graph(spec) == package


@pytest.mark.parametrize(
    ("counterexample", "expected_owner"),
    [
        ("missing", "unknown"), ("cross_scope", "ledger"), ("id_mismatch", "ledger"), ("wrong_type", "ledger"),
        ("wrong_result", "ledger"), ("target", "ledger"), ("assertion", "ledger"), ("read_failure", "unknown"),
        ("parent_read_failure", "reporting"), ("parent_missing", "reporting"), ("parent_coordinate", "reporting"), ("disconnected", "reporting"),
    ],
)
async def test_AC_audit_terminal_trace_2_counterexamples_fail_closed(counterexample: str, expected_owner: str) -> None:
    repo, spec, input_obs, input_dec, pkg_obs, pkg = _graph()
    if counterexample in ("missing", "parent_missing"):
        repo.records.pop(input_dec.record_id if counterexample == "missing" else pkg_obs.record_id)
    elif counterexample in ("read_failure", "parent_read_failure"):
        repo.fail_reads.add(input_dec.record_id if counterexample == "read_failure" else pkg_obs.record_id)
    elif counterexample in ("cross_scope", "id_mismatch", "parent_coordinate"):
        target = pkg_obs if counterexample == "parent_coordinate" else input_dec
        override = {"execution_id": "different-run"} if counterexample == "id_mismatch" else {"scope": TraceScope.tenant(uuid4())}
        repo.records[target.record_id] = _construct_from(target, **override)
    elif counterexample == "wrong_result":
        rejected = _construct_from(input_dec, result=TraceResult.REJECTED, reason_code="fixture_rejected")
        repo.records[rejected.record_id] = rejected
        spec = replace(spec, manifest=(_ref(rejected),))
    elif counterexample == "disconnected":
        disconnected = _construct_from(pkg, parent_ids=(pkg_obs.record_id,))
        repo.records[disconnected.record_id] = disconnected
        spec = replace(spec, package=_ref(disconnected))
    else:
        manifest_item = {
            "wrong_type": _ref(input_obs),
            "target": replace(spec.manifest[0], target=VersionedTraceRef("fixture_input", "other", "v1")),
            "assertion": replace(spec.manifest[0], assertion=VersionedTraceRef("fixture_authority", "other", "v1")),
        }[counterexample]
        spec = replace(spec, manifest=(manifest_item,))

    with pytest.raises(RuntimeError) as raised:
        await TerminalAuditVerifier(repo).verify_graph(spec)
    assert (raised.value.layer, raised.value.owner) == ("graph", expected_owner)


def _executed_proof(spec: TerminalAuditSpec) -> TraceRecord:
    def executed_scenario() -> None:
        pass

    setattr(
        executed_scenario,
        PROOF_ATTR,
        AcProof(
            proof_id=spec.proof.id, ac_ids=TRUSTED_YEAR_AC_IDS, stage="github_ci.merge_authority",
            task_category="critical_behavioral", ci_tier="pr_ci", trust_mode="deterministic_pr",
            scenario_id=spec.scenario_id, oracle_kind="independent_decimal", required_observation_kind="terminal_audit",
        ),
    )
    item = SimpleNamespace(obj=executed_scenario, nodeid="tests/integration/test_terminal.py::test_scenario", user_properties=[])

    def _stub_terminal_consumer(_executed_proof_record):
        stub = TraceRecord.observation(
            scope=spec.scope, target=spec.package.target, target_class=TraceTargetClass.GENERAL,
            assertion=VersionedTraceRef("terminal_audit", spec.scenario_id, TERMINAL_AUDIT_POLICY_VERSION),
            authority=TraceAuthorityProfile(
                package="audit", tier="CODE-ONLY", proof_kind="exact", provenance="deterministic",
                execution_stage="github_ci.merge_authority", assertion_owner_digest=TERMINAL_AUDIT_POLICY_VERSION, producer_version=f"git@{spec.commit_sha}",
            ),
            result=TraceResult.PASS, execution_id="123.2", evidence_manifest_digest="e" * 64, occurred_at=OCCURRED_AT, score=None, reason_code="terminal_audit_passed",
        )
        return CommonTraceRecordCodec.decode(TraceRecordCodec.encode(stub))

    register_executed_proof_consumer(item, _stub_terminal_consumer)
    report = SimpleNamespace(when="call", passed=True, wasxfail=None)
    common_record = record_executed_proof(
        item, report, environ={"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": spec.repository_id, "GITHUB_SHA": spec.commit_sha, "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2"}, occurred_at=OCCURRED_AT,
    )
    assert common_record is not None
    return TraceRecordCodec.decode(item.user_properties[0][1])


async def test_AC_audit_terminal_trace_3_to_5_canonical_audit_and_redaction() -> None:
    repository, spec, *_ = _graph()
    verifier = TerminalAuditVerifier(repository)
    proof = _executed_proof(spec)
    terminal = await verifier.audit(spec, proof)
    assert (terminal.record_type, terminal.result, terminal.assertion, terminal.authority.package, terminal.authority.producer_version, TraceRecordCodec.decode(TraceRecordCodec.encode(terminal))) == (
        TraceRecordType.OBSERVATION, TraceResult.PASS, VersionedTraceRef("terminal_audit", spec.scenario_id, TERMINAL_AUDIT_POLICY_VERSION), "audit", f"git@{spec.commit_sha}", terminal,
    )

    for bad_proof in (
        _construct_from(proof, scope=TraceScope(TraceScopeKind.REPOSITORY, "other/repository")),
        _construct_from(proof, target=VersionedTraceRef("terminal_scenario", "other", spec.commit_sha)),
        _construct_from(proof, target=VersionedTraceRef("terminal_scenario", spec.scenario_id, "f" * 40)),
        _construct_from(proof, execution_id="other-run"),
        _construct_from(proof, result=TraceResult.SKIPPED),
        _construct_from(proof, authority=replace(proof.authority, execution_stage="local.advisory")),
        _construct_from(proof, assertion=replace(spec.proof, version="e" * 64)),
    ):
        with pytest.raises(RuntimeError) as raised:
            verifier.verify_executed_proof(spec, bad_proof)
        assert (raised.value.layer, raised.value.owner) == ("proof", "testing")

    audit_source = REPOSITORY_ROOT / "apps/backend/src/audit"
    terminal_source = (audit_source / "extension/terminal_audit.py").read_text()
    wire = TraceRecordCodec.encode(terminal)
    assert not (audit_source / "extension/promotion_trace.py").exists() and "PromotionTrace" not in "".join(p.read_text() for p in audit_source.rglob("*.py"))
    assert "PersonalReportPackage" not in terminal_source and "scan_surfaces" not in terminal_source
    assert set(json.loads(wire)) == {
        "assertion", "authority", "causality", "content_digest", "evidence_manifest_digest", "execution_id", "occurred_at",
        "parent_ids", "reason_code", "record_id", "record_type", "result", "schema_version", "scope", "score", "supersedes_id", "target", "target_class",
    } and not any(tok in wire.lower() for tok in ("amount", "source_text", "prompt", "email", "secret"))

    input_ref = spec.manifest[0]
    repository.records[input_ref.decision_id] = _construct_from(repository.records[input_ref.decision_id], authority=replace(repository.records[input_ref.decision_id].authority, package="private owner payload"))
    with pytest.raises(RuntimeError) as raised:
        await verifier.verify_graph(spec)
    assert raised.value.owner == "unknown"


@pytest.mark.parametrize(
    ("changes", "error", "match"),
    [
        ({"scope": TraceScope(TraceScopeKind.REPOSITORY, "owner/repository")}, ValueError, None),
        ({"package": "not-a-ref"}, TypeError, None),
        ({"manifest": []}, TypeError, None),
        ({"manifest": ()}, ValueError, None),
        ({"proof": VersionedTraceRef("other", "proof", "v1")}, ValueError, None),
        ({"scenario_id": "secret payload with spaces"}, ValueError, "redaction-safe"),
        ({"repository_id": "repository"}, ValueError, "owner/repository"),
        ({"commit_sha": "main"}, ValueError, "commit SHA"),
    ],
)
def test_terminal_audit_spec_rejects_ambiguous_coordinates(changes: dict, error: type[Exception], match: str | None) -> None:
    _, spec, *_ = _graph()
    with pytest.raises(error, match=match):
        replace(spec, **changes)
    with pytest.raises(ValueError, match="unique"):
        replace(spec, manifest=(spec.manifest[0], spec.manifest[0]))
    with pytest.raises(ValueError, match="cannot be a member"):
        replace(spec, manifest=(spec.package,))
