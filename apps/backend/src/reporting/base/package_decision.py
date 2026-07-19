"""TraceRecord policy for one immutable personal-report package decision."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from src.audit import (
    TraceAuthorityProfile,
    TraceCausality,
    TraceDecisionOutcome,
    TraceRecord,
    TraceRecordType,
    TraceResult,
    TraceTargetClass,
    VersionedTraceRef,
)

PACKAGE_DECISION_POLICY_VERSION = "2026-07-18"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def personal_report_package_target(
    *,
    snapshot_id: UUID,
    context: Mapping[str, Any],
    framework_policy: Mapping[str, Any],
    statement_disposition_policy: Mapping[str, Any],
    input_manifest: Sequence[Mapping[str, Any]],
    sections: Mapping[str, Any],
) -> VersionedTraceRef:
    """Bind one frozen package's complete semantic payload to an exact target."""
    semantic_payload = {
        "schema_version": "2",
        "snapshot_id": str(snapshot_id),
        "context": dict(context),
        "framework_policy": dict(framework_policy),
        "statement_disposition_policy": dict(statement_disposition_policy),
        "input_manifest": [dict(item) for item in input_manifest],
        "sections": dict(sections),
    }
    version = hashlib.sha256(
        json.dumps(semantic_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return VersionedTraceRef("personal_report_package", str(snapshot_id), version)


@dataclass(frozen=True, slots=True)
class PackageReadinessDecisionPolicy:
    """Fold exact input decisions plus one deterministic section observation."""

    @property
    def assertion(self) -> VersionedTraceRef:
        return VersionedTraceRef(
            "package_readiness",
            "personal-report-package",
            PACKAGE_DECISION_POLICY_VERSION,
        )

    @property
    def authority(self) -> TraceAuthorityProfile:
        return TraceAuthorityProfile(
            package="reporting",
            tier="CODE-ONLY",
            proof_kind="exact",
            provenance="deterministic",
            execution_stage="product.runtime",
            assertion_owner_digest=_digest(f"reporting:personal-report-package:{PACKAGE_DECISION_POLICY_VERSION}"),
            producer_version=PACKAGE_DECISION_POLICY_VERSION,
        )

    @property
    def causality(self) -> TraceCausality:
        return TraceCausality.MANIFEST

    @property
    def target_class(self) -> TraceTargetClass:
        return TraceTargetClass.FINANCIAL

    def fold(self, parents: Sequence[TraceRecord]) -> TraceDecisionOutcome:
        section_observations = [
            parent
            for parent in parents
            if parent.record_type is TraceRecordType.OBSERVATION and parent.reason_code == "package_sections_valid"
        ]
        input_decisions = [parent for parent in parents if parent.record_type is TraceRecordType.DECISION]
        valid = (
            len(section_observations) == 1
            and section_observations[0].result is TraceResult.PASS
            and bool(input_decisions)
            and all(parent.result is TraceResult.AUTHORITATIVE for parent in input_decisions)
        )
        return TraceDecisionOutcome(
            result=TraceResult.AUTHORITATIVE if valid else TraceResult.REJECTED,
            reason_code="package_inputs_authoritative" if valid else "package_inputs_unproven",
        )
