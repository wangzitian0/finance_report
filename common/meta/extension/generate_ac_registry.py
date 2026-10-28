#!/usr/bin/env python3
"""In-memory AC registry loader from package contracts and marked EPIC residue."""

from __future__ import annotations

import ast
import os
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

# Import the matrix from the stdlib-only source (NOT package_contract, which
# pulls pydantic) so this loader stays importable in the lightweight CI lint
# env (`uv run --with pyyaml ...`).
from common.meta.base.authority_matrix import (
    AC_PROOF_KINDS as _AC_PROOF_KINDS,
)
from common.meta.base.authority_matrix import (
    AC_TIERS as _AC_TIERS,
)
from common.meta.base.authority_matrix import (
    TIER_DEFAULT_PROOF_KIND as _TIER_DEFAULT_PROOF_KIND,
)
from common.meta.base.gate_util import call_name

EPIC_DIR = "docs/project"

EPIC_NAMES: dict[int, str] = {
    1: "phase0-setup",
    2: "double-entry-core",
    3: "statement-parsing",
    4: "reconciliation-engine",
    5: "reporting-visualization",
    6: "ai-advisor",
    7: "deployment",
    8: "testing-strategy",
    9: "pdf-fixture-generation",
    10: "observability-logging",
    11: "asset-lifecycle",
    12: "foundation-libs",
    13: "statement-parsing-v2",
    14: "ttd-transformation",
    15: "processing-account",
    16: "two-stage-review-ui",
    17: "portfolio-management",
    18: "ai-driven-pipeline",
    19: "event-driven-upload-to-report-ux",
    20: "framework-aware-personal-reporting",
    21: "application-ai-advisor",
    22: "everyday-user-ia",
    23: "llm-provider-abstraction",
    24: "frontend-observability",
    25: "dry-ssot-simplification",
    26: "ac-authority-tiers",
}

AC_PATTERN = re.compile(r"\b(AC(\d+)\.(\d+)\.(\d+))\b")

PKG_AC_PATTERN = re.compile(
    r"^AC-(?P<package>[a-z][a-z0-9_]*)\.(?P<group>[a-z0-9][a-z0-9_-]*)\.(?P<seq>\d+)$"
)

EPIC_RESIDUE_CATEGORIES = ("fe-only", "fe-half", "horizontal", "pending-package")

_RESIDUE_MARKER_RE = re.compile(r"<!--\s*epic-owned:\s*([a-z][a-z-]*)\s*-->")

AC_TIERS = _AC_TIERS
AC_PROOF_KINDS = _AC_PROOF_KINDS

_TIER_MARKER_RE = re.compile(
    r"\{tier:\s*(" + "|".join(AC_TIERS) + r")\s*\}", re.IGNORECASE
)

_PROOF_MARKER_RE = re.compile(
    r"\{proof:\s*(" + "|".join(AC_PROOF_KINDS) + r")\s*\}",
    re.IGNORECASE,
)

_TIER_DEFAULT_PROOF = _TIER_DEFAULT_PROOF_KIND


def sort_key(ac_id: str) -> tuple[Any, ...]:
    """Total order over legacy numeric ``ACx.y.z`` and package ``AC-<pkg>.<g>.<s>`` IDs."""
    pkg = PKG_AC_PATTERN.fullmatch(ac_id)
    if pkg:
        return (1, pkg.group("package"), pkg.group("group"), int(pkg.group("seq")))
    return (0, "", *(int(p) for p in ac_id[2:].split(".")))


def _extract_tier(text: str) -> tuple[str, str | None]:
    match = _TIER_MARKER_RE.search(text)
    if not match:
        return text, None
    tier = match.group(1).upper()
    cleaned = _TIER_MARKER_RE.sub("", text)
    return cleaned, tier


def _extract_residue(text: str) -> tuple[str, str | None]:
    match = _RESIDUE_MARKER_RE.search(text)
    if not match:
        return text, None
    return _RESIDUE_MARKER_RE.sub("", text), match.group(1)


def _extract_proof(text: str) -> tuple[str, str | None]:
    match = _PROOF_MARKER_RE.search(text)
    if not match:
        return text, None
    proof_kind = match.group(1).lower()
    cleaned = _PROOF_MARKER_RE.sub("", text)
    return cleaned, proof_kind


def _default_proof_for_tier(tier: str | None) -> str | None:
    if not tier:
        return None
    return _TIER_DEFAULT_PROOF.get(tier.upper())


def _clean_description(text: str) -> str:
    return text.replace("**", "").replace("`", "").strip()


def _is_reference_only_line(line: str) -> bool:
    stripped = line.strip()
    lower = stripped.lower()
    if stripped.startswith("*(") and "removed" in lower:
        return True
    if "removed as duplicate" in lower or "removed as intra-epic" in lower:
        return True
    if stripped.startswith("- Total AC IDs:"):
        return True
    return False


def _extract_ac_definition(
    line: str,
) -> tuple[str, int, str, str | None, str | None, str | None] | None:
    """Extract one AC definition from a Markdown table, bullet, or plain line."""
    if _is_reference_only_line(line):
        return None

    stripped = line.strip()
    if not stripped:
        return None

    stripped, residue = _extract_residue(stripped)
    stripped, tier = _extract_tier(stripped)
    stripped, proof_kind = _extract_proof(stripped)
    stripped = stripped.rstrip()

    if stripped.startswith("|"):
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells:
            return None
        match = AC_PATTERN.fullmatch(cells[0])
        if not match:
            return None
        desc = _clean_description(cells[1] if len(cells) > 1 else "")
        return match.group(1), int(match.group(2)), desc, tier, proof_kind, residue

    match = re.match(
        r"^(?:[-*]\s*)?(?:\[[ xX]\]\s*)?(?:\*\*)?"
        r"(AC(\d+)\.(\d+)\.(\d+))(?:\*\*)?(?:\s*[:|-])?\s+(.+)$",
        stripped,
    )
    if not match:
        return None

    ac_id = match.group(1)
    ac_epic = int(match.group(2))
    desc = _clean_description(match.group(5))
    return ac_id, ac_epic, desc, tier, proof_kind, residue


def _epic_files(epic_dir: str | Path | None = None) -> list[Path]:
    source_dir = Path(epic_dir or EPIC_DIR)
    return [
        source_dir / f
        for f in sorted(os.listdir(source_dir))
        if re.match(r"EPIC-\d+.*\.md", f)
        and "IMPLEMENTATION" not in f
        and "ENCODING" not in f
    ]


def _repo_root_for(source_dir: Path) -> Path:
    """Derive the repo root from the EPIC ``source_dir`` (``<root>/docs/project``)."""
    parts = source_dir.resolve().parts
    if len(parts) >= 2 and parts[-2:] == ("docs", "project"):
        return source_dir.resolve().parents[1]
    return source_dir.resolve()


def _ac_record_field(
    call: ast.Call, field: str, default: str | None = None
) -> str | None:
    """Return the literal string value of an ``ACRecord(...)`` or ``ac(...)`` field, or None."""
    for kw in call.keywords:
        if kw.arg != field:
            continue
        node = kw.value
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return None
    pos_map = {
        "id": 0,
        "statement": 1,
        "test": 2,
        "priority": 3,
        "status": 4,
        "proof_kind": 5,
        "vision_anchor": 6,
    }
    pos = pos_map.get(field)
    if pos is not None and len(call.args) > pos:
        node = call.args[pos]
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return None
    return default


def package_contract_meta(contract_path: Path) -> dict | None:
    """Statically read a contract's package-level metadata (no import / pydantic)."""
    tree = ast.parse(contract_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call) and call_name(node.func) == "PackageContract"
        ):
            continue
        roadmap: list[dict] = []
        for kw in node.keywords:
            if kw.arg != "roadmap" or not isinstance(kw.value, (ast.List, ast.Tuple)):
                continue
            for elt in kw.value.elts:
                if isinstance(elt, ast.Call) and call_name(elt.func) in (
                    "ACRecord",
                    "ac",
                ):
                    ac_id = _ac_record_field(elt, "id")
                    if ac_id:
                        roadmap.append(
                            {
                                "id": ac_id,
                                "status": _ac_record_field(
                                    elt, "status", default="done"
                                ),
                                "test": _ac_record_field(elt, "test"),
                            }
                        )
        return {
            "name": _ac_record_field(node, "name"),
            "status": _ac_record_field(node, "status"),
            "tier": _ac_record_field(node, "tier"),
            "roadmap": roadmap,
        }
    return None


def _roadmap_acs_from_contract(contract_path: Path) -> list[dict]:
    """Statically read a contract's ``roadmap`` ``ACRecord(...)`` or ``ac(...)`` entries."""
    tree = ast.parse(contract_path.read_text(encoding="utf-8"))
    records: list[dict] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call) and call_name(node.func) == "PackageContract"
        ):
            continue
        package_tier = _ac_record_field(node, "tier")
        for kw in node.keywords:
            if kw.arg != "roadmap" or not isinstance(kw.value, (ast.List, ast.Tuple)):
                continue
            for elt in kw.value.elts:
                if not (
                    isinstance(elt, ast.Call)
                    and call_name(elt.func) in ("ACRecord", "ac")
                ):
                    continue
                ac_id = _ac_record_field(elt, "id")
                if not ac_id:
                    continue
                records.append(
                    {
                        "id": ac_id,
                        "statement": _ac_record_field(elt, "statement") or "",
                        "test": _ac_record_field(elt, "test") or "",
                        "priority": _ac_record_field(elt, "priority", default="P0"),
                        "status": _ac_record_field(elt, "status", default="done"),
                        "tier": package_tier,
                        "proof_kind": _ac_record_field(elt, "proof_kind"),
                        "vision_anchor": _ac_record_field(elt, "vision_anchor"),
                    }
                )
    return records


def _package_roadmap_acs(source_dir: Path) -> dict[str, dict]:
    """Source ACs from every ``<root>/common/<pkg>/contract.py`` ``roadmap``."""
    repo_root = _repo_root_for(source_dir)
    acs: dict[str, dict] = {}
    for contract_path in sorted(repo_root.glob("common/*/contract.py")):
        for record in _roadmap_acs_from_contract(contract_path):
            ac_id = record["id"]
            pkg_match = PKG_AC_PATTERN.fullmatch(ac_id)
            if pkg_match:
                package = pkg_match.group("package")
                entry = {
                    "epic": 0,
                    "epic_name": f"pkg-{package}",
                    "description": _clean_description(record["statement"]),
                    "mandatory": True,
                }
            else:
                match = AC_PATTERN.fullmatch(ac_id)
                if not match:
                    continue
                ac_epic = int(match.group(2))
                entry = {
                    "epic": ac_epic,
                    "epic_name": EPIC_NAMES.get(ac_epic, f"epic-{ac_epic:03d}"),
                    "description": _clean_description(record["statement"]),
                    "mandatory": True,
                }
            tier = record["tier"]
            if tier:
                entry["tier"] = tier
                entry["proof_kind"] = record["proof_kind"] or _default_proof_for_tier(
                    tier
                )
            entry.update(
                {
                    "owner": contract_path.parent.name,
                    "test": record["test"],
                    "priority": record["priority"],
                    "status": record["status"],
                    "vision_anchor": record["vision_anchor"],
                }
            )
            if ac_id in acs:
                raise ValueError(
                    f"duplicate package roadmap AC id {ac_id!r}; registry generation "
                    "refuses last-write-wins projection"
                )
            acs[ac_id] = entry
    return acs


def extract_acs(
    existing_acs: dict[str, dict] | str | Path | None = None,
    epic_dir: str | Path | None = None,
) -> dict[str, dict]:
    if isinstance(existing_acs, (str, Path)):
        epic_dir = existing_acs
        existing_acs = None
    source_dir = Path(epic_dir or EPIC_DIR)
    existing_acs = existing_acs or {}
    all_acs: dict[str, dict] = {}
    for path in _epic_files(source_dir):
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()

        for line in lines:
            definition = _extract_ac_definition(line)
            if definition is None:
                continue
            ac_id, ac_epic, desc, tier, proof_kind, residue = definition
            if residue not in EPIC_RESIDUE_CATEGORIES:
                continue
            if ac_id in all_acs:
                continue

            existing = existing_acs.get(ac_id, {})
            entry = {
                "id": ac_id,
                "epic": int(existing.get("epic", ac_epic)),
                "epic_name": existing.get(
                    "epic_name", EPIC_NAMES.get(ac_epic, f"epic-{ac_epic:03d}")
                ),
                "description": existing.get("description", desc),
                "mandatory": existing.get("mandatory", True),
            }
            ac_tier = tier or existing.get("tier")
            if ac_tier:
                entry["tier"] = ac_tier
                entry["proof_kind"] = (
                    proof_kind
                    or existing.get("proof_kind")
                    or _default_proof_for_tier(ac_tier)
                )
            all_acs[ac_id] = entry

    all_acs.update(_package_roadmap_acs(source_dir))
    return all_acs


def build_registry_entries(
    existing_acs: dict[str, dict] | None = None,
    epic_source: str | Path | None = None,
) -> dict[str, dict]:
    """Return the complete current registry from in-memory EPIC residue and package roadmaps."""
    extracted = extract_acs(existing_acs=existing_acs, epic_dir=epic_source)
    return dict(sorted(extracted.items(), key=lambda item: sort_key(item[0])))


def iter_registry_entries(payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """Yield registry entries from the grouped ACx -> ACx.y registry payload."""
    groups = payload.get("groups") or {}
    for _epic_key, scenario_groups in groups.items():
        for _scenario_key, entries in (scenario_groups or {}).items():
            yield from (dict(entry) for entry in entries or [])


def load_registry_entries(path: Path) -> list[dict[str, Any]]:
    """Load AC registry entries from in-memory EPIC/package sources or a test YAML fixture."""
    by_id: dict[str, dict[str, Any]] = {}
    project_dir = path.parent / "project"
    if not path.exists():
        if project_dir.is_dir():
            for ac_id, source in build_registry_entries(
                epic_source=project_dir
            ).items():
                entry = dict(source)
                entry["id"] = ac_id
                entry["mandatory"] = bool(entry.get("mandatory", True))
                by_id[ac_id] = entry
        return [by_id[ac_id] for ac_id in sorted(by_id, key=sort_key)]

    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for entry in iter_registry_entries(payload):
        if "id" in entry:
            by_id[str(entry["id"])] = dict(entry)
    return [by_id[ac_id] for ac_id in sorted(by_id, key=sort_key)]
