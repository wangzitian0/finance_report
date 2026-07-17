"""AC behavioral-evidence records.

A bare ``pass`` carries ~0 bits of information: it only says "the function did
not raise". This module lets a test attach a richer, *measured* signal to its
result for one Acceptance Criterion — a five-field record:

    (ac_id, code, score, metric, comment, provenance)

- ``code``  — the binary L2 outcome (pass/fail/skip/error). Hard gate.
- ``score`` — a graded L3 signal in [0.0, 1.0]. Ratcheted, never regressed.
- ``metric``/``provenance`` — the honesty anchor: a score must *name the yardstick
  it was measured against* and *where the number came from*. A score that is not
  ``compare(actual, golden)`` is just ``assert True`` moved up one level.

The record is emitted via pytest's builtin ``record_property`` fixture, which
serialises it into the junit-xml ``<property>`` element that CI already produces.
Downstream, :mod:`common.testing.ac_evidence_aggregate` reads it back and
:mod:`common.testing.check_ac_score_baseline` ratchets it. See
``common/testing/README.md`` for the full mechanism rationale.

This module imports only common-layer assurance values and stdlib at load time;
it remains importable from any test suite without app or framework dependencies.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from decimal import Decimal
from dataclasses import asdict, dataclass
from hashlib import sha256
from importlib import import_module, metadata
from pathlib import Path
from typing import Any, Callable

from common.audit.base.trace import (
    TraceAuthorityProfile,
    TraceRecord,
    TraceResult,
    TraceScope,
    TraceScopeKind,
    TraceTargetClass,
    VersionedTraceRef,
)
from common.audit.extension import TraceJUnitAdapter
from common.audit.ratio import Ratio
from common.meta.base.authority_matrix import TIER_DEFAULT_PROOF_KIND

PROPERTY_KEY = "ac_evidence"

# Accepts BOTH id grammars, matching the traceability layer
# (``common/testing/ac_traceability_refs.py``): the legacy EPIC-scoped ``ACx.y.z``
# and the package-scoped ``AC-<pkg>.group.seq`` (e.g. ``AC-ledger.2.1`` or
# ``AC-reconciliation.fx-transfer.1``, where ``group`` may be a word-entity
# slug, not just a number) used once an AC migrates into a package contract's
# roadmap. Without the second alternative, an ``@ac_proof`` test moved into
# the package scheme could not emit evidence.
AC_ID_PATTERN = re.compile(
    r"^AC(?:\d+\.\d+\.\d+|-[a-z][a-z0-9_]*\.[a-z0-9][a-z0-9_-]*\.\d+)$"
)
VALID_CODES = ("pass", "fail", "skip", "error")
# Provenance is either one of these literals, or "golden_fixture@<ref>". The bare
# "golden_fixture" form is rejected on purpose: a golden-derived score must name
# *which* golden it was measured against, or the honesty anchor is lost.
VALID_PROVENANCE = ("deterministic", "live_llm")


class ACEvidenceError(ValueError):
    """Raised when an AC evidence record is malformed."""


@dataclass(frozen=True)
class ACEvidence:
    """One measured evidence record binding a test outcome to an AC.

    Construction validates the record; an invalid record raises
    :class:`ACEvidenceError` rather than silently emitting a useless signal.
    """

    ac_id: str
    code: str
    score: float
    metric: str
    comment: str
    provenance: str

    def __post_init__(self) -> None:
        errors = self.validation_errors()
        if errors:
            raise ACEvidenceError("; ".join(errors))

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not AC_ID_PATTERN.match(self.ac_id):
            errors.append(f"ac_id {self.ac_id!r} must match ACx.y.z")
        if self.code not in VALID_CODES:
            errors.append(f"code {self.code!r} must be one of {VALID_CODES}")
        if not isinstance(self.score, (int, float)) or isinstance(self.score, bool):
            errors.append(f"score {self.score!r} must be a number")
        elif not 0.0 <= float(self.score) <= 1.0:
            errors.append(f"score {self.score!r} must be within [0.0, 1.0]")
        if not self.metric or not self.metric.strip():
            errors.append("metric is required (name the yardstick the score measures)")
        elif len(self.metric) > 200:
            errors.append("metric must not exceed 200 characters")
        if not self.comment or not self.comment.strip():
            errors.append("comment is required (human/agent-readable rationale)")
        if not _provenance_ok(self.provenance):
            errors.append(
                f"provenance {self.provenance!r} must be one of {VALID_PROVENANCE} "
                "or 'golden_fixture@<ref>'"
            )
        return errors

    def to_json(self) -> str:
        payload = asdict(self)
        payload["score"] = round(float(self.score), 6)
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, raw: str) -> ACEvidence:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ACEvidenceError(f"not valid JSON: {raw!r} ({exc})") from exc
        if not isinstance(data, dict):
            raise ACEvidenceError(f"expected a JSON object, got {type(data).__name__}")
        missing = sorted(
            {"ac_id", "code", "score", "metric", "comment", "provenance"} - set(data)
        )
        if missing:
            raise ACEvidenceError(f"missing fields: {', '.join(missing)}")
        return cls(
            ac_id=str(data["ac_id"]),
            code=str(data["code"]),
            score=float(data["score"]),
            metric=str(data["metric"]),
            comment=str(data["comment"]),
            provenance=str(data["provenance"]),
        )


def _provenance_ok(provenance: str) -> bool:
    if provenance in VALID_PROVENANCE:
        return True
    return provenance.startswith("golden_fixture@") and len(provenance) > len(
        "golden_fixture@"
    )


def build_evidence(
    *,
    ac_id: str,
    score: float,
    metric: str,
    comment: str,
    provenance: str,
    code: str = "pass",
) -> ACEvidence:
    """Build and validate an :class:`ACEvidence` record."""
    return ACEvidence(
        ac_id=ac_id,
        code=code,
        score=score,
        metric=metric,
        comment=comment,
        provenance=provenance,
    )


def record_ac_evidence(
    record_property: Callable[[str, Any], None],
    *,
    ac_id: str,
    score: float,
    metric: str,
    comment: str,
    provenance: str,
    code: str = "pass",
) -> ACEvidence:
    """Validate and emit one AC evidence record onto the current test result.

    ``record_property`` is pytest's builtin fixture of the same name. The record
    lands in junit-xml as ``<property name="ac_evidence" value="<json>">``.
    """
    evidence = build_evidence(
        ac_id=ac_id,
        score=score,
        metric=metric,
        comment=comment,
        provenance=provenance,
        code=code,
    )
    record_property(PROPERTY_KEY, evidence.to_json())
    trace_record = _trace_observation(evidence)
    if trace_record is not None:
        TraceJUnitAdapter.emit(record_property, trace_record)
    return evidence


def _trace_observation(evidence: ACEvidence) -> TraceRecord | None:
    """Resolve package authority for migrated AC ids; never infer legacy HU."""
    match = re.match(r"^AC-([a-z][a-z0-9_]*)\.", evidence.ac_id)
    if match is None:
        return None

    package = match.group(1)
    try:
        contract_module = import_module(f"common.{package}.contract")
        contract = contract_module.CONTRACT
    except (AttributeError, ImportError) as exc:
        raise ACEvidenceError(
            f"cannot resolve owning package contract for {evidence.ac_id}"
        ) from exc

    ac = next((row for row in contract.roadmap if row.id == evidence.ac_id), None)
    if ac is None or contract.tier is None:
        raise ACEvidenceError(
            f"{evidence.ac_id} has no active package authority declaration"
        )

    contract_path = Path(contract_module.__file__).resolve()
    owner_digest = sha256(contract_path.read_bytes()).hexdigest()
    stage = (
        "github_ci.merge_authority"
        if os.environ.get("GITHUB_ACTIONS") == "true"
        else "local.advisory"
    )
    target_version = os.environ.get("GITHUB_SHA", owner_digest)
    raw_execution_id = os.environ.get(
        "GITHUB_RUN_ID",
        os.environ.get("PYTEST_CURRENT_TEST", "local-pytest"),
    )
    execution_id = (
        raw_execution_id
        if len(raw_execution_id) <= 200
        else f"pytest@{sha256(raw_execution_id.encode('utf-8')).hexdigest()}"
    )
    result = {
        # This property is emitted before pytest knows the final testcase
        # outcome. A caller-reported pass therefore remains explicitly unproven
        # until the post-JUnit testing replacement folds the testcase result.
        "pass": TraceResult.UNPROVEN,
        "fail": TraceResult.FAIL,
        "skip": TraceResult.SKIPPED,
        "error": TraceResult.ERROR,
    }[evidence.code]
    return TraceRecord.observation(
        scope=TraceScope(
            kind=TraceScopeKind.REPOSITORY,
            id=os.environ.get("GITHUB_REPOSITORY", "finance_report"),
        ),
        target=VersionedTraceRef(
            kind="ac",
            id=evidence.ac_id,
            version=target_version,
        ),
        target_class=TraceTargetClass.GENERAL,
        assertion=VersionedTraceRef(
            kind="ac_proof",
            id=evidence.ac_id,
            version=owner_digest,
        ),
        authority=TraceAuthorityProfile(
            package=package,
            tier=contract.tier,
            proof_kind=ac.proof_kind or TIER_DEFAULT_PROOF_KIND[contract.tier],
            provenance=evidence.provenance,
            execution_stage=stage,
            assertion_owner_digest=owner_digest,
            producer_version=f"pytest@{metadata.version('pytest')}",
        ),
        result=result,
        execution_id=execution_id,
        evidence_manifest_digest=sha256(evidence.to_json().encode("utf-8")).hexdigest(),
        occurred_at=datetime.now(UTC),
        score=Ratio(Decimal(str(evidence.score))),
        reason_code=f"caller_reported_ac_evidence_{evidence.code}",
    )
