"""Discover and validate exact ownership of SQLAlchemy delete cascades."""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

INVENTORY_PATH = Path(__file__).resolve().parents[1] / "data/fk-cascade-ownership.json"

CascadeClass = Literal["aggregate_internal", "purge_owned", "cross_domain"]
_CLASSES = {"aggregate_internal", "purge_owned", "cross_domain"}


class CascadeInventoryError(ValueError):
    """The discovered cascade graph and its reviewed inventory disagree."""


@dataclass(frozen=True, order=True)
class CascadeSite:
    """One literal ``ForeignKey(..., ondelete="CASCADE")`` declaration."""

    site: str
    source_owner: str
    target_table: str


@dataclass(frozen=True)
class CascadeOwnership:
    """Reviewed ownership decision for one cascade declaration."""

    site: str
    source_owner: str
    target_owner: str
    classification: CascadeClass
    rationale: str
    issue: str | None = None


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    if isinstance(call.func, ast.Name):
        return call.func.id
    return None


def _assigned_name(statement: ast.stmt) -> tuple[str | None, ast.AST | None]:
    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
        return statement.target.id, statement.value
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
        target = statement.targets[0]
        if isinstance(target, ast.Name):
            return target.id, statement.value
    return None, None


def _cascade_target(value: ast.AST | None) -> list[str]:
    if value is None:
        return []
    targets: list[str] = []
    for node in ast.walk(value):
        if not isinstance(node, ast.Call) or _call_name(node) != "ForeignKey":
            continue
        ondelete = next(
            (keyword.value for keyword in node.keywords if keyword.arg == "ondelete"),
            None,
        )
        if not (isinstance(ondelete, ast.Constant) and ondelete.value == "CASCADE"):
            continue
        if not node.args:
            raise CascadeInventoryError("CASCADE ForeignKey has no target argument")
        target = node.args[0]
        if not (isinstance(target, ast.Constant) and isinstance(target.value, str)):
            raise CascadeInventoryError(
                "CASCADE ForeignKey target must be a literal for ownership review"
            )
        targets.append(target.value)
    return targets


def discover_cascades(source_root: Path) -> tuple[CascadeSite, ...]:
    """Return every literal production cascade declaration, or fail closed."""

    sites: list[CascadeSite] = []
    for source_path in sorted(source_root.rglob("*.py")):
        if "__pycache__" in source_path.parts:
            continue
        relative = source_path.relative_to(source_root)
        source_owner = relative.parts[0]
        tree = ast.parse(
            source_path.read_text(encoding="utf-8"), filename=str(source_path)
        )
        for class_node in (
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ):
            for statement in class_node.body:
                field, value = _assigned_name(statement)
                if field is None:
                    continue
                for target in _cascade_target(value):
                    target_table = target.split(".", 1)[0]
                    site = f"{relative.as_posix()}::{class_node.name}.{field}->{target}"
                    sites.append(
                        CascadeSite(
                            site=site,
                            source_owner=source_owner,
                            target_table=target_table,
                        )
                    )

    if not sites:
        raise CascadeInventoryError(
            f"no CASCADE declarations discovered under {source_root}"
        )
    if len({site.site for site in sites}) != len(sites):
        raise CascadeInventoryError("cascade discovery produced duplicate site keys")
    return tuple(sorted(sites))


def load_inventory(path: Path) -> tuple[CascadeOwnership, ...]:
    """Load the reviewed inventory with strict keys and duplicate rejection."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CascadeInventoryError(f"cannot read cascade inventory: {path}") from exc
    if not isinstance(payload, list) or not payload:
        raise CascadeInventoryError("cascade inventory must be a non-empty list")

    records: list[CascadeOwnership] = []
    required = {
        "site",
        "source_owner",
        "target_owner",
        "classification",
        "rationale",
        "issue",
    }
    for index, raw in enumerate(payload):
        if not isinstance(raw, dict) or set(raw) != required:
            raise CascadeInventoryError(
                f"inventory record {index} must have exactly {sorted(required)}"
            )
        if raw["classification"] not in _CLASSES:
            raise CascadeInventoryError(
                f"inventory record {index} has unknown classification"
            )
        records.append(CascadeOwnership(**raw))
    if len({record.site for record in records}) != len(records):
        raise CascadeInventoryError("cascade inventory contains duplicate sites")
    return tuple(records)


def validate_inventory(
    sites: Sequence[CascadeSite], inventory: Sequence[CascadeOwnership]
) -> None:
    """Require exact discovery coverage and internally coherent decisions."""

    discovered = {site.site: site for site in sites}
    reviewed = {record.site: record for record in inventory}
    if discovered.keys() != reviewed.keys():
        missing = sorted(discovered.keys() - reviewed.keys())
        stale = sorted(reviewed.keys() - discovered.keys())
        raise CascadeInventoryError(
            "cascade inventory does not equal discovery; "
            f"missing={missing}, stale={stale}"
        )

    for key, site in discovered.items():
        record = reviewed[key]
        if record.source_owner != site.source_owner:
            raise CascadeInventoryError(
                f"{key}: source_owner must be {site.source_owner!r}"
            )
        if len(record.rationale.strip()) < 12:
            raise CascadeInventoryError(f"{key}: rationale is not reviewable")

        same_owner = record.source_owner == record.target_owner
        if record.classification == "aggregate_internal":
            if not same_owner:
                raise CascadeInventoryError(
                    f"{key}: aggregate_internal requires the same source/target owner"
                )
            if record.issue is not None:
                raise CascadeInventoryError(
                    f"{key}: approved aggregate_internal survivor cannot carry debt"
                )
        elif record.classification == "purge_owned":
            if site.target_table != "users" or same_owner:
                raise CascadeInventoryError(
                    f"{key}: purge_owned is only valid for cross-owner users FKs"
                )
            if record.issue != "#1848":
                raise CascadeInventoryError(f"{key}: purge-owned debt must name #1848")
        else:
            if same_owner or site.target_table == "users":
                raise CascadeInventoryError(
                    f"{key}: cross_domain requires different owners and a non-user target"
                )
            if record.issue != "#1848":
                raise CascadeInventoryError(f"{key}: cross-domain debt must name #1848")
