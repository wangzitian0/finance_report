"""Exact technical coordinates consumed by terminal audit."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.audit.base.trace import (
    TraceDecisionRef,
    TraceScope,
    TraceScopeKind,
    VersionedTraceRef,
)

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,199}$")


def _safe_identifier(value: str, *, field: str) -> None:
    if not isinstance(value, str) or not _SAFE_IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{field} must be a redaction-safe technical identifier")


@dataclass(frozen=True, slots=True)
class TerminalAuditSpec:
    """Exact graph and CI coordinates for one terminal observation."""

    scope: TraceScope
    package: TraceDecisionRef
    manifest: tuple[TraceDecisionRef, ...]
    repository_id: str
    commit_sha: str
    scenario_id: str
    proof: VersionedTraceRef
    execution_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.scope, TraceScope) or self.scope.kind is not TraceScopeKind.TENANT:
            raise ValueError("terminal audit requires a tenant TraceScope")
        if not isinstance(self.package, TraceDecisionRef):
            raise TypeError("package must be a TraceDecisionRef")
        if not isinstance(self.manifest, tuple) or not all(
            isinstance(item, TraceDecisionRef) for item in self.manifest
        ):
            raise TypeError("manifest must be a tuple of TraceDecisionRef")
        decision_ids = [item.decision_id for item in self.manifest]
        if not decision_ids or len(set(decision_ids)) != len(decision_ids):
            raise ValueError("manifest decision refs must be non-empty and unique")
        if self.package.decision_id in decision_ids:
            raise ValueError("package decision cannot be a member of its input manifest")
        if not isinstance(self.proof, VersionedTraceRef) or self.proof.kind != "executed_proof":
            raise ValueError("proof must be an executed_proof VersionedTraceRef")
        for field in ("repository_id", "scenario_id", "execution_id"):
            _safe_identifier(getattr(self, field), field=field)
        if "/" not in self.repository_id:
            raise ValueError("repository_id must identify owner/repository")
        if not _COMMIT_RE.fullmatch(self.commit_sha):
            raise ValueError("commit_sha must be one exact lowercase Git commit SHA")
