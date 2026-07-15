"""Shrink-only contract for repository gate entry points."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = REPO_ROOT / "common/testing/data/gate-main-contract-baseline.json"
BASELINE_UPDATE_MODE = "shrink-only"


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


def _has_none_default(main: ast.FunctionDef | ast.AsyncFunctionDef, index: int) -> bool:
    positional = [*main.args.posonlyargs, *main.args.args]
    default_offset = len(positional) - len(main.args.defaults)
    if index < default_offset:
        return False
    default = main.args.defaults[index - default_offset]
    return isinstance(default, ast.Constant) and default.value is None


def _main_is_standard(main: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if main.returns is None or ast.unparse(main.returns) != "int":
        return False
    positional = [*main.args.posonlyargs, *main.args.args]
    for index, arg in enumerate(positional):
        if arg.arg != "argv":
            continue
        return (
            arg.annotation is not None
            and ast.unparse(arg.annotation) == "Sequence[str] | None"
            and _has_none_default(main, index)
        )
    return False


def _uses_shared_gate_runner(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "run_gate":
            return True
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "run_gate"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "gate_cli"
        ):
            return True
    return False


def current_debt(repo_root: Path) -> dict[str, set[str]]:
    """Return legacy main signatures and check modules bypassing gate_cli."""

    main_debt: set[str] = set()
    gate_cli_debt: set[str] = set()
    for path in _python_files(repo_root):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        main = _module_main(tree)
        if main is None:
            continue
        relative = path.relative_to(repo_root).as_posix()
        if not _main_is_standard(main):
            main_debt.add(relative)
        if (
            path.name.startswith("check_")
            and relative.startswith("common/")
            and not _uses_shared_gate_runner(tree)
        ):
            gate_cli_debt.add(relative)
    return {
        "legacy_main_contract": main_debt,
        "legacy_gate_cli": gate_cli_debt,
    }


def load_baseline(path: Path) -> dict[str, set[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    result: dict[str, set[str]] = {}
    for key in ("legacy_main_contract", "legacy_gate_cli"):
        values = payload.get(key)
        if not isinstance(values, list) or not all(
            isinstance(value, str) for value in values
        ):
            raise ValueError(f"{path}: {key} must be a list of paths")
        result[key] = set(values)
    return result


def write_baseline(path: Path, debt: dict[str, set[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {key: sorted(values) for key, values in sorted(debt.items())}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _diff_findings(
    current: dict[str, set[str]], baseline: dict[str, set[str]]
) -> tuple[list[str], list[str]]:
    new: list[str] = []
    stale: list[str] = []
    for key in ("legacy_main_contract", "legacy_gate_cli"):
        new.extend(
            f"{key}: new debt {path}" for path in sorted(current[key] - baseline[key])
        )
        stale.extend(
            f"{key}: resolved path still baselined {path}"
            for path in sorted(baseline[key] - current[key])
        )
    return new, stale


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--baseline", type=Path, default=None)
    parser.add_argument(
        "--update",
        action="store_true",
        help="Drop resolved legacy paths; refuses to adopt new contract debt.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    repo_root = args.repo_root.resolve()
    baseline_path = args.baseline or (
        repo_root / DEFAULT_BASELINE.relative_to(REPO_ROOT)
    )
    current = current_debt(repo_root)
    baseline = load_baseline(baseline_path)
    new, stale = _diff_findings(current, baseline)

    if new:
        for finding in new:
            print(f"::error title=Gate main contract::{finding}", file=sys.stderr)
        outcome = "--update REFUSED" if args.update else "FAILED"
        print(
            f"[GATE-MAIN] {outcome}: {len(new)} new debt path(s).",
            file=sys.stderr,
        )
        return 1
    if args.update:
        write_baseline(baseline_path, current)
        print("[GATE-MAIN] baseline tightened.")
        return 0
    if stale:
        for finding in stale:
            print(f"::error title=Gate main contract::{finding}", file=sys.stderr)
        print(
            f"[GATE-MAIN] FAILED: {len(stale)} resolved path(s) must be pruned with --update.",
            file=sys.stderr,
        )
        return 1
    print("[GATE-MAIN] PASSED: no entry-point or gate-runner debt grew.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
