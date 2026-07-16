"""Enforce explicit, monotonic semantics for baseline mutation flags."""

from __future__ import annotations

import ast
from collections.abc import Sequence
from pathlib import Path

from common.testing import gate_cli

MONOTONIC_MODES = frozenset({"raise-only", "shrink-only"})
REWRITE_MODE = "rewrite"
VALID_MODES = MONOTONIC_MODES | {REWRITE_MODE}
UPDATE_FLAG = "--" + "update"
REWRITE_FLAG = "--rewrite-" + "baseline"
MUTATION_FLAGS = frozenset({UPDATE_FLAG, REWRITE_FLAG})

MONOTONIC_UPDATE_PROOFS = {
    "common/meta/extension/check_ac_tier_baseline.py": (
        "tests/tooling/test_s4_gate_contracts.py"
        "::test_AC_testing_governance_21_real_updates_refuse_regression_debt"
    ),
    "common/meta/extension/check_app_boundary.py": (
        "tests/tooling/test_s4_gate_contracts.py"
        "::test_AC_testing_governance_21_real_updates_refuse_regression_debt"
    ),
    "common/testing/api_surface_ratchet.py": (
        "tests/tooling/test_api_surface_ratchet.py"
        "::test_router_ratchet_rejects_new_file_and_update_cannot_adopt_it"
    ),
    "common/testing/check_ac_score_baseline.py": (
        "tests/tooling/test_s4_gate_contracts.py"
        "::test_AC_testing_governance_21_real_updates_refuse_regression_debt"
    ),
    "common/testing/check_cassette_graded_eval.py": (
        "tests/tooling/test_s4_gate_contracts.py"
        "::test_AC_testing_governance_21_real_updates_refuse_regression_debt"
    ),
    "common/testing/check_critical_value_proof.py": (
        "tests/tooling/test_critical_value_proof_ratchet.py"
        "::test_baseline_only_shrinks_never_grows"
    ),
    "common/testing/fe_api_handmock_ratchet.py": (
        "tests/tooling/test_fe_api_handmock_ratchet.py"
        "::test_AC_testing_fe_handmock_1_ratchet_is_locked_and_only_goes_down"
    ),
    "common/testing/fe_fetch_ratchet.py": (
        "tests/tooling/test_fe_fetch_ratchet.py"
        "::test_AC_testing_fe_fetch_1_ratchet_is_locked_and_only_goes_down"
    ),
    "common/testing/gate_main_contract.py": (
        "tests/tooling/test_s4_gate_contracts.py"
        "::test_AC_testing_governance_21_real_updates_refuse_regression_debt"
    ),
    "common/testing/mirror_ratchet.py": (
        "tests/tooling/test_package_declaration_and_ratchet.py"
        "::test_AC8_24_3_mirror_assertion_ratchet_is_locked_and_only_goes_down"
    ),
    "common/testing/tool_shim_contract.py": (
        "tests/tooling/test_s4_gate_contracts.py"
        "::test_AC_testing_governance_21_real_updates_refuse_regression_debt"
    ),
}


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
                if (value := _string_value(arg, constants)) in MUTATION_FLAGS
            )
        elif isinstance(node, ast.Compare):
            value = _string_value(node.left, constants)
            if value not in MUTATION_FLAGS:
                continue
            if any(
                isinstance(operator, (ast.In, ast.NotIn))
                and _is_argument_sequence(comparator)
                for operator, comparator in zip(node.ops, node.comparators, strict=True)
            ):
                flags.add(value)
    return flags


def monotonic_update_paths(repo_root: Path) -> set[str]:
    """Return every module that exposes a monotonic ``--update`` path."""

    paths: set[str] = set()
    for root_name in ("common", "tools"):
        root = repo_root / root_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if (
                UPDATE_FLAG in _mutation_flags(tree)
                and _declared_mode(tree) in MONOTONIC_MODES
            ):
                paths.add(path.relative_to(repo_root).as_posix())
    return paths


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
            if REWRITE_FLAG in flags and mode != REWRITE_MODE:
                findings.append(
                    f"{relative}: --rewrite-baseline requires BASELINE_UPDATE_MODE = 'rewrite'"
                )
    return findings


def _test_node_exists(repo_root: Path, node_id: str) -> bool:
    test_path_text, separator, test_name = node_id.partition("::")
    if not separator or not test_name:
        return False
    test_path = repo_root / test_path_text
    if not test_path.is_file():
        return False
    tree = ast.parse(test_path.read_text(encoding="utf-8"), filename=str(test_path))
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == test_name
        for node in tree.body
    )


def proof_violations(repo_root: Path) -> list[str]:
    """Return monotonic update paths without a live behavioral proof node."""

    update_paths = monotonic_update_paths(repo_root)
    registered_paths = set(MONOTONIC_UPDATE_PROOFS)
    findings = [
        f"{path}: monotonic --update path lacks a behavioral regression proof"
        for path in sorted(update_paths - registered_paths)
    ]
    findings.extend(
        f"{path}: behavioral proof is stale; no monotonic --update path exists"
        for path in sorted(registered_paths - update_paths)
    )
    findings.extend(
        f"{path}: behavioral proof node does not exist: {MONOTONIC_UPDATE_PROOFS[path]}"
        for path in sorted(update_paths & registered_paths)
        if not _test_node_exists(repo_root, MONOTONIC_UPDATE_PROOFS[path])
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
