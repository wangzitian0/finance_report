"""Dependency topology and public-boundary impact reporting.

This extension owns filesystem, AST, and Git-ref I/O. The dependency graph
itself remains a pure ``base`` computation so both this report and the ``data``
projection use one policy implementation.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from common.meta.base.dependency_graph import build_dependency_graph


@dataclass(frozen=True)
class SnapshotPackage:
    """Neutral package facts read from a contract without importing its model."""

    name: str
    depends_on: tuple[str, ...]
    interface: tuple[str, ...]
    impl_dir: Path | None


@dataclass(frozen=True)
class _ResolvedExport:
    signature: str
    binding: str
    source: Path
    reexported: bool


_ResolutionKey = tuple[Path, str, int | None]


def _annotation(node: ast.expr | None) -> str:
    return ast.unparse(node) if node is not None else "Any"


def _decorator_prefix(nodes: list[ast.expr]) -> str:
    return "".join(f"@{ast.unparse(node)} " for node in nodes)


def _type_parameters(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
) -> str:
    parameters = getattr(node, "type_params", [])
    if not parameters:
        return ""
    return f"[{', '.join(ast.unparse(parameter) for parameter in parameters)}]"


def _module_values(body: Sequence[ast.stmt]) -> dict[str, ast.expr]:
    values: dict[str, ast.expr] = {}
    for node in body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            values[node.targets[0].id] = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            values[node.target.id] = node.value
    return values


def _value_fingerprint(
    name: str, values: dict[str, ast.expr], seen: frozenset[str] = frozenset()
) -> str:
    value = values[name]
    references = sorted(
        {
            child.id
            for child in ast.walk(value)
            if isinstance(child, ast.Name)
            and child.id in values
            and child.id not in seen
            and child.id != name
        }
    )
    dependencies = [
        f"{reference}={_value_fingerprint(reference, values, seen | {name})}"
        for reference in references
    ]
    suffix = f" [{', '.join(dependencies)}]" if dependencies else ""
    return f"{ast.unparse(value)}{suffix}"


def _resolved_default_values(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    values: dict[str, ast.expr],
) -> str:
    defaults = [*node.args.defaults]
    defaults.extend(default for default in node.args.kw_defaults if default is not None)
    references = sorted(
        {
            child.id
            for default in defaults
            for child in ast.walk(default)
            if isinstance(child, ast.Name) and child.id in values
        }
    )
    if not references:
        return ""
    resolved = ", ".join(
        f"{name}={_value_fingerprint(name, values)}" for name in references
    )
    return f" [defaults: {resolved}]"


def _function_signature(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    values: dict[str, ast.expr] | None = None,
) -> str:
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return (
        f"{_decorator_prefix(node.decorator_list)}{prefix}{_type_parameters(node)}"
        f"({ast.unparse(node.args)}) -> {_annotation(node.returns)}"
        f"{_resolved_default_values(node, values or {})}"
    )


def _annotated_assignment_signature(node: ast.AnnAssign) -> str:
    signature = _annotation(node.annotation)
    if node.value is not None:
        signature += f"={ast.unparse(node.value)}"
    return signature


def _is_public_method(name: str) -> bool:
    return not name.startswith("_") or (name.startswith("__") and name.endswith("__"))


def _base_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Subscript):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _project_base_signature(
    source: Path,
    body: list[ast.stmt],
    base_name: str,
    repo_root: Path,
    seen: frozenset[_ResolutionKey],
    before_index: int,
) -> str | None:
    for node in reversed(body[:before_index]):
        if isinstance(node, ast.ClassDef) and node.name == base_name:
            resolved = _resolve_export(
                source,
                base_name,
                repo_root,
                seen,
                before_index=before_index,
            )
            return resolved.signature if resolved is not None else None
        if not isinstance(node, ast.ImportFrom):
            continue
        if not any((alias.asname or alias.name) == base_name for alias in node.names):
            continue
        if _import_source(source, node, repo_root) is None:
            return None
        resolved = _resolve_export(
            source,
            base_name,
            repo_root,
            seen,
            before_index=before_index,
        )
        return resolved.signature if resolved is not None else None
    return None


def _class_signature(
    node: ast.ClassDef,
    *,
    module_body: list[ast.stmt],
    values: dict[str, ast.expr],
    source: Path,
    repo_root: Path,
    seen: frozenset[_ResolutionKey],
    definition_index: int,
) -> str:
    bases = [ast.unparse(base) for base in node.bases]
    bases.extend(
        f"{keyword.arg}={ast.unparse(keyword.value)}"
        if keyword.arg is not None
        else f"**{ast.unparse(keyword.value)}"
        for keyword in node.keywords
    )
    members: list[str] = []
    for base in node.bases:
        name = _base_name(base)
        if name is None:
            continue
        signature = _project_base_signature(
            source,
            module_body,
            name,
            repo_root,
            seen,
            definition_index,
        )
        if signature is not None:
            members.append(f"inherits[{ast.unparse(base)}]={signature}")
    for child in node.body:
        if (
            isinstance(child, ast.AnnAssign)
            and isinstance(child.target, ast.Name)
            and not child.target.id.startswith("_")
        ):
            members.append(
                f"{child.target.id}: {_annotated_assignment_signature(child)}"
            )
        elif isinstance(child, ast.Assign):
            for target in child.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    members.append(f"{target.id}={ast.unparse(child.value)}")
        elif isinstance(
            child, (ast.FunctionDef, ast.AsyncFunctionDef)
        ) and _is_public_method(child.name):
            signature = _function_signature(child, values)
            marker = "async def" if isinstance(child, ast.AsyncFunctionDef) else "def"
            members.append(signature.replace(marker, child.name, 1))
    body = "; ".join(members)
    return (
        f"{_decorator_prefix(node.decorator_list)}class{_type_parameters(node)}"
        f"({', '.join(bases)}){{{body}}}"
    )


def _definition_signature(
    node: ast.stmt,
    symbol: str,
    *,
    module_body: list[ast.stmt],
    values: dict[str, ast.expr],
    source: Path,
    repo_root: Path,
    seen: frozenset[_ResolutionKey],
    definition_index: int,
) -> str | None:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return _function_signature(node, values) if node.name == symbol else None
    if isinstance(node, ast.ClassDef):
        return (
            _class_signature(
                node,
                module_body=module_body,
                values=values,
                source=source,
                repo_root=repo_root,
                seen=seen,
                definition_index=definition_index,
            )
            if node.name == symbol
            else None
        )
    if (
        isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == symbol
    ):
        return f"value: {_annotated_assignment_signature(node)}"
    if isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == symbol for target in node.targets
    ):
        return f"value={ast.unparse(node.value)}"
    return None


def _is_overload(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        (isinstance(decorator, ast.Name) and decorator.id == "overload")
        or (isinstance(decorator, ast.Attribute) and decorator.attr == "overload")
        for decorator in node.decorator_list
    )


def _assigned_alias_target(node: ast.stmt, symbol: str) -> str | None:
    value: ast.expr | None = None
    if isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == symbol for target in node.targets
    ):
        value = node.value
    elif (
        isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == symbol
    ):
        value = node.value
    return value.id if isinstance(value, ast.Name) else None


def _module_definition_signature(
    body: list[ast.stmt],
    index: int,
    symbol: str,
    *,
    source: Path,
    repo_root: Path,
    seen: frozenset[_ResolutionKey],
) -> str | None:
    node = body[index]
    values = _module_values(body[:index])
    signature = _definition_signature(
        node,
        symbol,
        module_body=body,
        values=values,
        source=source,
        repo_root=repo_root,
        seen=seen,
        definition_index=index,
    )
    if signature is None or not isinstance(
        node, (ast.FunctionDef, ast.AsyncFunctionDef)
    ):
        return signature
    overloads = [
        candidate
        for candidate in body[:index]
        if isinstance(candidate, (ast.FunctionDef, ast.AsyncFunctionDef))
        and candidate.name == symbol
        and _is_overload(candidate)
    ]
    definitions = overloads if _is_overload(node) else [*overloads, node]
    if _is_overload(node):
        definitions.append(node)
    return " | ".join(
        _function_signature(definition, values) for definition in definitions
    )


def _module_source(base: Path) -> Path | None:
    source = base.with_suffix(".py")
    if source.is_file():
        return source
    init_source = base / "__init__.py"
    return init_source if init_source.is_file() else None


def _absolute_module_source(source: Path, module: str, repo_root: Path) -> Path | None:
    module_parts = module.split(".")
    anchor = source.parent
    while anchor == repo_root or repo_root in anchor.parents:
        candidate = _module_source(anchor.joinpath(*module_parts))
        if candidate is not None:
            return candidate
        if anchor == repo_root:
            break
        anchor = anchor.parent
    return None


def _import_source(source: Path, node: ast.ImportFrom, repo_root: Path) -> Path | None:
    module_parts = (node.module or "").split(".") if node.module else []
    if node.level:
        anchor = source.parent
        for _ in range(node.level - 1):
            anchor = anchor.parent
        return _module_source(anchor.joinpath(*module_parts))
    return _absolute_module_source(source, node.module or "", repo_root)


def _import_binding(node: ast.ImportFrom, symbol: str) -> str:
    module = "." * node.level + (node.module or "")
    separator = "" if module.endswith(".") else "."
    return f"{module}{separator}{symbol}"


_UNKNOWN = object()


def _literal_value(node: ast.expr) -> object:
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "frozenset"
            and len(node.args) == 1
        ):
            try:
                return frozenset(ast.literal_eval(node.args[0]))
            except (ValueError, TypeError, SyntaxError):
                pass
    return _UNKNOWN


def _wildcard_exports(source: Path, symbol: str) -> bool:
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for node in reversed(tree.body):
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            value = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "__all__"
        ):
            value = node.value
        if value is None:
            continue
        exported = _literal_value(value)
        if not isinstance(exported, (list, tuple, set, frozenset)) or not all(
            isinstance(item, str) for item in exported
        ):
            raise RuntimeError(f"{source}: wildcard target has non-literal __all__")
        return symbol in exported
    return not symbol.startswith("_")


def _lazy_constants(
    tree: ast.Module,
) -> tuple[dict[str, set[str]], dict[str, dict[str, str]]]:
    collections: dict[str, set[str]] = {}
    module_maps: dict[str, dict[str, str]] = {}
    for node in tree.body:
        name: str | None = None
        value: ast.expr | None = None
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            name = node.targets[0].id
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            value = node.value
        if name is None or value is None:
            continue
        literal = _literal_value(value)
        if isinstance(literal, dict) and all(
            isinstance(key, str) and isinstance(item, str)
            for key, item in literal.items()
        ):
            module_maps[name] = dict(literal)
        elif isinstance(literal, (set, frozenset, list, tuple)) and all(
            isinstance(item, str) for item in literal
        ):
            collections[name] = set(literal)
    return collections, module_maps


def _expression_value(
    node: ast.expr,
    symbol: str,
    collections: dict[str, set[str]],
    strings: dict[str, str | None],
) -> object:
    if isinstance(node, ast.Name):
        if node.id == "name":
            return symbol
        if node.id in collections:
            return collections[node.id]
        return strings.get(node.id, _UNKNOWN)
    literal = _literal_value(node)
    return literal


def _condition_value(
    node: ast.expr,
    symbol: str,
    collections: dict[str, set[str]],
    strings: dict[str, str | None],
) -> bool | None:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        value = _condition_value(node.operand, symbol, collections, strings)
        return None if value is None else not value
    if not isinstance(node, ast.Compare) or len(node.ops) != 1:
        return None
    left = _expression_value(node.left, symbol, collections, strings)
    right = _expression_value(node.comparators[0], symbol, collections, strings)
    if left is _UNKNOWN or right is _UNKNOWN:
        return None
    operator = node.ops[0]
    if isinstance(operator, (ast.Eq, ast.Is)):
        return left == right
    if isinstance(operator, (ast.NotEq, ast.IsNot)):
        return left != right
    if isinstance(operator, ast.In):
        return left in right  # type: ignore[operator]
    if isinstance(operator, ast.NotIn):
        return left not in right  # type: ignore[operator]
    return None


def _module_map_value(
    node: ast.expr, symbol: str, module_maps: dict[str, dict[str, str]]
) -> str | None | object:
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in module_maps
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "name"
    ):
        return _UNKNOWN
    return module_maps[node.func.value.id].get(symbol)


def _call_target(
    node: ast.expr,
    symbol: str,
    imports: dict[str, tuple[str, str]],
    strings: dict[str, str | None],
) -> tuple[str, str] | None:
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
    ):
        return None
    target_name = _expression_value(node.args[1], symbol, {}, strings)
    if not isinstance(target_name, str):
        return None
    owner = node.args[0]
    if isinstance(owner, ast.Name) and owner.id in imports:
        module, imported_name = imports[owner.id]
        return f"{module}.{imported_name}", target_name
    if (
        isinstance(owner, ast.Call)
        and (
            (isinstance(owner.func, ast.Name) and owner.func.id == "import_module")
            or (
                isinstance(owner.func, ast.Attribute)
                and isinstance(owner.func.value, ast.Name)
                and owner.func.value.id == "importlib"
                and owner.func.attr == "import_module"
            )
        )
        and len(owner.args) == 1
    ):
        module = _expression_value(owner.args[0], symbol, {}, strings)
        if isinstance(module, str):
            return module, target_name
    return None


def _evaluate_lazy_statements(
    statements: list[ast.stmt],
    symbol: str,
    collections: dict[str, set[str]],
    module_maps: dict[str, dict[str, str]],
    imports: dict[str, tuple[str, str]],
    strings: dict[str, str | None],
    targets: dict[str, tuple[str, str]],
) -> tuple[tuple[str, str] | None, bool]:
    for node in statements:
        if isinstance(node, ast.If):
            condition = _condition_value(node.test, symbol, collections, strings)
            if condition is None:
                raise RuntimeError(
                    f"ambiguous lazy export {symbol!r}: cannot evaluate "
                    f"{ast.unparse(node.test)!r}"
                )
            branch = node.body if condition else node.orelse
            target, terminal = _evaluate_lazy_statements(
                branch,
                symbol,
                collections,
                module_maps,
                imports,
                strings,
                targets,
            )
            if target is not None or terminal:
                return target, terminal
            continue
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imports[alias.asname or alias.name] = (node.module, alias.name)
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            if isinstance(node, ast.Assign):
                if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                    continue
                name = node.targets[0].id
                value = node.value
            else:
                if not isinstance(node.target, ast.Name) or node.value is None:
                    continue
                name = node.target.id
                value = node.value
            target = _call_target(value, symbol, imports, strings)
            if target is not None:
                targets[name] = target
                continue
            mapped = _module_map_value(value, symbol, module_maps)
            if mapped is not _UNKNOWN:
                strings[name] = mapped  # type: ignore[assignment]
                continue
            literal = _literal_value(value)
            if isinstance(literal, str):
                strings[name] = literal
            continue
        if isinstance(node, ast.Return):
            if node.value is None:
                return None, True
            target = _call_target(node.value, symbol, imports, strings)
            if target is not None:
                return target, True
            if isinstance(node.value, ast.Name):
                if node.value.id in targets:
                    return targets[node.value.id], True
                if node.value.id in imports:
                    return imports[node.value.id], True
            return None, True
        if isinstance(node, ast.Raise):
            return None, True
    return None, False


def _lazy_export_target(tree: ast.Module, symbol: str) -> tuple[str, str] | None:
    getter = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "__getattr__"
        ),
        None,
    )
    if getter is None:
        return None
    collections, module_maps = _lazy_constants(tree)
    target, _ = _evaluate_lazy_statements(
        getter.body,
        symbol,
        collections,
        module_maps,
        {},
        {},
        {},
    )
    return target


def _resolve_export(
    source: Path,
    symbol: str,
    repo_root: Path,
    seen: frozenset[_ResolutionKey] = frozenset(),
    *,
    before_index: int | None = None,
) -> _ResolvedExport | None:
    key = (source.resolve(), symbol, before_index)
    if key in seen:
        return None
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    next_seen = seen | {key}
    stop = len(tree.body) if before_index is None else min(before_index, len(tree.body))

    # Reverse order reflects the binding left in the module namespace at runtime.
    for index in range(stop - 1, -1, -1):
        node = tree.body[index]
        alias_target = _assigned_alias_target(node, symbol)
        if alias_target is not None:
            resolved = _resolve_export(
                source,
                alias_target,
                repo_root,
                next_seen,
                before_index=index,
            )
            if resolved is None:
                raise RuntimeError(
                    f"{source}: cannot resolve alias {symbol!r} through "
                    f"{alias_target!r}"
                )
            return _ResolvedExport(
                signature=resolved.signature,
                binding=f"alias:{alias_target} -> {resolved.binding}",
                source=resolved.source,
                reexported=True,
            )
        signature = _module_definition_signature(
            tree.body,
            index,
            symbol,
            source=source,
            repo_root=repo_root,
            seen=next_seen,
        )
        if signature is not None:
            relative = source.relative_to(repo_root).as_posix()
            return _ResolvedExport(
                signature=signature,
                binding=f"{relative}::{symbol}",
                source=source,
                reexported=False,
            )
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in reversed(node.names):
            public_name = alias.asname or alias.name
            if public_name != symbol and alias.name != "*":
                continue
            imported_symbol = symbol if alias.name == "*" else alias.name
            binding = _import_binding(node, imported_symbol)
            target_source = _import_source(source, node, repo_root)
            if target_source is None:
                raise RuntimeError(
                    f"{source}: cannot resolve export {symbol!r} through {binding}"
                )
            if alias.name == "*" and not _wildcard_exports(
                target_source, imported_symbol
            ):
                continue
            resolved = _resolve_export(
                target_source, imported_symbol, repo_root, next_seen
            )
            if resolved is None and target_source.name == "__init__.py":
                submodule_source = _module_source(
                    target_source.parent / imported_symbol
                )
                if submodule_source is not None:
                    relative = submodule_source.relative_to(repo_root).as_posix()
                    resolved = _ResolvedExport(
                        signature=f"module:{relative}",
                        binding=f"{relative}::{imported_symbol}",
                        source=submodule_source,
                        reexported=False,
                    )
            if resolved is None:
                raise RuntimeError(
                    f"{source}: cannot resolve export {symbol!r} through {binding}"
                )
            return _ResolvedExport(
                signature=resolved.signature,
                binding=f"{binding} -> {resolved.binding}",
                source=resolved.source,
                reexported=True,
            )
    lazy_target = _lazy_export_target(tree, symbol)
    if lazy_target is not None:
        module, target_symbol = lazy_target
        binding = f"lazy:{module}.{target_symbol}"
        target_source = _absolute_module_source(source, module, repo_root)
        if target_source is None:
            raise RuntimeError(
                f"{source}: cannot resolve export {symbol!r} through {binding}"
            )
        resolved = _resolve_export(target_source, target_symbol, repo_root, next_seen)
        if resolved is None:
            raise RuntimeError(
                f"{source}: cannot resolve export {symbol!r} through {binding}"
            )
        return _ResolvedExport(
            signature=resolved.signature,
            binding=f"{binding} -> {resolved.binding}",
            source=resolved.source,
            reexported=True,
        )
    return None


def _public_symbol_records(
    package: SnapshotPackage, repo_root: Path
) -> list[dict[str, str]]:
    if not package.interface:
        return []
    if package.impl_dir is None or not package.impl_dir.is_dir():
        raise RuntimeError(
            f"package {package.name!r} publishes an interface but has no readable "
            "BE implementation"
        )

    init_path = package.impl_dir / "__init__.py"
    records: list[dict[str, str]] = []
    for symbol in sorted(package.interface):
        resolved = (
            _resolve_export(init_path, symbol, repo_root)
            if init_path.is_file()
            else None
        )
        if resolved is not None:
            records.append(
                {
                    "package": package.name,
                    "symbol": symbol,
                    "signature": f"{resolved.binding} => {resolved.signature}",
                    "resolution": "reexport" if resolved.reexported else "definition",
                    "source": resolved.source.relative_to(repo_root).as_posix(),
                }
            )
            continue

        records.append(
            {
                "package": package.name,
                "symbol": symbol,
                "signature": "dynamic-export",
                "resolution": "dynamic",
                "source": init_path.relative_to(repo_root).as_posix(),
            }
        )
    return records


def _contract_call(contract_path: Path) -> ast.Call:
    tree = ast.parse(
        contract_path.read_text(encoding="utf-8"), filename=str(contract_path)
    )
    for node in tree.body:
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "CONTRACT"
            for target in node.targets
        ):
            value = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "CONTRACT"
        ):
            value = node.value
        if isinstance(value, ast.Call):
            return value
    raise RuntimeError(f"{contract_path}: no CONTRACT declaration found")


def _literal_keyword(call: ast.Call, name: str, contract_path: Path) -> object:
    for keyword in call.keywords:
        if keyword.arg != name:
            continue
        try:
            return ast.literal_eval(keyword.value)
        except (ValueError, TypeError, SyntaxError) as exc:
            raise RuntimeError(
                f"{contract_path}: {name!r} must be a literal for dependency reporting"
            ) from exc
    raise RuntimeError(f"{contract_path}: missing {name!r} contract field")


def _implementation_dir(be_path: object, repo_root: Path) -> Path | None:
    if be_path is None:
        return None
    if not isinstance(be_path, str):
        raise RuntimeError("contract implementations['be'] must be a string or null")
    relative = Path(be_path)
    if relative.is_absolute():
        return None
    resolved = (repo_root / relative).resolve()
    if resolved != repo_root and repo_root not in resolved.parents:
        return None
    return resolved


def _snapshot_packages(repo_root: Path) -> list[SnapshotPackage]:
    packages: list[SnapshotPackage] = []
    for contract_path in sorted(repo_root.glob("common/*/contract.py")):
        call = _contract_call(contract_path)
        name = _literal_keyword(call, "name", contract_path)
        depends_on = _literal_keyword(call, "depends_on", contract_path)
        interface = _literal_keyword(call, "interface", contract_path)
        implementations = _literal_keyword(call, "implementations", contract_path)
        if not isinstance(name, str):
            raise RuntimeError(f"{contract_path}: 'name' must be a string")
        if not isinstance(depends_on, list) or not all(
            isinstance(value, str) for value in depends_on
        ):
            raise RuntimeError(f"{contract_path}: 'depends_on' must be a string list")
        if not isinstance(interface, list) or not all(
            isinstance(value, str) for value in interface
        ):
            raise RuntimeError(f"{contract_path}: 'interface' must be a string list")
        if not isinstance(implementations, dict):
            raise RuntimeError(f"{contract_path}: 'implementations' must be a mapping")
        packages.append(
            SnapshotPackage(
                name=name,
                depends_on=tuple(depends_on),
                interface=tuple(interface),
                impl_dir=_implementation_dir(implementations.get("be"), repo_root),
            )
        )
    return packages


def build_dependency_snapshot(repo_root: Path) -> dict[str, object]:
    """Build a deterministic dependency/public-boundary snapshot of a tree."""

    root = repo_root.resolve()
    packages = _snapshot_packages(root)
    if not packages:
        raise RuntimeError(f"no package contracts discovered under {root}")

    graph = build_dependency_graph(packages)
    public_symbols = [
        record
        for package in sorted(packages, key=lambda item: item.name)
        for record in _public_symbol_records(package, root)
    ]
    snapshot = graph.as_dict()
    snapshot["public_symbols"] = public_symbols
    return snapshot


def _edge_key(edge: dict[str, str]) -> tuple[str, str, str, str]:
    return (edge["consumer"], edge["provider"], edge["kind"], edge["detail"])


def _symbol_map(snapshot: dict[str, object]) -> dict[tuple[str, str], dict[str, str]]:
    records = snapshot["public_symbols"]
    assert isinstance(records, list)
    return {
        (record["package"], record["symbol"]): record
        for record in records
        if isinstance(record, dict)
    }


def _consumer_set(
    snapshots: Iterable[dict[str, object]], package: str, field: str
) -> list[str]:
    consumers: set[str] = set()
    for snapshot in snapshots:
        index = snapshot[field]
        assert isinstance(index, dict)
        values = index.get(package, [])
        assert isinstance(values, list)
        consumers.update(value for value in values if isinstance(value, str))
    return sorted(consumers)


def _providers_with_consumer_changes(
    base: dict[str, object], head: dict[str, object]
) -> set[str]:
    changed: set[str] = set()
    for field in ("direct_consumers", "transitive_consumers"):
        base_index = base[field]
        head_index = head[field]
        assert isinstance(base_index, dict)
        assert isinstance(head_index, dict)
        for package in base_index.keys() | head_index.keys():
            if base_index.get(package, []) != head_index.get(package, []):
                changed.add(package)
    return changed


def compare_dependency_snapshots(
    base: dict[str, object], head: dict[str, object]
) -> dict[str, object]:
    """Compare two snapshots and compute the complete consumer fan-out."""

    base_edges = {_edge_key(edge): edge for edge in base["edges"]}  # type: ignore[index]
    head_edges = {_edge_key(edge): edge for edge in head["edges"]}  # type: ignore[index]
    added_edges = [head_edges[key] for key in sorted(head_edges.keys() - base_edges)]
    removed_edges = [base_edges[key] for key in sorted(base_edges.keys() - head_edges)]

    base_symbols = _symbol_map(base)
    head_symbols = _symbol_map(head)
    added_symbols = [
        head_symbols[key] for key in sorted(head_symbols.keys() - base_symbols)
    ]
    removed_symbols = [
        base_symbols[key] for key in sorted(base_symbols.keys() - head_symbols)
    ]
    changed_symbols: list[dict[str, str]] = []
    for key in sorted(base_symbols.keys() & head_symbols):
        before = base_symbols[key]
        after = head_symbols[key]
        if before["signature"] != after["signature"]:
            changed_symbols.append(
                {
                    "package": key[0],
                    "symbol": key[1],
                    "before": before["signature"],
                    "after": after["signature"],
                }
            )

    affected_packages = {
        record["package"]
        for record in (*added_symbols, *removed_symbols, *changed_symbols)
    }
    affected_packages.update(edge["provider"] for edge in added_edges)
    affected_packages.update(edge["provider"] for edge in removed_edges)
    affected_packages.update(_providers_with_consumer_changes(base, head))

    affected_consumers: dict[str, dict[str, list[str]]] = {}
    for package in sorted(affected_packages):
        direct = _consumer_set((base, head), package, "direct_consumers")
        transitive = _consumer_set((base, head), package, "transitive_consumers")
        affected_consumers[package] = {
            "direct": direct,
            "transitive": transitive,
            "indirect": sorted(set(transitive) - set(direct)),
        }

    return {
        "base": base,
        "head": head,
        "added_edges": added_edges,
        "removed_edges": removed_edges,
        "added_public_symbols": added_symbols,
        "removed_public_symbols": removed_symbols,
        "changed_public_symbols": changed_symbols,
        "affected_consumers": affected_consumers,
        "errors": [],
    }


def _snapshot_git_ref(repo_root: Path, ref: str) -> dict[str, object]:
    try:
        archive = subprocess.run(
            ["git", "-C", str(repo_root), "archive", "--format=tar", ref],
            check=True,
            capture_output=True,
        ).stdout
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"cannot read base ref {ref!r}: {detail}") from exc

    with tempfile.TemporaryDirectory(prefix="ddd-dependency-base-") as temp_dir:
        base_root = Path(temp_dir)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
            tar.extractall(base_root, filter="data")
        output_path = base_root / "dependency-snapshot.json"
        current_root = Path(__file__).resolve().parents[3]
        runner = """
import json
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from common.meta.extension.dependency_report import build_dependency_snapshot

snapshot = build_dependency_snapshot(Path(sys.argv[2]))
Path(sys.argv[3]).write_text(json.dumps(snapshot), encoding="utf-8")
"""
        load = subprocess.run(
            [
                sys.executable,
                "-I",
                "-c",
                runner,
                current_root.as_posix(),
                base_root.as_posix(),
                output_path.as_posix(),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if load.returncode != 0 or not output_path.is_file():
            detail = load.stderr.strip() or load.stdout.strip() or "loader failed"
            raise RuntimeError(f"cannot snapshot base ref {ref!r}: {detail}")
        try:
            snapshot = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"invalid snapshot for base ref {ref!r}: {exc}") from exc
        if not isinstance(snapshot, dict):
            raise RuntimeError(
                f"invalid snapshot for base ref {ref!r}: expected object"
            )
        return snapshot


def build_impact_report(repo_root: Path, *, base_ref: str) -> dict[str, object]:
    """Compare the working tree with an archive isolated from ``base_ref``."""

    root = repo_root.resolve()
    head = build_dependency_snapshot(root)
    base = _snapshot_git_ref(root, base_ref)
    report = compare_dependency_snapshots(base, head)
    report["base_ref"] = base_ref
    return report


def render_markdown(report: dict[str, object]) -> str:
    """Render the high-level dependency impact for a CI step summary."""

    added_edges = report["added_edges"]
    removed_edges = report["removed_edges"]
    added_symbols = report["added_public_symbols"]
    removed_symbols = report["removed_public_symbols"]
    changed_symbols = report["changed_public_symbols"]
    affected = report["affected_consumers"]
    assert isinstance(added_edges, list)
    assert isinstance(removed_edges, list)
    assert isinstance(added_symbols, list)
    assert isinstance(removed_symbols, list)
    assert isinstance(changed_symbols, list)
    assert isinstance(affected, dict)

    lines = [
        "## DDD Dependency Impact",
        "",
        f"Base: `{report.get('base_ref', 'snapshot')}`",
        "",
        "| Change | Count |",
        "|---|---:|",
        f"| Added dependency edges | {len(added_edges)} |",
        f"| Removed dependency edges | {len(removed_edges)} |",
        f"| Added public symbols | {len(added_symbols)} |",
        f"| Removed public symbols | {len(removed_symbols)} |",
        f"| Changed public signatures | {len(changed_symbols)} |",
        f"| Affected provider packages | {len(affected)} |",
    ]
    edge_changes = [
        ("added", edge) for edge in added_edges if isinstance(edge, dict)
    ] + [("removed", edge) for edge in removed_edges if isinstance(edge, dict)]
    if edge_changes:
        lines.extend(
            [
                "",
                "### Dependency Edge Changes",
                "",
                "| Change | Consumer | Provider | Kind |",
                "|---|---|---|---|",
            ]
        )
        for change, edge in edge_changes:
            lines.append(
                f"| {change} | `{edge['consumer']}` | `{edge['provider']}` | "
                f"`{edge['kind']}` |"
            )

    boundary_changes: list[tuple[str, dict[str, str]]] = [
        ("added", record) for record in added_symbols if isinstance(record, dict)
    ]
    boundary_changes.extend(
        ("removed", record) for record in removed_symbols if isinstance(record, dict)
    )
    boundary_changes.extend(
        ("changed", record) for record in changed_symbols if isinstance(record, dict)
    )
    if boundary_changes:
        lines.extend(
            [
                "",
                "### Public Boundary Changes",
                "",
                "| Change | Package | Symbol | Before | After |",
                "|---|---|---|---|---|",
            ]
        )
        for change, record in boundary_changes:
            before = str(
                record.get(
                    "before", "-" if change == "added" else record.get("signature", "-")
                )
            )
            after = str(
                record.get(
                    "after",
                    "-" if change == "removed" else record.get("signature", "-"),
                )
            )
            before = before.replace("|", "\\|")
            after = after.replace("|", "\\|")
            lines.append(
                f"| {change} | `{record['package']}` | `{record['symbol']}` | "
                f"`{before}` | `{after}` |"
            )
    if affected:
        lines.extend(
            [
                "",
                "### Affected Consumers",
                "",
                "| Provider | Direct consumers | Indirect consumers |",
                "|---|---|---|",
            ]
        )
        for package, consumers in sorted(affected.items()):
            assert isinstance(consumers, dict)
            direct = ", ".join(consumers["direct"]) or "-"
            indirect = ", ".join(consumers["indirect"]) or "-"
            lines.append(f"| `{package}` | {direct} | {indirect} |")
    return "\n".join(lines) + "\n"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args(argv)

    report = build_impact_report(args.repo_root, base_ref=args.base_ref)
    json_text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    markdown = render_markdown(report)
    if args.json_out:
        _write(args.json_out, json_text)
    if args.markdown_out:
        _write(args.markdown_out, markdown)
    if not args.json_out and not args.markdown_out:
        print(json_text, end="")
    return 0
