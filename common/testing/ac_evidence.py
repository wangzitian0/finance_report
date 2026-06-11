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
Downstream, :mod:`common.ssot.ac_evidence_aggregate` reads it back and
:mod:`common.ssot.check_ac_score_baseline` ratchets it. See
``common/testing/README.md`` for the full mechanism rationale.

stdlib-only by design: this module is importable from any test suite without
pulling in app or framework dependencies.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Callable

PROPERTY_KEY = "ac_evidence"

AC_ID_PATTERN = re.compile(r"^AC\d+\.\d+\.\d+$")
VALID_CODES = ("pass", "fail", "skip", "error")
# Provenance is either one of these literals, or "golden_fixture@<ref>".
VALID_PROVENANCE = ("deterministic", "golden_fixture", "live_llm")


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
    return evidence
