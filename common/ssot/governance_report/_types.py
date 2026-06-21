"""Governance dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - CLI guard
    yaml = None


from common.ssot.governance_report._base import (
    GATE_HLS_RULE,
    GATE_ISSUE,
)


@dataclass(frozen=True)
class GovernanceEntry:
    key: str
    owner: str
    description: str
    cross_refs: tuple[str, ...]
    proofs: tuple[str, ...]
    family: str | None
    kind: str | None
    parent: str | None
    authority: str | None


@dataclass(frozen=True)
class ManifestSource:
    system: str
    source_root: Path
    manifest_path: Path
    entry_key: str


@dataclass(frozen=True)
class GateViolation:
    code: str
    system: str
    target: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "system": self.system,
            "target": self.target,
            "message": self.message,
            "issue": GATE_ISSUE,
            "hls_rule": GATE_HLS_RULE,
        }
