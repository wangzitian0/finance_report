"""Fail-closed terminal verification over one exact TraceRecord graph."""

from __future__ import annotations

import hashlib
import json
import re

from src.audit.base.terminal_audit import TerminalAuditSpec
from src.audit.base.trace import (
    TraceAuthorityProfile,
    TraceDecisionRef,
    TraceRecord,
    TraceRecordType,
    TraceResult,
    TraceScope,
    TraceScopeKind,
    TraceTargetClass,
    VersionedTraceRef,
)
from src.audit.base.trace_repository import TraceRecordRepository

_POLICY = {
    "graph": "exact-direct-decision-parents",
    "proof": "testing-executed-proof",
    "schema": 1,
}
_SAFE_DIAGNOSTIC_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,199}$")
TERMINAL_AUDIT_POLICY_VERSION = hashlib.sha256(
    json.dumps(_POLICY, sort_keys=True, separators=(",", ":")).encode("ascii")
).hexdigest()


class _TerminalAuditError(RuntimeError):
    """Redaction-safe diagnostic for the first broken terminal boundary."""

    def __init__(self, *, layer: str, owner: str, code: str) -> None:
        if not _SAFE_DIAGNOSTIC_RE.fullmatch(owner):
            owner = "unknown"
        self.layer = layer
        self.owner = owner
        self.code = code
        super().__init__(f"terminal audit failed: layer={layer} owner={owner} code={code}")


class TerminalAuditVerifier:
    """Verify canonical records without reconstructing an owner's policy."""

    def __init__(self, repository: TraceRecordRepository) -> None:
        self._repository = repository

    async def verify_graph(self, spec: TerminalAuditSpec) -> TraceRecord:
        manifest_records = [await self._load_exact_decision(spec.scope, expected) for expected in spec.manifest]
        package = await self._load_exact_decision(spec.scope, spec.package)

        parents: list[TraceRecord] = []
        for parent_id in package.parent_ids:
            try:
                parent = await self._repository.get(spec.scope, parent_id)
            except Exception as exc:
                raise _TerminalAuditError(
                    layer="graph",
                    owner=package.authority.package,
                    code="package_parent_read_failed",
                ) from exc
            if parent is None:
                raise _TerminalAuditError(
                    layer="graph",
                    owner=package.authority.package,
                    code="package_parent_missing_or_cross_scope",
                )
            if parent.scope != spec.scope or parent.record_id != parent_id:
                raise _TerminalAuditError(
                    layer="graph",
                    owner=parent.authority.package,
                    code="package_parent_coordinate_mismatch",
                )
            parents.append(parent)

        expected_ids = {record.record_id for record in manifest_records}
        actual_ids = {parent.record_id for parent in parents if parent.record_type is TraceRecordType.DECISION}
        if actual_ids != expected_ids:
            raise _TerminalAuditError(
                layer="graph",
                owner=package.authority.package,
                code="package_decision_parents_disconnected",
            )
        return package

    async def _load_exact_decision(
        self,
        scope: TraceScope,
        expected: TraceDecisionRef,
    ) -> TraceRecord:
        try:
            record = await self._repository.get(scope, expected.decision_id)
        except Exception as exc:
            raise _TerminalAuditError(
                layer="graph",
                owner="unknown",
                code="decision_read_failed",
            ) from exc
        if record is None:
            raise _TerminalAuditError(
                layer="graph",
                owner="unknown",
                code="decision_missing_or_cross_scope",
            )

        owner = record.authority.package
        if record.scope != scope:
            raise _TerminalAuditError(
                layer="graph",
                owner=owner,
                code="decision_cross_scope",
            )
        if record.record_id != expected.decision_id:
            raise _TerminalAuditError(
                layer="graph",
                owner=owner,
                code="decision_id_mismatch",
            )
        if record.record_type is not TraceRecordType.DECISION:
            raise _TerminalAuditError(
                layer="graph",
                owner=owner,
                code="referenced_record_not_decision",
            )
        if record.result is not TraceResult.AUTHORITATIVE:
            raise _TerminalAuditError(
                layer="graph",
                owner=owner,
                code="decision_not_authoritative",
            )
        if record.target != expected.target:
            raise _TerminalAuditError(
                layer="graph",
                owner=owner,
                code="decision_target_mismatch",
            )
        if record.assertion != expected.assertion:
            raise _TerminalAuditError(
                layer="graph",
                owner=owner,
                code="decision_assertion_mismatch",
            )
        return record

    def verify_executed_proof(
        self,
        spec: TerminalAuditSpec,
        proof: TraceRecord,
    ) -> None:
        valid = (
            proof.record_type is TraceRecordType.OBSERVATION
            and proof.result is TraceResult.PASS
            and proof.scope == TraceScope(TraceScopeKind.REPOSITORY, spec.repository_id)
            and proof.target == VersionedTraceRef("terminal_scenario", spec.scenario_id, spec.commit_sha)
            and proof.assertion == spec.proof
            and proof.execution_id == spec.execution_id
            and proof.authority.package == "testing"
            and proof.authority.tier == "CODE-ONLY"
            and proof.authority.proof_kind == "exact"
            and proof.authority.provenance == "deterministic"
            and proof.authority.execution_stage == "github_ci.merge_authority"
            and proof.reason_code == "executed_proof_passed"
        )
        if not valid:
            raise _TerminalAuditError(
                layer="proof",
                owner="testing",
                code="executed_proof_mismatch",
            )

    async def audit(
        self,
        spec: TerminalAuditSpec,
        executed_proof: TraceRecord,
    ) -> TraceRecord:
        package = await self.verify_graph(spec)
        self.verify_executed_proof(spec, executed_proof)
        evidence_digest = hashlib.sha256(
            json.dumps(
                {
                    "commit_sha": spec.commit_sha,
                    "execution_id": spec.execution_id,
                    "manifest_decision_ids": sorted(str(item.decision_id) for item in spec.manifest),
                    "package_decision_id": str(spec.package.decision_id),
                    "proof_record_id": str(executed_proof.record_id),
                    "repository_id": spec.repository_id,
                    "scenario_id": spec.scenario_id,
                    "terminal_policy_version": TERMINAL_AUDIT_POLICY_VERSION,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
        ).hexdigest()
        return TraceRecord.observation(
            scope=spec.scope,
            target=package.target,
            target_class=TraceTargetClass.GENERAL,
            assertion=VersionedTraceRef(
                "terminal_audit",
                spec.scenario_id,
                TERMINAL_AUDIT_POLICY_VERSION,
            ),
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
            execution_id=spec.execution_id,
            evidence_manifest_digest=evidence_digest,
            occurred_at=executed_proof.occurred_at,
            score=None,
            reason_code="terminal_audit_passed",
        )
