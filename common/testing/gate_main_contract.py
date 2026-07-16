"""Allowlist-free structural contract for repository command entry points."""

from __future__ import annotations

import ast
from collections.abc import Sequence
from pathlib import Path

from common.meta.base.gate_cli import run_gate

REPO_ROOT = Path(__file__).resolve().parents[2]


def _python_files(repo_root: Path) -> list[Path]:
    return [
        path
        for root_name in ("common", "tools")
        if (root := repo_root / root_name).exists()
        for path in sorted(root.rglob("*.py"))
    ]


def _module_main(tree: ast.Module) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    return next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "main"
        ),
        None,
    )


def _main_is_standard(main: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if isinstance(main, ast.AsyncFunctionDef):
        return False
    if main.returns is None or ast.unparse(main.returns) != "int":
        return False
    if (
        main.args.posonlyargs
        or main.args.vararg
        or main.args.kwarg
        or main.args.kwonlyargs
    ):
        return False
    if len(main.args.args) != 1 or len(main.args.defaults) != 1:
        return False
    argv = main.args.args[0]
    default = main.args.defaults[0]
    return (
        argv.arg == "argv"
        and argv.annotation is not None
        and ast.unparse(argv.annotation) == "Sequence[str] | None"
        and isinstance(default, ast.Constant)
        and default.value is None
    )


def _uses_shared_gate_runner(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "run_gate":
            return True
        if isinstance(node.func, ast.Attribute) and node.func.attr == "run_gate":
            return True
    return False


def _has_standard_process_exit(tree: ast.Module) -> bool:
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        if ast.unparse(node.test) != "__name__ == '__main__'":
            continue
        invokes_main = any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "main"
            for call in ast.walk(node)
        )
        if not invokes_main:
            continue
        if len(node.body) != 1 or not isinstance(node.body[0], ast.Raise):
            return False
        exc = node.body[0].exc
        return (
            isinstance(exc, ast.Call)
            and isinstance(exc.func, ast.Name)
            and exc.func.id == "SystemExit"
            and len(exc.args) == 1
            and ast.unparse(exc.args[0]) == "main()"
        )
    return True


def current_debt(repo_root: Path) -> dict[str, set[str]]:
    """Return every malformed module or command that violates the contract."""

    debt = {
        "legacy_main_contract": set(),
        "legacy_gate_cli": set(),
        "legacy_process_exit": set(),
        "malformed_python": set(),
    }
    for path in _python_files(repo_root):
        relative = path.relative_to(repo_root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            debt["malformed_python"].add(relative)
            continue
        main = _module_main(tree)
        if main is None:
            continue
        if not _main_is_standard(main):
            debt["legacy_main_contract"].add(relative)
        if (
            path.name.startswith("check_")
            and relative.startswith("common/")
            and not _uses_shared_gate_runner(tree)
        ):
            debt["legacy_gate_cli"].add(relative)
        if not _has_standard_process_exit(tree):
            debt["legacy_process_exit"].add(relative)
    return debt


def violations(repo_root: Path) -> list[str]:
    return [
        f"{kind}: {path}"
        for kind, paths in current_debt(repo_root).items()
        for path in sorted(paths)
    ]


def main(argv: Sequence[str] | None = None) -> int:
    return run_gate(
        "GATE-MAIN",
        violations,
        argv,
        annotation_title="Gate main contract",
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
