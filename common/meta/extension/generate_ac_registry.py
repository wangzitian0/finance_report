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

from common.meta.base.authority_matrix import (
    AC_PROOF_KINDS,
    AC_TIERS,
    TIER_DEFAULT_PROOF_KIND,
)
from common.meta.base.gate_util import (
    call_name,
    expand_test_path,
    parse_acs_table,
    parse_ast_cached,
    read_text_cached,
)

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
_TIER_MARKER_RE = re.compile(
    r"\{tier:\s*(" + "|".join(AC_TIERS) + r")\s*\}", re.IGNORECASE
)
_PROOF_MARKER_RE = re.compile(
    r"\{proof:\s*(" + "|".join(AC_PROOF_KINDS) + r")\s*\}", re.IGNORECASE
)
_TIER_DEFAULT_PROOF = TIER_DEFAULT_PROOF_KIND


def sort_key(ac_id: str) -> tuple[Any, ...]:
    """Total order over legacy numeric ``ACx.y.z`` and package ``AC-<pkg>.<g>.<s>`` IDs."""
    pkg = PKG_AC_PATTERN.fullmatch(ac_id)
    if pkg:
        return (1, pkg.group("package"), pkg.group("group"), int(pkg.group("seq")))
    return (0, "", *(int(p) for p in ac_id[2:].split(".")))


def _strip_marker(
    pattern: re.Pattern[str], text: str, transform: Any = str
) -> tuple[str, str | None]:
    match = pattern.search(text)
    if not match:
        return text, None
    return pattern.sub("", text), transform(match.group(1))


def _extract_tier(text: str) -> tuple[str, str | None]:
    return _strip_marker(_TIER_MARKER_RE, text, str.upper)


def _extract_residue(text: str) -> tuple[str, str | None]:
    return _strip_marker(_RESIDUE_MARKER_RE, text)


def _extract_proof(text: str) -> tuple[str, str | None]:
    return _strip_marker(_PROOF_MARKER_RE, text, str.lower)


def _default_proof_for_tier(tier: str | None) -> str | None:
    return _TIER_DEFAULT_PROOF.get(tier.upper()) if tier else None


def _clean_description(text: str) -> str:
    return text.replace("**", "").replace("`", "").strip()


def _is_reference_only_line(line: str) -> bool:
    stripped = line.strip()
    lower = stripped.lower()
    return (
        (stripped.startswith("*(") and "removed" in lower)
        or "removed as duplicate" in lower
        or "removed as intra-epic" in lower
        or stripped.startswith("- Total AC IDs:")
    )


def _extract_ac_definition(
    line: str,
) -> tuple[str, int, str, str | None, str | None, str | None] | None:
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
        match = AC_PATTERN.fullmatch(cells[0]) if cells else None
        if not match:
            return None
        return (
            match.group(1),
            int(match.group(2)),
            _clean_description(cells[1] if len(cells) > 1 else ""),
            tier,
            proof_kind,
            residue,
        )

    match = re.match(
        r"^(?:[-*]\s*)?(?:\[[ xX]\]\s*)?(?:\*\*)?"
        r"(AC(\d+)\.(\d+)\.(\d+))(?:\*\*)?(?:\s*[:|-])?\s+(.+)$",
        stripped,
    )
    if not match:
        return None
    return (
        match.group(1),
        int(match.group(2)),
        _clean_description(match.group(5)),
        tier,
        proof_kind,
        residue,
    )


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
    resolved = source_dir.resolve()
    parts = resolved.parts
    return (
        resolved.parents[1]
        if len(parts) >= 2 and parts[-2:] == ("docs", "project")
        else resolved
    )


def _const_str(node: ast.AST | None) -> str | None:
    return (
        node.value
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        else None
    )


def _kw_str(call: ast.Call, field: str, default: str | None = None) -> str | None:
    for kw in call.keywords:
        if kw.arg == field:
            return _const_str(kw.value)
    return default


_AC_POS = {
    "id": 0,
    "statement": 1,
    "test": 2,
    "priority": 3,
    "status": 4,
    "proof_kind": 5,
    "vision_anchor": 6,
}


def _ac_record_field(
    call: ast.Call, field: str, default: str | None = None
) -> str | None:
    for kw in call.keywords:
        if kw.arg == field:
            return _const_str(kw.value)
    pos = _AC_POS.get(field)
    if pos is not None and len(call.args) > pos:
        return _const_str(call.args[pos])
    return default


def _expand_ac_id(raw_id: str, prefix: str) -> str:
    return raw_id if raw_id.startswith("AC") or not prefix else f"{prefix}{raw_id}"


def _extract_suite_records(
    call: ast.Call, prefix: str, package_tier: str | None
) -> list[dict]:
    file_prefix = expand_test_path(
        (_const_str(call.args[0]) if call.args else _kw_str(call, "file")) or ""
    )
    def_prio = _kw_str(call, "priority", default="P0") or "P0"
    def_status = _kw_str(call, "status", default="done") or "done"
    def_pk = _kw_str(call, "proof_kind")
    out: list[dict] = []
    for row in call.args[1:] if call.args else ():
        if not isinstance(row, (ast.Tuple, ast.List)) or len(row.elts) < 3:
            continue
        raw_id = _const_str(row.elts[0])
        if not raw_id:
            continue
        test_ref = expand_test_path(_const_str(row.elts[2]) or "")
        out.append(
            {
                "id": _expand_ac_id(raw_id, prefix),
                "statement": _const_str(row.elts[1]) or "",
                "test": (
                    f"{file_prefix}::{test_ref}"
                    if file_prefix and "::" not in test_ref
                    else test_ref
                ),
                "priority": (_const_str(row.elts[3]) if len(row.elts) > 3 else None)
                or def_prio,
                "status": (_const_str(row.elts[4]) if len(row.elts) > 4 else None)
                or def_status,
                "tier": package_tier,
                "proof_kind": (_const_str(row.elts[5]) if len(row.elts) > 5 else None)
                or def_pk,
                "vision_anchor": _const_str(row.elts[6]) if len(row.elts) > 6 else None,
            }
        )
    return out


def _extract_roadmap_expr(
    expr: ast.AST, package_tier: str | None, prefix: str = ""
) -> list[dict]:
    records: list[dict] = []
    if isinstance(expr, ast.Call):
        fn = call_name(expr.func)
        if fn in ("ACRecord", "ac"):
            ac_id = _ac_record_field(expr, "id")
            if ac_id:
                records.append(
                    {
                        "id": _expand_ac_id(ac_id, prefix),
                        "statement": _ac_record_field(expr, "statement") or "",
                        "test": _ac_record_field(expr, "test") or "",
                        "priority": _ac_record_field(expr, "priority", default="P0"),
                        "status": _ac_record_field(expr, "status", default="done"),
                        "tier": package_tier,
                        "proof_kind": _ac_record_field(expr, "proof_kind"),
                        "vision_anchor": _ac_record_field(expr, "vision_anchor"),
                    }
                )
        elif fn == "suite":
            records.extend(_extract_suite_records(expr, prefix, package_tier))
        elif fn == "acs" and expr.args:
            pkg = _const_str(expr.args[0]) or ""
            sub_prefix = f"AC-{pkg}." if pkg else prefix
            for item in expr.args[1:]:
                table_str = _const_str(item)
                records.extend(
                    parse_acs_table(pkg, table_str, package_tier)
                    if table_str is not None
                    else _extract_roadmap_expr(item, package_tier, sub_prefix)
                )
    elif isinstance(expr, (ast.List, ast.Tuple)):
        for elt in expr.elts:
            records.extend(_extract_roadmap_expr(elt, package_tier, prefix))
    return records


def _parse_contract_call(contract_path: Path) -> ast.Call | None:
    tree = parse_ast_cached(contract_path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and call_name(node.func) == "PackageContract":
            return node
    return None


def package_contract_meta(contract_path: Path) -> dict | None:
    """Statically read a contract's package-level metadata (no import / pydantic)."""
    node = _parse_contract_call(contract_path)
    if node is None:
        return None
    package_tier = _ac_record_field(node, "tier")
    roadmap = [
        {"id": rec["id"], "status": rec["status"], "test": rec["test"]}
        for kw in node.keywords
        if kw.arg == "roadmap"
        for rec in _extract_roadmap_expr(kw.value, package_tier)
    ]
    return {
        "name": _ac_record_field(node, "name"),
        "status": _ac_record_field(node, "status"),
        "tier": package_tier,
        "roadmap": roadmap,
    }


def _roadmap_acs_from_contract(contract_path: Path) -> list[dict]:
    """Statically read a contract's ``roadmap`` entries."""
    tree = parse_ast_cached(contract_path)
    records: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and call_name(node.func) == "PackageContract":
            package_tier = _ac_record_field(node, "tier")
            for kw in node.keywords:
                if kw.arg == "roadmap":
                    records.extend(_extract_roadmap_expr(kw.value, package_tier))
    return records


def _package_roadmap_acs(source_dir: Path) -> dict[str, dict]:
    repo_root = _repo_root_for(source_dir)
    acs: dict[str, dict] = {}
    for contract_path in sorted(repo_root.glob("common/*/contract.py")):
        for record in _roadmap_acs_from_contract(contract_path):
            ac_id = record["id"]
            pkg_match = PKG_AC_PATTERN.fullmatch(ac_id)
            if pkg_match:
                ac_epic, epic_name = 0, f"pkg-{pkg_match.group('package')}"
            else:
                match = AC_PATTERN.fullmatch(ac_id)
                if not match:
                    continue
                ac_epic = int(match.group(2))
                epic_name = EPIC_NAMES.get(ac_epic, f"epic-{ac_epic:03d}")
            entry: dict[str, Any] = {
                "epic": ac_epic,
                "epic_name": epic_name,
                "description": _clean_description(record["statement"]),
                "mandatory": True,
                "owner": contract_path.parent.name,
                "test": record["test"],
                "priority": record["priority"],
                "status": record["status"],
                "vision_anchor": record["vision_anchor"],
            }
            if record["tier"]:
                entry["tier"] = record["tier"]
                entry["proof_kind"] = record["proof_kind"] or _default_proof_for_tier(
                    record["tier"]
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
        for line in read_text_cached(path).splitlines():
            definition = _extract_ac_definition(line)
            if definition is None:
                continue
            ac_id, ac_epic, desc, tier, proof_kind, residue = definition
            if residue not in EPIC_RESIDUE_CATEGORIES or ac_id in all_acs:
                continue
            existing = existing_acs.get(ac_id, {})
            entry: dict[str, Any] = {
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
    return dict(
        sorted(
            extract_acs(existing_acs=existing_acs, epic_dir=epic_source).items(),
            key=lambda item: sort_key(item[0]),
        )
    )


def iter_registry_entries(payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for scenario_groups in (payload.get("groups") or {}).values():
        for entries in (scenario_groups or {}).values():
            yield from (dict(entry) for entry in entries or [])


def load_registry_entries(path: Path) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    project_dir = path.parent / "project"
    if not path.exists():
        if project_dir.is_dir():
            for ac_id, source in build_registry_entries(
                epic_source=project_dir
            ).items():
                by_id[ac_id] = {
                    **source,
                    "id": ac_id,
                    "mandatory": bool(source.get("mandatory", True)),
                }
        return [by_id[ac_id] for ac_id in sorted(by_id, key=sort_key)]
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for entry in iter_registry_entries(payload):
        if "id" in entry:
            by_id[str(entry["id"])] = dict(entry)
    return [by_id[ac_id] for ac_id in sorted(by_id, key=sort_key)]
