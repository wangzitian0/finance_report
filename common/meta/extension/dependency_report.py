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


@dataclass(frozen=True)
class _ImportedValue:
    source: Path
    symbol: str
    binding: str


@dataclass(frozen=True)
class _ImportedModule:
    source: Path
    binding: str


@dataclass(frozen=True)
class _LocalDefinition:
    source: Path
    symbol: str
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
    values: tuple[tuple[str, _ValueBinding], ...]
    body: tuple[ast.stmt, ...]
    index: int
    binding: str


@dataclass(frozen=True)
class _ExpressionValue:
    expression: str
    dependencies: tuple[tuple[str, _ValueBinding], ...]


type _ValueBinding = (
    _ExpressionValue | _ImportedModule | _ImportedValue | _LocalDefinition
)


_ResolutionKey = tuple[Path, str, int | None]
_ValueKey = tuple[Path, str]


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


def _attribute_parts(node: ast.expr) -> tuple[str, tuple[str, ...]] | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return node.id, tuple(reversed(parts))


def _qualified_imported_value(
    node: ast.expr,
    values: dict[str, _ValueBinding],
) -> _ImportedValue | None:
    qualified = _attribute_parts(node)
    if qualified is None:
        return None
    root, parts = qualified
    binding = values.get(root)
    if not isinstance(binding, _ImportedModule) or not parts:
        return None
    target_source = binding.source
    if len(parts) > 1:
        target_source = _module_source(target_source.parent.joinpath(*parts[:-1]))
        if target_source is None:
            return None
    return _ImportedValue(
        source=target_source,
        symbol=parts[-1],
        binding=f"{binding.binding}.{'.'.join(parts)}",
    )


def _capture_expression(
    node: ast.expr,
    values: dict[str, _ValueBinding],
) -> _ExpressionValue:
    dependencies: dict[str, _ValueBinding] = {}

    def visit(child: ast.AST) -> None:
        if isinstance(child, ast.Attribute):
            qualified = _qualified_imported_value(child, values)
            if qualified is not None:
                dependencies[ast.unparse(child)] = qualified
                return
        if isinstance(child, ast.Name) and child.id in values:
            dependencies[child.id] = values[child.id]
            return
        for nested in ast.iter_child_nodes(child):
            visit(nested)

    visit(node)
    return _ExpressionValue(
        expression=ast.unparse(node),
        dependencies=tuple(sorted(dependencies.items())),
    )


def _binding_fingerprint(
    binding: _ValueBinding,
    repo_root: Path,
    seen: frozenset[_ValueKey] = frozenset(),
) -> str:
    if isinstance(binding, _ImportedModule):
        return binding.binding
    if isinstance(binding, _LocalDefinition):
        key = (binding.source.resolve(), binding.symbol)
        if key in seen:
            return binding.binding
        definition_seen = seen | {key}
        if isinstance(binding.node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            signature = _function_signature(
                binding.node,
                repo_root,
                dict(binding.values),
                definition_seen,
            )
        else:
            signature = _class_signature(
                binding.node,
                module_body=list(binding.body),
                values=dict(binding.values),
                source=binding.source,
                repo_root=repo_root,
                seen=frozenset(),
                definition_index=binding.index,
                value_seen=definition_seen,
            )
        return f"{binding.binding} -> {signature}"
    if isinstance(binding, _ImportedValue):
        fingerprint = _imported_value_fingerprint(
            binding.source, binding.symbol, repo_root, seen
        )
        return (
            f"{binding.binding} -> {fingerprint}"
            if fingerprint is not None
            else binding.binding
        )
    dependencies = [
        f"{name}={_binding_fingerprint(value, repo_root, seen)}"
        for name, value in binding.dependencies
    ]
    suffix = f" [{', '.join(dependencies)}]" if dependencies else ""
    return f"{binding.expression}{suffix}"


def _expression_fingerprint(
    node: ast.expr,
    values: dict[str, _ValueBinding],
    repo_root: Path,
    value_seen: frozenset[_ValueKey] = frozenset(),
) -> str:
    return _binding_fingerprint(
        _capture_expression(node, values), repo_root, value_seen
    )


def _imported_value_fingerprint(
    source: Path,
    symbol: str,
    repo_root: Path,
    seen: frozenset[_ValueKey],
) -> str | None:
    key = (source.resolve(), symbol)
    if key in seen:
        return None
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    values = _module_values(tree.body, source=source, repo_root=repo_root)
    binding = values.get(symbol)
    if binding is not None:
        binding_seen = seen if isinstance(binding, _LocalDefinition) else seen | {key}
        return _binding_fingerprint(binding, repo_root, binding_seen)
    return _imported_definition_fingerprint(source, symbol, repo_root, seen | {key})


def _imported_definition_fingerprint(
    source: Path,
    symbol: str,
    repo_root: Path,
    value_seen: frozenset[_ValueKey],
) -> str | None:
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for index in range(len(tree.body) - 1, -1, -1):
        node = tree.body[index]
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if node.name != symbol:
            continue
        return _module_definition_signature(
            tree.body,
            index,
            symbol,
            source=source,
            repo_root=repo_root,
            seen=frozenset(),
            value_seen=value_seen,
        )
    return None


def _is_type_checking_test(node: ast.expr) -> bool:
    return (isinstance(node, ast.Name) and node.id == "TYPE_CHECKING") or (
        isinstance(node, ast.Attribute) and node.attr == "TYPE_CHECKING"
    )


def _module_values(
    body: Sequence[ast.stmt],
    *,
    source: Path,
    repo_root: Path,
    initial: dict[str, _ValueBinding] | None = None,
) -> dict[str, _ValueBinding]:
    values = dict(initial or {})
    scope_body = tuple(body)
    for index, node in enumerate(scope_body):
        if isinstance(node, ast.If) and _is_type_checking_test(node.test):
            values = _module_values(
                node.body,
                source=source,
                repo_root=repo_root,
                initial=values,
            )
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            relative = source.relative_to(repo_root).as_posix()
            values[node.name] = _LocalDefinition(
                source=source,
                symbol=node.name,
                node=node,
                values=tuple(values.items()),
                body=scope_body,
                index=index,
                binding=f"{relative}::{node.name}",
            )
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_name = alias.name if alias.asname else alias.name.split(".")[0]
                target_source = _absolute_module_source(
                    source, imported_name, repo_root
                )
                if target_source is not None:
                    values[alias.asname or imported_name] = _ImportedModule(
                        source=target_source,
                        binding=alias.asname or imported_name,
                    )
            continue
        if isinstance(node, ast.ImportFrom):
            target_source = _import_source(source, node, repo_root)
            if target_source is None:
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                submodule_source = (
                    _module_source(target_source.parent / alias.name)
                    if target_source.name == "__init__.py"
                    else None
                )
                if submodule_source is not None:
                    values[alias.asname or alias.name] = _ImportedModule(
                        source=submodule_source,
                        binding=_import_binding(node, alias.name),
                    )
                else:
                    values[alias.asname or alias.name] = _ImportedValue(
                        source=target_source,
                        symbol=alias.name,
                        binding=_import_binding(node, alias.name),
                    )
            continue
        if isinstance(node, ast.Assign):
            binding = _capture_expression(node.value, values)
            for target in node.targets:
                if isinstance(target, ast.Name):
                    values[target.id] = binding
            continue
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            values[node.target.id] = _capture_expression(node.value, values)
            continue
        if isinstance(node, ast.TypeAlias) and isinstance(node.name, ast.Name):
            values[node.name.id] = _capture_expression(node.value, values)
    return values


def _resolved_references(
    expressions: Iterable[ast.expr],
    values: dict[str, _ValueBinding],
    label: str,
    repo_root: Path,
    value_seen: frozenset[_ValueKey] = frozenset(),
) -> str:
    dependencies = dict(
        dependency
        for expression in expressions
        for dependency in _capture_expression(expression, values).dependencies
    )
    if not dependencies:
        return ""
    resolved = ", ".join(
        f"{name}={_binding_fingerprint(binding, repo_root, value_seen)}"
        for name, binding in sorted(dependencies.items())
    )
    return f" [{label}: {resolved}]"


def _resolved_default_values(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    values: dict[str, _ValueBinding],
    repo_root: Path,
    value_seen: frozenset[_ValueKey] = frozenset(),
) -> str:
    defaults = [*node.args.defaults]
    defaults.extend(default for default in node.args.kw_defaults if default is not None)
    return _resolved_references(defaults, values, "defaults", repo_root, value_seen)


def _resolved_annotation_values(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    values: dict[str, _ValueBinding],
    repo_root: Path,
    value_seen: frozenset[_ValueKey] = frozenset(),
) -> str:
    arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
    if node.args.vararg is not None:
        arguments.append(node.args.vararg)
    if node.args.kwarg is not None:
        arguments.append(node.args.kwarg)
    annotations = [argument.annotation for argument in arguments if argument.annotation]
    if node.returns is not None:
        annotations.append(node.returns)
    return _resolved_references(
        annotations, values, "annotations", repo_root, value_seen
    )


def _function_signature(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    repo_root: Path,
    values: dict[str, _ValueBinding] | None = None,
    value_seen: frozenset[_ValueKey] = frozenset(),
) -> str:
    bindings = values or {}
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return (
        f"{_decorator_prefix(node.decorator_list)}{prefix}{_type_parameters(node)}"
        f"({ast.unparse(node.args)}) -> {_annotation(node.returns)}"
        f"{_resolved_default_values(node, bindings, repo_root, value_seen)}"
        f"{_resolved_annotation_values(node, bindings, repo_root, value_seen)}"
        f"{_resolved_references(node.decorator_list, bindings, 'decorators', repo_root, value_seen)}"
    )


def _annotated_assignment_signature(
    node: ast.AnnAssign,
    values: dict[str, _ValueBinding],
    repo_root: Path,
    value_seen: frozenset[_ValueKey] = frozenset(),
) -> str:
    signature = _annotation(node.annotation)
    signature += _resolved_references(
        [node.annotation], values, "annotations", repo_root, value_seen
    )
    if node.value is not None:
        signature += (
            f"={_expression_fingerprint(node.value, values, repo_root, value_seen)}"
        )
    return signature


def _is_public_method(name: str) -> bool:
    return not name.startswith("_") or (name.startswith("__") and name.endswith("__"))


def _base_target(
    node: ast.expr, values: dict[str, _ValueBinding]
) -> str | _ImportedValue | None:
    while isinstance(node, ast.Subscript):
        node = node.value
    qualified = _qualified_imported_value(node, values)
    if qualified is not None:
        return qualified
    if not isinstance(node, ast.Name):
        return None
    imported = values.get(node.id)
    return imported if isinstance(imported, _ImportedValue) else node.id


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
    values: dict[str, _ValueBinding],
    source: Path,
    repo_root: Path,
    seen: frozenset[_ResolutionKey],
    definition_index: int,
    value_seen: frozenset[_ValueKey] = frozenset(),
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
        target = _base_target(base, values)
        if target is None:
            continue
        if isinstance(target, _ImportedValue):
            resolved = _resolve_export(target.source, target.symbol, repo_root, seen)
            signature = (
                f"{target.binding} -> {resolved.signature}"
                if resolved is not None
                else None
            )
        else:
            signature = _project_base_signature(
                source,
                module_body,
                target,
                repo_root,
                seen,
                definition_index,
            )
        if signature is not None:
            members.append(f"inherits[{ast.unparse(base)}]={signature}")
    class_values = dict(values)
    class_body = tuple(node.body)
    relative = source.relative_to(repo_root).as_posix()
    for child_index, child in enumerate(class_body):
        if (
            isinstance(child, ast.AnnAssign)
            and isinstance(child.target, ast.Name)
            and not child.target.id.startswith("_")
        ):
            members.append(
                f"{child.target.id}: "
                f"{_annotated_assignment_signature(child, class_values, repo_root, value_seen)}"
            )
        elif isinstance(child, ast.Assign):
            for target in child.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    members.append(
                        f"{target.id}="
                        f"{_expression_fingerprint(child.value, class_values, repo_root, value_seen)}"
                    )
        elif isinstance(
            child, (ast.FunctionDef, ast.AsyncFunctionDef)
        ) and _is_public_method(child.name):
            signature = _function_signature(child, repo_root, class_values, value_seen)
            marker = "async def" if isinstance(child, ast.AsyncFunctionDef) else "def"
            members.append(signature.replace(marker, child.name, 1))
        if isinstance(child, ast.Assign):
            binding = _capture_expression(child.value, class_values)
            for target in child.targets:
                if isinstance(target, ast.Name):
                    class_values[target.id] = binding
        elif (
            isinstance(child, ast.AnnAssign)
            and isinstance(child.target, ast.Name)
            and child.value is not None
        ):
            class_values[child.target.id] = _capture_expression(
                child.value, class_values
            )
        elif isinstance(child, ast.TypeAlias) and isinstance(child.name, ast.Name):
            class_values[child.name.id] = _capture_expression(child.value, class_values)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            class_values[child.name] = _LocalDefinition(
                source=source,
                symbol=child.name,
                node=child,
                values=tuple(class_values.items()),
                body=class_body,
                index=child_index,
                binding=f"{relative}::{node.name}.{child.name}",
            )
        elif isinstance(child, (ast.Import, ast.ImportFrom)) or (
            isinstance(child, ast.If) and _is_type_checking_test(child.test)
        ):
            class_values = _module_values(
                [child],
                source=source,
                repo_root=repo_root,
                initial=class_values,
            )
    body = "; ".join(members)
    decorator_values = _resolved_references(
        node.decorator_list, values, "decorators", repo_root, value_seen
    )
    return (
        f"{_decorator_prefix(node.decorator_list)}{decorator_values}"
        f"class{_type_parameters(node)}"
        f"({', '.join(bases)}){{{body}}}"
    )


def _definition_signature(
    node: ast.stmt,
    symbol: str,
    *,
    module_body: list[ast.stmt],
    values: dict[str, _ValueBinding],
    source: Path,
    repo_root: Path,
    seen: frozenset[_ResolutionKey],
    definition_index: int,
    value_seen: frozenset[_ValueKey] = frozenset(),
) -> str | None:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return (
            _function_signature(node, repo_root, values, value_seen)
            if node.name == symbol
            else None
        )
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
                value_seen=value_seen,
            )
            if node.name == symbol
            else None
        )
    if (
        isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == symbol
    ):
        return (
            "value: "
            f"{_annotated_assignment_signature(node, values, repo_root, value_seen)}"
        )
    if isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == symbol for target in node.targets
    ):
        return f"value={_expression_fingerprint(node.value, values, repo_root, value_seen)}"
    if (
        isinstance(node, ast.TypeAlias)
        and isinstance(node.name, ast.Name)
        and node.name.id == symbol
    ):
        return (
            f"type={_expression_fingerprint(node.value, values, repo_root, value_seen)}"
        )
    return None


def _is_overload(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        (isinstance(decorator, ast.Name) and decorator.id == "overload")
        or (isinstance(decorator, ast.Attribute) and decorator.attr == "overload")
        for decorator in node.decorator_list
    )


def _assigned_alias_value(node: ast.stmt, symbol: str) -> ast.expr | None:
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
    return value


def _defines_symbol(node: ast.stmt, symbol: str) -> bool:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name == symbol
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id == symbol
    if isinstance(node, ast.Assign):
        return any(
            isinstance(target, ast.Name) and target.id == symbol
            for target in node.targets
        )
    if isinstance(node, ast.TypeAlias) and isinstance(node.name, ast.Name):
        return node.name.id == symbol
    return False


def _module_definition_signature(
    body: list[ast.stmt],
    index: int,
    symbol: str,
    *,
    source: Path,
    repo_root: Path,
    seen: frozenset[_ResolutionKey],
    value_seen: frozenset[_ValueKey] = frozenset(),
) -> str | None:
    node = body[index]
    values = _module_values(body[:index], source=source, repo_root=repo_root)
    signature = _definition_signature(
        node,
        symbol,
        module_body=body,
        values=values,
        source=source,
        repo_root=repo_root,
        seen=seen,
        definition_index=index,
        value_seen=value_seen,
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
        _function_signature(definition, repo_root, values, value_seen)
        for definition in definitions
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


def _module_spec_source(source: Path, module: str, repo_root: Path) -> Path | None:
    level = len(module) - len(module.lstrip("."))
    if not level:
        return _absolute_module_source(source, module, repo_root)
    anchor = source.parent
    for _ in range(level - 1):
        anchor = anchor.parent
    module_parts = module[level:].split(".") if module[level:] else []
    return _module_source(anchor.joinpath(*module_parts))


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
        separator = "" if module.endswith(".") else "."
        return f"{module}{separator}{imported_name}", target_name
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
        if isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            for alias in node.names:
                imports[alias.asname or alias.name] = (module, alias.name)
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
        if _defines_symbol(node, symbol):
            alias_value = _assigned_alias_value(node, symbol)
            alias_target: str | _ImportedValue | None = None
            if isinstance(alias_value, ast.Name):
                alias_target = alias_value.id
            elif isinstance(alias_value, ast.Attribute):
                values = _module_values(
                    tree.body[:index], source=source, repo_root=repo_root
                )
                alias_target = _qualified_imported_value(alias_value, values)
                if alias_target is None:
                    raise RuntimeError(
                        f"{source}: cannot resolve qualified alias {symbol!r} "
                        f"through {ast.unparse(alias_value)!r}"
                    )
            if isinstance(alias_target, str):
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
            if isinstance(alias_target, _ImportedValue):
                resolved = _resolve_export(
                    alias_target.source,
                    alias_target.symbol,
                    repo_root,
                    next_seen,
                )
                if resolved is None:
                    raise RuntimeError(
                        f"{source}: cannot resolve alias {symbol!r} through "
                        f"{alias_target.binding!r}"
                    )
                return _ResolvedExport(
                    signature=resolved.signature,
                    binding=f"alias:{alias_target.binding} -> {resolved.binding}",
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
        separator = "" if module.endswith(".") else "."
        binding = f"lazy:{module}{separator}{target_symbol}"
        target_source = _module_spec_source(source, module, repo_root)
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
