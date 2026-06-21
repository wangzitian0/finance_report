"""Path/ref/family/proof + gate-target helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - CLI guard
    yaml = None


from common.ssot.governance_report._base import (
    HIGH_RISK_SUBSTRINGS,
    HIGH_RISK_TOKENS,
    MACHINE_KINDS,
    MACHINE_OWNER_SUFFIXES,
    PROOF_MARKERS,
)
from common.ssot.governance_report._types import GovernanceEntry


def _file_part(ref: str) -> str:
    return ref.split("#", 1)[0]


def _as_strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _display_path(path: Path, workspace_root: Path) -> str:
    try:
        return path.relative_to(workspace_root).as_posix()
    except ValueError:
        return path.as_posix()


def _source_relative_path(path: Path, source_root: Path) -> str:
    try:
        return path.relative_to(source_root).as_posix()
    except ValueError:
        return path.as_posix()


def _display_ref(source_root: Path, ref: str, workspace_root: Path) -> str:
    try:
        prefix = source_root.relative_to(workspace_root).as_posix()
    except ValueError:
        prefix = ""
    if not prefix or prefix == ".":
        return ref
    return f"{prefix}/{ref}"


def _infer_family(entry: GovernanceEntry) -> str:
    if entry.family:
        return entry.family

    owner_file = _file_part(entry.owner)
    owner_path = Path(owner_file)
    parts = owner_path.parts
    if len(parts) >= 3 and parts[0] == "docs" and parts[1] == "ssot":
        stem = owner_path.stem
        for delimiter in (".", "-", "_"):
            if delimiter in stem:
                return stem.split(delimiter, 1)[0]
        return stem
    if len(parts) >= 2 and parts[0] == "docs":
        return parts[1]
    if "." in entry.key:
        return entry.key.split(".", 1)[0]
    if "_" in entry.key:
        return entry.key.split("_", 1)[0]
    return "unknown"


def _has_proof(entry: GovernanceEntry) -> bool:
    refs = entry.proofs + entry.cross_refs
    return any(any(marker in ref for marker in PROOF_MARKERS) for ref in refs)


def _is_machine_owned(entry: GovernanceEntry) -> bool:
    owner_file = _file_part(entry.owner).lower()
    return owner_file.endswith(MACHINE_OWNER_SUFFIXES) or (
        (entry.kind or "").lower() in MACHINE_KINDS
    )


def _is_high_risk(entry: GovernanceEntry) -> bool:
    haystack = " ".join((entry.key, entry.owner, entry.description)).lower()
    tokens = set(re.findall(r"[a-z0-9]+", haystack))
    return any(term in haystack for term in HIGH_RISK_SUBSTRINGS) or bool(
        HIGH_RISK_TOKENS & tokens
    )


def _gate_target(system: str, target: str) -> str:
    return f"{system}:{target}"


def _manifest_entry_target(system: str, key: str) -> str:
    return _gate_target(system, f"manifest:{key}")
