"""Discover and validate exact ownership of SQLAlchemy delete cascades."""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

INVENTORY_PATH = Path(__file__).resolve().parents[1] / "data/fk-cascade-ownership.json"
DEBT_BASELINE_PATH = (
    Path(__file__).resolve().parents[1] / "data/fk-cascade-debt-baseline.json"
)

CascadeClass = Literal[
    "aggregate_internal",
    "purge_owned",
    "cross_domain",
    "retention_sensitive",
]
_CLASSES = {
    "aggregate_internal",
    "purge_owned",
    "cross_domain",
    "retention_sensitive",
}


class CascadeInventoryError(ValueError):
    """The discovered cascade graph and its reviewed inventory disagree."""


@dataclass(frozen=True, order=True)
class CascadeSite:
    """One scalar or composite CASCADE realized on a mapped table."""

    site: str
    source_owner: str
    target_table: str
    target_owner: str


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


def _constructor_aliases(tree: ast.Module) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or not (node.module or "").startswith(
            "sqlalchemy"
        ):
            continue
        for imported in node.names:
            if imported.name in {"ForeignKey", "ForeignKeyConstraint"}:
                aliases[imported.asname or imported.name] = imported.name
    return aliases


def _import_aliases(tree: ast.Module) -> dict[str, str]:
    return {
        imported.asname: imported.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        for imported in node.names
        if imported.asname is not None
    }


def _call_argument(call: ast.Call, keyword: str, position: int) -> ast.expr | None:
    keyword_values = [item.value for item in call.keywords if item.arg == keyword]
    positional = call.args[position] if len(call.args) > position else None
    if keyword_values and positional is not None:
        raise CascadeInventoryError(
            f"{_call_name(call)} provides {keyword} both positionally and by keyword"
        )
    return keyword_values[0] if keyword_values else positional


def _cascade_target(
    node: ast.AST, aliases: dict[str, str]
) -> tuple[str, str, str | None] | None:
    if not isinstance(node, ast.Call):
        return None
    syntactic_name = _call_name(node)
    call_name = aliases.get(syntactic_name or "", syntactic_name)
    if call_name not in {"ForeignKey", "ForeignKeyConstraint"}:
        return None
    if any(isinstance(argument, ast.Starred) for argument in node.args) or any(
        keyword.arg is None for keyword in node.keywords
    ):
        raise CascadeInventoryError(
            f"{call_name} uses unpacked arguments that ownership review cannot resolve"
        )
    ondelete_position = 5 if call_name == "ForeignKey" else 4
    ondelete = _call_argument(node, "ondelete", ondelete_position)
    if ondelete is None:
        return None
    if not (isinstance(ondelete, ast.Constant) and isinstance(ondelete.value, str)):
        raise CascadeInventoryError(
            f"{call_name} ondelete must be a literal for ownership review"
        )
    if ondelete.value.strip().upper() != "CASCADE":
        return None
    if call_name == "ForeignKey":
        if not node.args:
            raise CascadeInventoryError("CASCADE ForeignKey has no target argument")
        target = node.args[0]
        if not (isinstance(target, ast.Constant) and isinstance(target.value, str)):
            raise CascadeInventoryError(
                "CASCADE ForeignKey target must be a literal for ownership review"
            )
        target_value = target.value
        return target_value, target_value.split(".", 1)[0], None

    if len(node.args) < 2:
        raise CascadeInventoryError(
            "CASCADE ForeignKeyConstraint has no remote target argument"
        )
    remote_targets = node.args[1]
    if not isinstance(remote_targets, (ast.List, ast.Tuple)) or not remote_targets.elts:
        raise CascadeInventoryError(
            "CASCADE ForeignKeyConstraint remote targets must be literal strings"
        )
    targets = tuple(
        element.value
        for element in remote_targets.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    )
    if len(targets) != len(remote_targets.elts):
        raise CascadeInventoryError(
            "CASCADE ForeignKeyConstraint remote targets must be literal strings"
        )
    constraint_name_node = _call_argument(node, "name", 2)
    if not (
        isinstance(constraint_name_node, ast.Constant)
        and isinstance(constraint_name_node.value, str)
    ):
        raise CascadeInventoryError(
            "CASCADE ForeignKeyConstraint must have a literal name"
        )
    constraint_name = constraint_name_node.value
    target_tables = {target.split(".", 1)[0] for target in targets}
    if len(target_tables) != 1:
        raise CascadeInventoryError(
            "CASCADE ForeignKeyConstraint must reference one target table"
        )
    return "+".join(targets), next(iter(target_tables)), constraint_name


def _literal_tablename(node: ast.ClassDef) -> str | None:
    for statement in node.body:
        field, value = _assigned_name(statement)
        if (
            field == "__tablename__"
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
        ):
            return value.value
    return None


def _parent_map(tree: ast.Module) -> dict[ast.AST, ast.AST]:
    return {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }


def _enclosing_class(
    node: ast.AST, parents: dict[ast.AST, ast.AST]
) -> ast.ClassDef | None:
    cursor = node
    while cursor in parents:
        cursor = parents[cursor]
        if isinstance(cursor, ast.ClassDef):
            return cursor
    return None


def _assigned_field(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str | None:
    cursor = node
    while cursor in parents:
        cursor = parents[cursor]
        if isinstance(cursor, ast.stmt):
            field, _value = _assigned_name(cursor)
            if field is not None:
                return field
    return None


def _base_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _defines_field(node: ast.ClassDef, field: str) -> bool:
    return any(_assigned_name(statement)[0] == field for statement in node.body)


def _mixin_consumers(
    mixin: ast.ClassDef,
    field: str,
    parsed_sources: Sequence[tuple[Path, str, ast.Module]],
) -> tuple[tuple[Path, str, ast.ClassDef], ...]:
    definitions: dict[str, list[ast.ClassDef]] = {}
    aliases_by_class: dict[ast.ClassDef, dict[str, str]] = {}
    for _relative, _source_owner, tree in parsed_sources:
        aliases = _import_aliases(tree)
        for candidate in ast.walk(tree):
            if isinstance(candidate, ast.ClassDef):
                definitions.setdefault(candidate.name, []).append(candidate)
                aliases_by_class[candidate] = aliases

    def inherits_through_mixins(
        candidate: ast.ClassDef, ancestor: str, seen: frozenset[str]
    ) -> bool:
        for base in candidate.bases:
            base_name = _base_name(base)
            if base_name is None:
                continue
            base_name = aliases_by_class.get(candidate, {}).get(base_name, base_name)
            if base_name == ancestor:
                return True
            if base_name in seen:
                continue
            for intermediate in definitions.get(base_name, []):
                if _literal_tablename(intermediate) is not None:
                    continue
                if _defines_field(intermediate, field):
                    continue
                if inherits_through_mixins(intermediate, ancestor, seen | {base_name}):
                    return True
        return False

    consumers: list[tuple[Path, str, ast.ClassDef]] = []
    for relative, source_owner, tree in parsed_sources:
        for candidate in ast.walk(tree):
            if not isinstance(candidate, ast.ClassDef):
                continue
            if _literal_tablename(candidate) is None:
                continue
            if not inherits_through_mixins(candidate, mixin.name, frozenset()):
                continue
            if _defines_field(candidate, field):
                continue
            consumers.append((relative, source_owner, candidate))
    return tuple(consumers)


def _site_label(node: ast.Call, parents: dict[ast.AST, ast.AST]) -> str:
    column_name: str | None = None
    cursor: ast.AST = node
    while cursor in parents:
        cursor = parents[cursor]
        if (
            isinstance(cursor, ast.Call)
            and _call_name(cursor) == "Column"
            and cursor.args
            and isinstance(cursor.args[0], ast.Constant)
            and isinstance(cursor.args[0].value, str)
        ):
            column_name = cursor.args[0].value
        field, _value = (
            _assigned_name(cursor) if isinstance(cursor, ast.stmt) else (None, None)
        )
        if field is None:
            continue

        scopes: list[str] = []
        scope_cursor = cursor
        while scope_cursor in parents:
            scope_cursor = parents[scope_cursor]
            if isinstance(
                scope_cursor, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                scopes.append(scope_cursor.name)
        label_parts = [*reversed(scopes), field]
        if column_name is not None and column_name != field:
            label_parts.append(column_name)
        return ".".join(label_parts)
    return f"line_{node.lineno}_{node.col_offset}"


def _table_owners(
    parsed_sources: Sequence[tuple[Path, str, ast.Module]],
) -> dict[str, str]:
    owners: dict[str, set[str]] = {}
    for _relative, source_owner, tree in parsed_sources:
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            table = _literal_tablename(node)
            if table is not None:
                owners.setdefault(table, set()).add(source_owner)

    resolved: dict[str, str] = {}
    for table, table_owners in owners.items():
        if len(table_owners) != 1:
            raise CascadeInventoryError(
                f"table {table!r} has ambiguous owner packages {sorted(table_owners)}"
            )
        resolved[table] = next(iter(table_owners))
    return resolved


def discover_cascades(source_root: Path) -> tuple[CascadeSite, ...]:
    """Return every literal production cascade declaration, or fail closed."""

    parsed_sources: list[tuple[Path, str, ast.Module]] = []
    for source_path in sorted(source_root.rglob("*.py")):
        if "__pycache__" in source_path.parts:
            continue
        relative = source_path.relative_to(source_root)
        parsed_sources.append(
            (
                relative,
                relative.parts[0],
                ast.parse(
                    source_path.read_text(encoding="utf-8"), filename=str(source_path)
                ),
            )
        )

    table_owners = _table_owners(parsed_sources)
    sites: list[CascadeSite] = []
    for relative, source_owner, tree in parsed_sources:
        parents = _parent_map(tree)
        aliases = _constructor_aliases(tree)
        for node in ast.walk(tree):
            target_details = _cascade_target(node, aliases)
            if target_details is None:
                continue
            target, target_table, constraint_name = target_details
            label = _site_label(node, parents)
            if constraint_name is not None:
                label = f"{label}.{constraint_name}"
            origins = [(relative, source_owner, label)]
            enclosing_class = _enclosing_class(node, parents)
            if (
                enclosing_class is not None
                and _literal_tablename(enclosing_class) is None
            ):
                field = _assigned_field(node, parents)
                if field is None:
                    raise CascadeInventoryError(
                        f"{relative.as_posix()}::{label}: mixin CASCADE has no stable field"
                    )
                consumers = _mixin_consumers(enclosing_class, field, parsed_sources)
                if not consumers:
                    raise CascadeInventoryError(
                        f"{relative.as_posix()}::{label}: mixin CASCADE has no mapped consumers"
                    )
                origins = [
                    (
                        consumer_relative,
                        consumer_owner,
                        label.replace(
                            f"{enclosing_class.name}.",
                            f"{consumer.name}.",
                            1,
                        ),
                    )
                    for consumer_relative, consumer_owner, consumer in consumers
                ]

            for origin_relative, origin_owner, origin_label in origins:
                site = f"{origin_relative.as_posix()}::{origin_label}->{target}"
                target_owner = table_owners.get(target_table)
                if target_owner is None:
                    raise CascadeInventoryError(
                        f"{site}: target table {target_table!r} has no literal table owner"
                    )
                sites.append(
                    CascadeSite(
                        site=site,
                        source_owner=origin_owner,
                        target_table=target_table,
                        target_owner=target_owner,
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


def load_debt_baseline(path: Path) -> frozenset[str]:
    """Load the exact set of reviewed cascade debt sites."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CascadeInventoryError(
            f"cannot read cascade debt baseline: {path}"
        ) from exc
    if not isinstance(payload, dict) or set(payload) != {"debt_sites"}:
        raise CascadeInventoryError(
            "cascade debt baseline must contain exactly the debt_sites key"
        )
    debt_sites = payload["debt_sites"]
    if not isinstance(debt_sites, list) or not all(
        isinstance(site, str) and site for site in debt_sites
    ):
        raise CascadeInventoryError(
            "cascade debt baseline debt_sites must be a list of non-empty strings"
        )
    if len(set(debt_sites)) != len(debt_sites):
        raise CascadeInventoryError("cascade debt baseline contains duplicate sites")
    return frozenset(debt_sites)


def validate_debt_ratchet(
    inventory: Sequence[CascadeOwnership], baseline: frozenset[str]
) -> None:
    """Reject new debt and force resolved sites out of the shrink-only baseline."""

    current = {
        record.site
        for record in inventory
        if record.classification != "aggregate_internal"
    }
    new = sorted(current - baseline)
    stale = sorted(baseline - current)
    if new:
        raise CascadeInventoryError(f"cascade debt grew; new={new}")
    if stale:
        raise CascadeInventoryError(
            f"resolved debt remains baselined and must be pruned; stale={stale}"
        )


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
        if record.target_owner != site.target_owner:
            raise CascadeInventoryError(
                f"{key}: target_owner must be {site.target_owner!r}"
            )
        if len(record.rationale.strip()) < 12:
            raise CascadeInventoryError(f"{key}: rationale is not reviewable")

        same_owner = site.source_owner == site.target_owner
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
        elif record.classification == "cross_domain":
            if same_owner or site.target_table == "users":
                raise CascadeInventoryError(
                    f"{key}: cross_domain requires different owners and a non-user target"
                )
            if record.issue != "#1848":
                raise CascadeInventoryError(f"{key}: cross-domain debt must name #1848")
        elif record.classification == "retention_sensitive":
            if not same_owner:
                raise CascadeInventoryError(
                    f"{key}: retention_sensitive requires the same source/target owner"
                )
            if record.issue != "#1848":
                raise CascadeInventoryError(
                    f"{key}: retention-sensitive debt must name #1848"
                )
        else:  # pragma: no cover - load_inventory rejects this shape
            raise CascadeInventoryError(f"{key}: unknown classification")
