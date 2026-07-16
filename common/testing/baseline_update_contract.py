"""Enforce explicit, monotonic semantics for baseline mutation flags."""

from __future__ import annotations

import ast
from collections.abc import Callable, Sequence
from copy import deepcopy
from pathlib import Path
from typing import TypeVar

from common.testing import gate_cli

MONOTONIC_MODES = frozenset({"raise-only", "shrink-only"})
REWRITE_MODE = "rewrite"
VALID_MODES = MONOTONIC_MODES | {REWRITE_MODE}
UPDATE_FLAG = "--" + "update"
REWRITE_FLAG = "--rewrite-" + "baseline"
PROOF_HARNESS_MODULE = "common.testing.baseline_update_contract"
PROOF_HARNESS_NAME = "assert_regression_debt_refused"

Result = TypeVar("Result")
UpdateCommand = tuple[str, str]

MONOTONIC_UPDATE_PROOFS = {
    ("common/meta/extension/check_ac_tier_baseline.py", UPDATE_FLAG): (
        "tests/tooling/test_s4_gate_contracts.py"
        "::test_AC_testing_governance_21_real_updates_refuse_regression_debt"
    ),
    ("common/meta/extension/check_app_boundary.py", UPDATE_FLAG): (
        "tests/tooling/test_s4_gate_contracts.py"
        "::test_AC_testing_governance_21_real_updates_refuse_regression_debt"
    ),
    ("common/testing/api_surface_ratchet.py", UPDATE_FLAG): (
        "tests/tooling/test_api_surface_ratchet.py"
        "::test_router_ratchet_rejects_new_file_and_update_cannot_adopt_it"
    ),
    ("common/testing/check_ac_score_baseline.py", UPDATE_FLAG): (
        "tests/tooling/test_s4_gate_contracts.py"
        "::test_AC_testing_governance_21_real_updates_refuse_regression_debt"
    ),
    ("common/testing/check_ac_index.py", f"{UPDATE_FLAG}-floor"): (
        "tests/tooling/test_ac_index_consistency.py"
        "::test_AC8_13_140_update_floor_raises_floors"
    ),
    ("common/testing/check_cassette_graded_eval.py", UPDATE_FLAG): (
        "tests/tooling/test_s4_gate_contracts.py"
        "::test_AC_testing_governance_21_real_updates_refuse_regression_debt"
    ),
    ("common/testing/check_critical_value_proof.py", UPDATE_FLAG): (
        "tests/tooling/test_critical_value_proof_ratchet.py"
        "::test_baseline_only_shrinks_never_grows"
    ),
    ("common/testing/fe_api_handmock_ratchet.py", UPDATE_FLAG): (
        "tests/tooling/test_fe_api_handmock_ratchet.py"
        "::test_AC_testing_fe_handmock_1_ratchet_is_locked_and_only_goes_down"
    ),
    ("common/testing/fe_fetch_ratchet.py", UPDATE_FLAG): (
        "tests/tooling/test_fe_fetch_ratchet.py"
        "::test_AC_testing_fe_fetch_1_ratchet_is_locked_and_only_goes_down"
    ),
    ("common/testing/gate_main_contract.py", UPDATE_FLAG): (
        "tests/tooling/test_s4_gate_contracts.py"
        "::test_AC_testing_governance_21_real_updates_refuse_regression_debt"
    ),
    ("common/testing/mirror_ratchet.py", UPDATE_FLAG): (
        "tests/tooling/test_package_declaration_and_ratchet.py"
        "::test_AC8_24_3_mirror_assertion_ratchet_is_locked_and_only_goes_down"
    ),
    ("common/testing/tool_shim_contract.py", UPDATE_FLAG): (
        "tests/tooling/test_s4_gate_contracts.py"
        "::test_AC_testing_governance_21_real_updates_refuse_regression_debt"
    ),
}


def assert_regression_debt_refused(
    *,
    regression_debt_present: Callable[[], bool],
    baseline_state: Callable[[], object],
    update: Callable[[], Result],
) -> Result:
    """Run a real updater while proving synthetic debt cannot mutate its baseline."""

    if not regression_debt_present():
        raise AssertionError("the proof did not establish synthetic regression debt")
    before = deepcopy(baseline_state())
    result = update()
    after = baseline_state()
    if after != before:
        raise AssertionError("the updater adopted synthetic regression debt")
    return result


def _declared_mode(tree: ast.Module) -> str | None:
    for node in tree.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if (
            isinstance(target, ast.Name)
            and target.id == "BASELINE_UPDATE_MODE"
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
        ):
            return value.value
    return None


def _string_value(node: ast.expr, constants: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _string_value(node.left, constants)
        right = _string_value(node.right, constants)
        if left is not None and right is not None:
            return left + right
    return None


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    constants: dict[str, str] = {}
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        if value is None:
            continue
        resolved = _string_value(value, constants)
        if resolved is not None:
            constants.update(
                (target.id, resolved)
                for target in targets
                if isinstance(target, ast.Name)
            )
    return constants


def _is_argument_sequence(node: ast.expr) -> bool:
    return (isinstance(node, ast.Name) and node.id in {"args", "argv"}) or (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "sys"
        and node.attr == "argv"
    )


def _is_monotonic_mutation_flag(value: str | None) -> bool:
    return value == UPDATE_FLAG or bool(value and value.startswith(f"{UPDATE_FLAG}-"))


def _is_mutation_flag(value: str | None) -> bool:
    return _is_monotonic_mutation_flag(value) or value == REWRITE_FLAG


def _mutation_flags(tree: ast.Module) -> set[str]:
    constants = _module_string_constants(tree)
    flags: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            flags.update(
                value
                for arg in node.args
                if _is_mutation_flag(value := _string_value(arg, constants))
            )
        elif isinstance(node, ast.Compare):
            value = _string_value(node.left, constants)
            if not _is_mutation_flag(value):
                continue
            if any(
                isinstance(operator, (ast.In, ast.NotIn))
                and _is_argument_sequence(comparator)
                for operator, comparator in zip(node.ops, node.comparators, strict=True)
            ):
                flags.add(value)
    return flags


def monotonic_update_commands(repo_root: Path) -> set[UpdateCommand]:
    """Return every module/flag command in the monotonic mutation family."""

    commands: set[UpdateCommand] = set()
    for root_name in ("common", "tools"):
        root = repo_root / root_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if _declared_mode(tree) not in MONOTONIC_MODES:
                continue
            relative = path.relative_to(repo_root).as_posix()
            commands.update(
                (relative, flag)
                for flag in _mutation_flags(tree)
                if _is_monotonic_mutation_flag(flag)
            )
    return commands


def monotonic_update_paths(repo_root: Path) -> set[str]:
    """Return modules exposing any monotonic ``--update``/``--update-*`` flag."""

    return {path for path, _flag in monotonic_update_commands(repo_root)}


def declaration_violations(repo_root: Path) -> list[str]:
    """Return baseline CLI declarations whose flag and mutation mode disagree."""

    findings: list[str] = []
    for root_name in ("common", "tools"):
        root = repo_root / root_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            flags = _mutation_flags(tree)
            mode = _declared_mode(tree)
            relative = path.relative_to(repo_root)

            if not flags:
                if mode is not None:
                    findings.append(
                        f"{relative}: BASELINE_UPDATE_MODE={mode!r} has no mutation flag"
                    )
                continue
            if mode not in VALID_MODES:
                findings.append(
                    f"{relative}: baseline mutation flag requires "
                    "BASELINE_UPDATE_MODE = 'raise-only', 'shrink-only', or 'rewrite'"
                )
                continue
            if UPDATE_FLAG in flags and mode not in MONOTONIC_MODES:
                findings.append(
                    f"{relative}: rewrite mode must use --rewrite-baseline, not --update"
                )
            specialized = {
                flag
                for flag in flags
                if flag != UPDATE_FLAG and _is_monotonic_mutation_flag(flag)
            }
            if specialized and mode not in MONOTONIC_MODES:
                findings.append(
                    f"{relative}: monotonic mutation flag(s) "
                    f"{', '.join(sorted(specialized))} require "
                    "BASELINE_UPDATE_MODE = 'raise-only' or 'shrink-only'"
                )
            if REWRITE_FLAG in flags and mode != REWRITE_MODE:
                findings.append(
                    f"{relative}: --rewrite-baseline requires BASELINE_UPDATE_MODE = 'rewrite'"
                )
    return findings


TestFunction = ast.FunctionDef | ast.AsyncFunctionDef


def _test_node(repo_root: Path, node_id: str) -> tuple[ast.Module, TestFunction] | None:
    test_path_text, separator, test_name = node_id.partition("::")
    if not separator or not test_name:
        return None
    test_path = repo_root / test_path_text
    if not test_path.is_file():
        return None
    tree = ast.parse(test_path.read_text(encoding="utf-8"), filename=str(test_path))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name == test_name
        ):
            return tree, node
    return None


def _updater_aliases(
    tree: ast.Module, function: TestFunction, module_name: str
) -> set[str]:
    aliases: set[str] = set()
    import_nodes = [
        node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    import_nodes.extend(
        node
        for node in ast.walk(function)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    )
    for node in import_nodes:
        if isinstance(node, ast.Import):
            aliases.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name == module_name and alias.asname is not None
            )
            continue
        aliases.update(
            alias.asname or alias.name
            for alias in node.names
            if f"{node.module}.{alias.name}" == module_name
        )

    for node in ast.walk(function):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        value = node.value
        if (
            not isinstance(target, ast.Name)
            or not isinstance(value, ast.Call)
            or not isinstance(value.func, ast.Attribute)
            or not isinstance(value.func.value, ast.Name)
            or value.func.value.id != "importlib"
            or value.func.attr != "import_module"
            or not value.args
        ):
            continue
        if _string_value(value.args[0], {}) == module_name:
            aliases.add(target.id)
    return aliases


_OBSERVER_BUILTINS = frozenset(
    {
        "all",
        "any",
        "bool",
        "bytes",
        "dict",
        "frozenset",
        "int",
        "len",
        "list",
        "set",
        "str",
        "tuple",
    }
)
_UNKNOWN_RESULT = object()


def _bound_names(target: ast.expr) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.List, ast.Tuple)):
        return {name for element in target.elts for name in _bound_names(element)}
    if isinstance(target, ast.Starred):
        return _bound_names(target.value)
    return set()


def _destructured_literal_names(target: ast.expr, value: ast.expr) -> set[str]:
    if isinstance(target, ast.Name):
        try:
            ast.literal_eval(value)
        except (ValueError, TypeError):
            return set()
        return {target.id}
    if isinstance(target, (ast.List, ast.Tuple)):
        try:
            ast.literal_eval(value)
        except (ValueError, TypeError):
            pass
        else:
            return _bound_names(target)
    if not (
        isinstance(target, (ast.List, ast.Tuple))
        and isinstance(value, (ast.List, ast.Tuple))
        and len(target.elts) == len(value.elts)
    ):
        return set()
    return {
        name
        for target_element, value_element in zip(target.elts, value.elts, strict=True)
        for name in _destructured_literal_names(target_element, value_element)
    }


class _FunctionScopeVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.assignments: list[ast.Assign | ast.AnnAssign | ast.AugAssign] = []
        self.functions: list[TestFunction] = []
        self.return_values: list[ast.expr] = []

    def visit_Assign(self, node: ast.Assign) -> None:
        self.assignments.append(node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.assignments.append(node)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.assignments.append(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.functions.append(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.functions.append(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_Return(self, node: ast.Return) -> None:
        if node.value is not None:
            self.return_values.append(node.value)


def _function_scope(function: TestFunction) -> _FunctionScopeVisitor:
    visitor = _FunctionScopeVisitor()
    for statement in function.body:
        visitor.visit(statement)
    return visitor


def _scoped_assignments(
    function: TestFunction,
) -> list[ast.Assign | ast.AnnAssign | ast.AugAssign]:
    return _function_scope(function).assignments


_CONTAINER_MUTATORS = frozenset(
    {
        "add",
        "append",
        "clear",
        "difference_update",
        "discard",
        "extend",
        "insert",
        "intersection_update",
        "pop",
        "popitem",
        "remove",
        "reverse",
        "setdefault",
        "sort",
        "symmetric_difference_update",
        "update",
    }
)


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _mutated_local_names(function: TestFunction) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(function):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _CONTAINER_MUTATORS
        ):
            if name := _root_name(node.func.value):
                names.add(name)
        elif isinstance(node, ast.AugAssign):
            if name := _root_name(node.target):
                names.add(name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names.update(
                name
                for target in targets
                if isinstance(target, ast.Subscript)
                and (name := _root_name(target)) is not None
            )
    return names


def _literal_local_names(
    function: TestFunction, *, include_unmutated_containers: bool = False
) -> set[str]:
    names: set[str] = set()
    mutated_names = _mutated_local_names(function)
    direct_assignments = {
        id(node)
        for node in function.body
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign))
    }
    for node in _scoped_assignments(function):
        targets: list[ast.expr]
        if isinstance(node, ast.Assign):
            targets = node.targets
        else:
            targets = [node.target]
        bound_names = {name for target in targets for name in _bound_names(target)}
        if id(node) in direct_assignments:
            names.difference_update(bound_names)
        if isinstance(node, ast.AugAssign):
            continue
        if isinstance(node, ast.Assign):
            if len(node.targets) > 1:
                try:
                    ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    continue
                names.update(
                    name for target in node.targets for name in _bound_names(target)
                )
            elif isinstance(node.targets[0], (ast.List, ast.Tuple)):
                names.update(_destructured_literal_names(node.targets[0], node.value))
            elif isinstance(node.targets[0], ast.Name):
                target_name = node.targets[0].id
                try:
                    ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    continue
                if isinstance(node.value, ast.Constant) or (
                    include_unmutated_containers and target_name not in mutated_names
                ):
                    names.add(target_name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            try:
                ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
            if isinstance(node.value, ast.Constant) or (
                include_unmutated_containers and node.target.id not in mutated_names
            ):
                names.add(node.target.id)
    return names


def _literal_module_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        elif isinstance(node, ast.AugAssign):
            names.difference_update(_bound_names(node.target))
            continue
        if value is None:
            continue
        bound_names = {name for target in targets for name in _bound_names(target)}
        names.difference_update(bound_names)
        try:
            ast.literal_eval(value)
        except (ValueError, TypeError):
            continue
        names.update(name for target in targets for name in _bound_names(target))
    return names


def _scoped_functions(function: TestFunction) -> list[TestFunction]:
    return _function_scope(function).functions


def _named_observer_function(
    name: str, tree: ast.Module, function: TestFunction
) -> TestFunction | None:
    candidates = _scoped_functions(function)
    candidates.extend(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    return next((candidate for candidate in candidates if candidate.name == name), None)


def _return_values(function: TestFunction) -> list[ast.expr]:
    return _function_scope(function).return_values


def _has_arguments(function: TestFunction | ast.Lambda) -> bool:
    arguments = function.args
    return bool(
        arguments.posonlyargs
        or arguments.args
        or arguments.kwonlyargs
        or arguments.vararg
        or arguments.kwarg
    )


def _expanded_function_references(
    names: set[str], observer_function: TestFunction | None
) -> set[str]:
    if observer_function is None:
        return names
    dependencies: dict[str, set[str]] = {}
    for node in observer_function.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if not isinstance(target, ast.Name) or value is None:
            continue
        dependencies[target.id] = {
            child.id for child in ast.walk(value) if isinstance(child, ast.Name)
        }
    expanded = set(names)
    pending = list(names)
    while pending:
        name = pending.pop()
        for dependency in dependencies.get(name, set()) - expanded:
            expanded.add(dependency)
            pending.append(dependency)
    return expanded


def _expression_uses_runtime_state(
    expression: ast.expr,
    tree: ast.Module,
    function: TestFunction,
    *,
    observer_function: TestFunction | None = None,
    include_unmutated_containers: bool = False,
    required_names: frozenset[str] | None = None,
    seen_functions: frozenset[tuple[int, int]] = frozenset(),
) -> bool:
    if _static_result(expression) is not _UNKNOWN_RESULT:
        return False
    referenced = {
        node.id for node in ast.walk(expression) if isinstance(node, ast.Name)
    }
    literal_names: set[str] = set()
    if observer_function is not None:
        literal_names = _literal_local_names(
            observer_function,
            include_unmutated_containers=include_unmutated_containers,
        )
    named_calls: dict[str, TestFunction] = {}
    for node in ast.walk(expression):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        called_function = _named_observer_function(node.func.id, tree, function)
        if called_function is not None:
            named_calls[node.func.id] = called_function
    referenced -= (
        literal_names
        | _OBSERVER_BUILTINS
        | named_calls.keys()
        | _literal_local_names(
            function,
            include_unmutated_containers=include_unmutated_containers,
        )
        | _literal_module_names(tree)
    )
    referenced = _expanded_function_references(referenced, observer_function)
    directly_uses_state = bool(
        referenced if required_names is None else referenced & required_names
    )
    return directly_uses_state or any(
        _function_uses_runtime_state(
            called_function,
            tree,
            function,
            include_unmutated_containers=include_unmutated_containers,
            required_names=required_names,
            seen_functions=seen_functions,
        )
        for called_function in named_calls.values()
    )


def _function_uses_runtime_state(
    observer_function: TestFunction,
    tree: ast.Module,
    function: TestFunction,
    *,
    include_unmutated_containers: bool,
    required_names: frozenset[str] | None = None,
    seen_functions: frozenset[tuple[int, int]] = frozenset(),
) -> bool:
    function_key = (observer_function.lineno, observer_function.col_offset)
    if function_key in seen_functions or _has_arguments(observer_function):
        return False
    return_values = _return_values(observer_function)
    next_seen = seen_functions | {function_key}
    return bool(return_values) and all(
        _expression_uses_runtime_state(
            value,
            tree,
            function,
            observer_function=observer_function,
            include_unmutated_containers=include_unmutated_containers,
            required_names=required_names,
            seen_functions=next_seen,
        )
        for value in return_values
    )


def _observer_uses_runtime_state(
    observer: ast.expr,
    tree: ast.Module,
    function: TestFunction,
    *,
    include_unmutated_containers: bool,
    required_names: frozenset[str] | None = None,
) -> bool:
    if isinstance(observer, ast.Name):
        observer_function = _named_observer_function(observer.id, tree, function)
        if observer_function is None:
            return False
        return _function_uses_runtime_state(
            observer_function,
            tree,
            function,
            include_unmutated_containers=include_unmutated_containers,
            required_names=required_names,
        )
    if isinstance(observer, ast.Lambda) and _has_arguments(observer):
        return False
    expression = observer.body if isinstance(observer, ast.Lambda) else observer
    return _expression_uses_runtime_state(
        expression,
        tree,
        function,
        include_unmutated_containers=include_unmutated_containers,
        required_names=required_names,
    )


def _static_result(node: ast.expr) -> object:
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        pass
    if isinstance(node, ast.IfExp):
        condition = _static_result(node.test)
        if condition is not _UNKNOWN_RESULT:
            return _static_result(node.body if condition else node.orelse)
        body = _static_result(node.body)
        alternative = _static_result(node.orelse)
        if (
            body is not _UNKNOWN_RESULT
            and alternative is not _UNKNOWN_RESULT
            and body == alternative
        ):
            return body
    elif isinstance(node, ast.BoolOp):
        for value_node in node.values[:-1]:
            value = _static_result(value_node)
            if value is _UNKNOWN_RESULT:
                return _UNKNOWN_RESULT
            if (isinstance(node.op, ast.Or) and value) or (
                isinstance(node.op, ast.And) and not value
            ):
                return value
        return _static_result(node.values[-1])
    return _UNKNOWN_RESULT


def _executed_string_value(node: ast.expr, constants: dict[str, str]) -> str | None:
    if isinstance(node, ast.IfExp):
        try:
            condition = ast.literal_eval(node.test)
        except (ValueError, TypeError):
            return None
        selected = node.body if condition else node.orelse
        return _executed_string_value(selected, constants)
    return _string_value(node, constants)


def _is_explicit_non_option_value(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "str"
        and len(node.args) == 1
        and not node.keywords
    )


def _call_argv_node(call: ast.Call) -> ast.expr | None:
    return (
        call.args[0]
        if call.args
        else next(
            (keyword.value for keyword in call.keywords if keyword.arg == "argv"), None
        )
    )


def _call_argv_strings(call: ast.Call, constants: dict[str, str]) -> list[str] | None:
    argv = _call_argv_node(call)
    if not isinstance(argv, (ast.List, ast.Tuple)):
        return None
    values: list[str] = []
    for element in argv.elts:
        value = _executed_string_value(element, constants)
        if value is not None:
            values.append(value)
        elif not _is_explicit_non_option_value(element):
            return None
    return values


def _node_names(node: ast.AST) -> set[str]:
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}


def _updater_baseline_names(
    function: TestFunction,
    updater_call: ast.Call,
    updater_aliases: set[str],
    constants: dict[str, str],
) -> tuple[frozenset[str], frozenset[str]]:
    names: set[str] = set()
    captured_names: set[str] = set()
    argv = _call_argv_node(updater_call)
    if isinstance(argv, (ast.List, ast.Tuple)):
        for option_node, value_node in zip(argv.elts, argv.elts[1:]):
            option = _executed_string_value(option_node, constants)
            if option is not None and any(
                token in option.lower() for token in ("baseline", "floor")
            ):
                names.update(_node_names(value_node))

    mutated_names = _mutated_local_names(function)
    for call in ast.walk(function):
        if not (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "setattr"
            and len(call.args) >= 3
            and isinstance(call.args[0], ast.Name)
            and call.args[0].id in updater_aliases
        ):
            continue
        attribute = _executed_string_value(call.args[1], constants)
        if attribute is None:
            continue
        value = call.args[2]
        value_names = _node_names(value)
        if isinstance(value, ast.Lambda):
            value_names -= {argument.arg for argument in value.args.args}
        attribute = attribute.lower()
        if "baseline" in attribute or "floor" in attribute:
            names.update(value_names)
            if isinstance(value, ast.Lambda):
                captured_names.update(value_names & mutated_names)
        elif attribute.startswith(("dump", "write")):
            captured_names.update(value_names & mutated_names)
            names.update(captured_names)
    names -= updater_aliases | _OBSERVER_BUILTINS | {"monkeypatch"}
    captured_names &= names
    return frozenset(names), frozenset(captured_names)


_PERSISTED_STATE_READERS = frozenset({"read_bytes", "read_text"})


def _observer_target(
    observer: ast.expr, tree: ast.Module, function: TestFunction
) -> ast.AST | None:
    if not isinstance(observer, ast.Name):
        return observer
    observer_function = _named_observer_function(observer.id, tree, function)
    if observer_function is None:
        return None
    return ast.Module(body=observer_function.body, type_ignores=[])


def _observer_reads_persisted_state(
    observer: ast.expr,
    tree: ast.Module,
    function: TestFunction,
    baseline_names: frozenset[str],
    captured_names: frozenset[str],
) -> bool:
    target = _observer_target(observer, tree, function)
    if target is None:
        return False
    if _node_names(target) & captured_names:
        return True
    return any(
        isinstance(node, ast.Attribute)
        and node.attr in _PERSISTED_STATE_READERS
        and _root_name(node.value) in baseline_names
        for node in ast.walk(target)
    )


def _observer_depends_on_regression_state(
    observer: ast.expr,
    tree: ast.Module,
    function: TestFunction,
    baseline_names: frozenset[str],
) -> bool:
    target = _observer_target(observer, tree, function)
    if target is None:
        return False
    referenced = _node_names(target) - baseline_names - _OBSERVER_BUILTINS
    if isinstance(observer, ast.Name):
        referenced.discard(observer.id)
        observer_function = _named_observer_function(observer.id, tree, function)
        if observer_function is not None:
            referenced -= {
                name
                for assignment in _scoped_assignments(observer_function)
                for target_node in (
                    assignment.targets
                    if isinstance(assignment, ast.Assign)
                    else [assignment.target]
                )
                for name in _bound_names(target_node)
            }
    return bool(referenced)


def _proof_status(
    tree: ast.Module,
    function: TestFunction,
    source_path: str,
    mutation_flag: str,
) -> str:
    module_name = Path(source_path).with_suffix("").as_posix().replace("/", ".")
    updater_aliases = _updater_aliases(tree, function, module_name)
    harness_aliases = _updater_aliases(tree, function, PROOF_HARNESS_MODULE)
    if not updater_aliases or not harness_aliases:
        return "missing-harness"
    proof_constants = _module_string_constants(tree)
    proof_constants.update(
        _module_string_constants(ast.Module(body=function.body, type_ignores=[]))
    )
    saw_bound_updater = False
    for harness_call in ast.walk(function):
        if not isinstance(harness_call, ast.Call):
            continue
        if not (
            isinstance(harness_call.func, ast.Attribute)
            and isinstance(harness_call.func.value, ast.Name)
            and harness_call.func.value.id in harness_aliases
            and harness_call.func.attr == PROOF_HARNESS_NAME
        ):
            continue
        update_argument = next(
            (
                keyword.value
                for keyword in harness_call.keywords
                if keyword.arg == "update"
            ),
            None,
        )
        if update_argument is None:
            continue
        bound_updater_call: ast.Call | None = None
        for call in ast.walk(update_argument):
            if not isinstance(call, ast.Call):
                continue
            if not (
                isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id in updater_aliases
                and call.func.attr == "main"
            ):
                continue
            argv_strings = _call_argv_strings(call, proof_constants)
            if argv_strings is None:
                continue
            invocation_flags = [
                value for value in argv_strings if _is_monotonic_mutation_flag(value)
            ]
            if invocation_flags == [mutation_flag]:
                bound_updater_call = call
                break
        if bound_updater_call is None:
            continue
        saw_bound_updater = True
        baseline_names, captured_names = _updater_baseline_names(
            function,
            bound_updater_call,
            updater_aliases,
            proof_constants,
        )
        observers = {
            keyword.arg: keyword.value
            for keyword in harness_call.keywords
            if keyword.arg in {"regression_debt_present", "baseline_state"}
        }
        if all(
            name in observers
            and _observer_uses_runtime_state(
                observers[name],
                tree,
                function,
                include_unmutated_containers=name == "baseline_state",
                required_names=baseline_names if name == "baseline_state" else None,
            )
            and (
                _observer_depends_on_regression_state(
                    observers[name], tree, function, baseline_names
                )
                if name == "regression_debt_present"
                else _observer_reads_persisted_state(
                    observers[name],
                    tree,
                    function,
                    baseline_names,
                    captured_names,
                )
            )
            for name in ("regression_debt_present", "baseline_state")
        ):
            return "valid"
    return "vacuous-observers" if saw_bound_updater else "missing-harness"


def proof_violations(repo_root: Path) -> list[str]:
    """Return monotonic mutation commands without an exact behavioral proof."""

    update_commands = monotonic_update_commands(repo_root)
    registered_commands = set(MONOTONIC_UPDATE_PROOFS)
    findings = [
        f"{path} [{flag}]: monotonic mutation path lacks a behavioral regression proof"
        for path, flag in sorted(update_commands - registered_commands)
    ]
    findings.extend(
        f"{path} [{flag}]: behavioral proof is stale; "
        "no matching monotonic mutation command exists"
        for path, flag in sorted(registered_commands - update_commands)
    )
    for path, flag in sorted(update_commands & registered_commands):
        node_id = MONOTONIC_UPDATE_PROOFS[(path, flag)]
        test_node = _test_node(repo_root, node_id)
        if test_node is None:
            findings.append(
                f"{path} [{flag}]: behavioral proof node does not exist: {node_id}"
            )
            continue
        proof_status = _proof_status(*test_node, path, flag)
        if proof_status == "missing-harness":
            findings.append(
                f"{path} [{flag}]: behavioral proof does not exercise synthetic "
                f"regression debt through the refusal harness: {node_id}"
            )
        elif proof_status == "vacuous-observers":
            findings.append(
                f"{path} [{flag}]: behavioral proof uses constant or vacuous "
                f"regression-debt observers: {node_id}"
            )
    return findings


def violations(repo_root: Path) -> list[str]:
    """Return invalid declarations or missing monotonic-update proofs."""

    return declaration_violations(repo_root) + proof_violations(repo_root)


def main(argv: Sequence[str] | None = None) -> int:
    return gate_cli.run_gate(
        "BASELINE-UPDATE",
        violations,
        argv,
        annotation_title="Baseline update contract",
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
