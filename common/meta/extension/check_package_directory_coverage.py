"""``check_package_directory_coverage`` — no directory under ``common/`` goes ungoverned.

``check_package_contract`` discovers packages *additively*: it globs
``common/*/contract.py`` and validates modules that export
``CONTRACT = PackageContract(...)``. That makes it easy to add a package, but it
means a directory dropped into ``common/`` without a discoverable contract is
invisible to it -- exactly how ``common/ci``, ``common/shell``, and
``common/ssot`` accumulated as undeclared "junk drawers" before they were
dissolved back into real packages (#1564-#1568, #1430).

This gate closes that gap from the other direction: it enumerates every
directory directly under ``common/`` and requires each one to either ship a
``contract.py`` with a module-level ``CONTRACT = PackageContract(...)`` or be a
documented entry in :data:`UNGOVERNED_EXCEPTIONS`. The migration clean-up in
#1430 retired the last residual exception (``common/ssot``), so the list is now
empty and a shrink-only ratchet: a brand-new directory with neither a
discoverable contract nor an exception entry is rejected, so the junk-drawer
pattern cannot silently recur, and the list may not silently regrow.

stdlib only (no pyyaml/pydantic) so the gate runs anywhere, including the
lightweight CI lint environment.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

# This module lives at common/meta/extension/check_package_directory_coverage.py,
# so the repo root is three parents up (extension -> meta -> common -> repo).
REPO_ROOT = Path(__file__).resolve().parents[3]

IGNORED_DIR_NAMES = {"__pycache__"}

# Directories under common/ that are deliberately, not accidentally, ungoverned
# today. Shrink-only ratchet: the migration clean-up in #1430 retires the last
# residual ``common/ssot`` escape hatch, so new entries should be exceptional.
UNGOVERNED_EXCEPTIONS: dict[str, str] = {}


def _has_real_content(dir_path: Path) -> bool:
    """True if the tree holds any file outside a ``__pycache__`` directory.

    A package directory deleted from git can leave stale, untracked
    ``__pycache__`` bytecode behind on a developer's existing checkout (Python
    does not clean these up when the source is removed). Such a directory is
    dead local debris, not an undeclared package, so it must not fail the gate.
    """
    return any(
        "__pycache__" not in path.relative_to(dir_path).parts
        for path in dir_path.rglob("*")
        if path.is_file()
    )


def discover_common_dirs(repo_root: Path) -> list[str]:
    """Every directory directly under common/, excluding caches and dotdirs."""
    common_dir = repo_root / "common"
    return sorted(
        p.name
        for p in common_dir.iterdir()
        if p.is_dir()
        and p.name not in IGNORED_DIR_NAMES
        and not p.name.startswith(".")
        and _has_real_content(p)
    )


def _is_package_contract_call(value: ast.expr) -> bool:
    """Whether ``value`` is a direct ``PackageContract(...)`` constructor call."""
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    return isinstance(func, ast.Name) and func.id == "PackageContract"


def _declares_discoverable_contract(contract_path: Path) -> bool:
    """Whether package discovery can see a module-level package contract export."""
    try:
        tree = ast.parse(contract_path.read_text(encoding="utf-8"))
    except SyntaxError:
        return False
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id == "CONTRACT"
                for target in node.targets
            ) and _is_package_contract_call(node.value):
                return True
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "CONTRACT"
            and node.value is not None
            and _is_package_contract_call(node.value)
        ):
            return True
    return False


def check_directory_coverage(repo_root: Path) -> list[str]:
    """Every common/<dir> ships a discoverable contract or is excepted."""
    errors: list[str] = []
    for name in discover_common_dirs(repo_root):
        contract_path = repo_root / "common" / name / "contract.py"
        if contract_path.exists() and _declares_discoverable_contract(contract_path):
            continue
        if name in UNGOVERNED_EXCEPTIONS:
            continue
        if contract_path.exists():
            errors.append(
                f"common/{name}/contract.py does not export a module-level "
                "CONTRACT = PackageContract(...), so package discovery and "
                "governance cannot see it."
            )
            continue
        errors.append(
            f"common/{name}/ has no contract.py and is not a documented "
            "exception in UNGOVERNED_EXCEPTIONS "
            "(common/meta/extension/check_package_directory_coverage.py). Ship "
            f"a PackageContract (common/{name}/contract.py) or add a reasoned "
            "exception entry."
        )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Repository root to scan (default: this file's repo).",
    )
    args = parser.parse_args(argv)

    errors = check_directory_coverage(Path(args.repo_root))
    if errors:
        print("[DIRECTORY COVERAGE] FAILED:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(
        "[DIRECTORY COVERAGE] PASSED: every common/ directory is governed or excepted."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
