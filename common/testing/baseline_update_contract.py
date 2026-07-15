"""Enforce explicit, monotonic semantics for baseline mutation flags."""

from __future__ import annotations

import ast
from collections.abc import Sequence
from pathlib import Path

from common.testing import gate_cli

MONOTONIC_MODES = frozenset({"raise-only", "shrink-only"})
REWRITE_MODE = "rewrite"
VALID_MODES = MONOTONIC_MODES | {REWRITE_MODE}


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


def _mutation_flags(tree: ast.Module) -> set[str]:
    flags: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "add_argument":
            continue
        flags.update(
            arg.value
            for arg in node.args
            if isinstance(arg, ast.Constant)
            and arg.value in {"--update", "--rewrite-baseline"}
        )
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
                "--update" in _mutation_flags(tree)
                and _declared_mode(tree) in MONOTONIC_MODES
            ):
                paths.add(path.relative_to(repo_root).as_posix())
    return paths


def violations(repo_root: Path) -> list[str]:
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
            if "--update" in flags and mode not in MONOTONIC_MODES:
                findings.append(
                    f"{relative}: rewrite mode must use --rewrite-baseline, not --update"
                )
            if "--rewrite-baseline" in flags and mode != REWRITE_MODE:
                findings.append(
                    f"{relative}: --rewrite-baseline requires BASELINE_UPDATE_MODE = 'rewrite'"
                )
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    return gate_cli.run_gate(
        "BASELINE-UPDATE",
        violations,
        argv,
        annotation_title="Baseline update contract",
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
