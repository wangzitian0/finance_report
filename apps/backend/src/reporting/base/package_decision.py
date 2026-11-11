"""TraceRecord policy for one immutable personal-report package decision."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from src.audit import (
    DeclarativeTracePolicy,
    TraceAuthorityProfile,
    TraceCausality,
    TraceDecisionOutcome,
    TraceRecord,
    TraceRecordType,
    TraceResult,
    VersionedTraceRef,
    canonical_json_digest,
    text_digest,
)

PACKAGE_DECISION_POLICY_VERSION = "2026-07-18"


def personal_report_package_target(
    *,
    snapshot_id: UUID,
    context: Mapping[str, Any],
    framework_policy: Mapping[str, Any],
    statement_disposition_policy: Mapping[str, Any],
    input_manifest: Sequence[Mapping[str, Any]],
    sections: Mapping[str, Any],
) -> VersionedTraceRef:
    version = canonical_json_digest(
        {
            "schema_version": "2",
            "snapshot_id": str(snapshot_id),
            "context": dict(context),
            "framework_policy": dict(framework_policy),
            "statement_disposition_policy": dict(statement_disposition_policy),
            "input_manifest": [dict(item) for item in input_manifest],
            "sections": dict(sections),
        }
    )
    return VersionedTraceRef("personal_report_package", str(snapshot_id), version)


@dataclass(frozen=True, slots=True)
class PackageReadinessDecisionPolicy(DeclarativeTracePolicy):
    assertion: VersionedTraceRef = field(
        default_factory=lambda: VersionedTraceRef(
            "package_readiness", "personal-report-package", PACKAGE_DECISION_POLICY_VERSION
        )
    )
    authority: TraceAuthorityProfile = field(
        default_factory=lambda: TraceAuthorityProfile(
            package="reporting",
            tier="CODE-ONLY",
            proof_kind="exact",
            provenance="deterministic",
            execution_stage="product.runtime",
            assertion_owner_digest=text_digest(f"reporting:personal-report-package:{PACKAGE_DECISION_POLICY_VERSION}"),
            producer_version=PACKAGE_DECISION_POLICY_VERSION,
        )
    )
    causality: TraceCausality = TraceCausality.MANIFEST

    def fold(self, parents: Sequence[TraceRecord]) -> TraceDecisionOutcome:
        obs = [
            p for p in parents if p.record_type is TraceRecordType.OBSERVATION and p.reason_code == "package_sections_valid"
        ]
        decisions = [p for p in parents if p.record_type is TraceRecordType.DECISION]
        valid = (
            len(obs) == 1
            and obs[0].result is TraceResult.PASS
            and bool(decisions)
            and all(p.result is TraceResult.AUTHORITATIVE for p in decisions)
        )
        return TraceDecisionOutcome(
            result=TraceResult.AUTHORITATIVE if valid else TraceResult.REJECTED,
            reason_code="package_inputs_authoritative" if valid else "package_inputs_unproven",
        )
