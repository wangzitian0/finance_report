"""Transitional @ac_proof decorator and metadata dataclass (removed in #2937 Wave 1)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

F = TypeVar("F", bound=Callable[..., object])
PROOF_ATTR = "__ac_proof__"


@dataclass(frozen=True)
class AcProof:
    """Minimal critical-proof metadata container."""

    proof_id: str
    ac_ids: tuple[str, ...]
    stage: str = ""
    task_category: str = ""
    scope: str = "behavioral"
    ci_tier: str = "post_merge_environment"
    trust_mode: str = ""
    source_classes: tuple[str, ...] = ()
    mirror_proof_id: str = ""
    issue: str = ""
    scenario_id: str = ""
    oracle_kind: str = ""
    governance_strength: str = "exact"
    required_observation_kind: str = ""
    required_markers: tuple[str, ...] = ()
    outcomes: tuple[str, ...] = field(default_factory=tuple)


def ac_proof(proof_id: str, *, ac_ids=(), source_classes=(), required_markers=(), outcomes=(), **kwargs) -> Callable[[F], F]:
    """Attach lightweight @ac_proof metadata to a test function."""
    meta = AcProof(
        proof_id=proof_id,
        ac_ids=tuple(ac_ids),
        source_classes=tuple(source_classes),
        required_markers=tuple(required_markers),
        outcomes=tuple(outcomes),
        **kwargs,
    )

    def decorate(func: F) -> F:
        setattr(func, PROOF_ATTR, meta)
        return func

    return decorate
