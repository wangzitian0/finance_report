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


def _literal_local_names(function: TestFunction) -> set[str]:
    names: set[str] = set()
    for node in function.body:
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
            elif isinstance(node.targets[0], ast.Name) and isinstance(
                node.value, ast.Constant
            ):
                names.add(node.targets[0].id)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and isinstance(node.value, ast.Constant)
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
        if value is None:
            continue
        try:
            ast.literal_eval(value)
        except (ValueError, TypeError):
            continue
        names.update(name for target in targets for name in _bound_names(target))
    return names


def _observer_uses_runtime_state(
    observer: ast.expr, tree: ast.Module, function: TestFunction
) -> bool:
    if isinstance(observer, ast.Name):
        return False
    lambda_arguments: set[str] = set()
    if isinstance(observer, ast.Lambda):
        lambda_arguments = {argument.arg for argument in observer.args.args}
    referenced = {node.id for node in ast.walk(observer) if isinstance(node, ast.Name)}
    referenced -= (
        lambda_arguments
        | _OBSERVER_BUILTINS
        | _literal_local_names(function)
        | _literal_module_names(tree)
    )
    return bool(referenced)


def _executed_string_value(node: ast.expr, constants: dict[str, str]) -> str | None:
    if isinstance(node, ast.IfExp):
        try:
            condition = ast.literal_eval(node.test)
        except (ValueError, TypeError):
            return None
        selected = node.body if condition else node.orelse
        return _executed_string_value(selected, constants)
    return _string_value(node, constants)


def _call_argv_strings(call: ast.Call, constants: dict[str, str]) -> set[str]:
    argv = (
        call.args[0]
        if call.args
        else next(
            (keyword.value for keyword in call.keywords if keyword.arg == "argv"), None
        )
    )
    if not isinstance(argv, (ast.List, ast.Tuple)):
        return set()
    return {
        value
        for element in argv.elts
        if (value := _executed_string_value(element, constants)) is not None
    }


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
        updater_is_bound = False
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
            if mutation_flag in _call_argv_strings(call, proof_constants):
                updater_is_bound = True
                break
        if not updater_is_bound:
            continue
        saw_bound_updater = True
        observers = {
            keyword.arg: keyword.value
            for keyword in harness_call.keywords
            if keyword.arg in {"regression_debt_present", "baseline_state"}
        }
        if all(
            name in observers
            and _observer_uses_runtime_state(observers[name], tree, function)
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
