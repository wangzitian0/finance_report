"""Pure vocabulary for package-owned governance and supplied observations."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

ProofStrength = Literal[
    "reference-only",
    "report-only",
    "exact",
    "concurrency",
    "schema",
    "consumer-compile",
    "value-oracle",
]


class GovernanceGuarantee(BaseModel):
    """One independently provable outcome owned by a package initiative."""

    id: str
    statement: str
    affected_acs: list[str]
    detector: str
    target: str
    lock: str
    proof: str
    required_proof_strength: ProofStrength
    enforcing_gate: str

    @field_validator("id", "statement", "detector", "target", "lock", "proof", "enforcing_gate")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("governance guarantee fields must be non-empty")
        return value.strip()

    @model_validator(mode="after")
    def _has_affected_ac(self) -> GovernanceGuarantee:
        if not self.affected_acs:
            raise ValueError("governance guarantee must reference at least one AC")
        if len(self.affected_acs) != len(set(self.affected_acs)):
            raise ValueError(f"guarantee {self.id!r} has duplicate affected ACs")
        return self


class GovernanceInitiative(BaseModel):
    """A package-local root-cause initiative; progress is never authored here."""

    id: str
    title: str
    issue: str
    guarantees: list[GovernanceGuarantee]
    depends_on: list[str] = []

    @field_validator("id", "title", "issue")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("governance initiative fields must be non-empty")
        return value.strip()

    @model_validator(mode="after")
    def _unique_guarantees(self) -> GovernanceInitiative:
        ids = [guarantee.id for guarantee in self.guarantees]
        if not ids:
            raise ValueError("governance initiative must declare guarantees")
        if len(ids) != len(set(ids)):
            raise ValueError(f"initiative {self.id!r} has duplicate guarantee ids")
        return self


class DetectorObservation(BaseModel):
    guarantee_id: str
    current: int
    target: int
    findings: list[str]


class ProofObservation(BaseModel):
    guarantee_id: str
    proof_id: str
    result: Literal["passed", "failed", "skipped", "xfailed"]
    strength: ProofStrength
    target_sha: str
    occurred_at: datetime
    evidence_url: str
    gate_id: str


class EnforcementObservation(BaseModel):
    gate_id: str
    declared_blocking: bool
    workflow_required: bool
    live_required: bool
    required_context: str | None
    observed_at: datetime


class IssueObservation(BaseModel):
    issue: str
    state: Literal["OPEN", "CLOSED"]
    observed_at: datetime


__all__ = [
    "DetectorObservation",
    "EnforcementObservation",
    "GovernanceGuarantee",
    "GovernanceInitiative",
    "IssueObservation",
    "ProofObservation",
    "ProofStrength",
]
