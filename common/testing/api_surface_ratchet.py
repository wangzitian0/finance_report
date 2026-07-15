"""Shrink-only API-surface migration locks (#1865 S2 PR-A).

The terminal home for an HTTP adapter is its owning package's
``extension/api/`` directory. ``src/routers`` remains only as a transitional
delivery layer, so it must not gain new flat router modules. Domain packages
also still have transitional ``src.schemas`` imports; the number of package
files carrying that dependency may only decrease until the vocabulary is fully
repatriated.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Sequence

from common.meta.base.layering import PACKAGE_LAYER

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "apps" / "backend" / "src"
ROUTERS_DIR = BACKEND_SRC / "routers"
BASELINE_PATH = Path(__file__).parent / "data" / "api-surface-ratchet-baseline.json"

TERMINAL_API_HOME = "extension/api"


def _relative_to_root(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def router_files() -> set[str]:
    if not ROUTERS_DIR.exists():
        return set()
    return {
        _relative_to_root(path)
        for path in ROUTERS_DIR.glob("*.py")
        if path.name != "__init__.py"
    }


def _package_dirs() -> list[Path]:
    return [
        BACKEND_SRC / name
        for name in sorted(PACKAGE_LAYER)
        if name not in {"backend", "frontend", "meta", "testing"}
        and (BACKEND_SRC / name).is_dir()
    ]


def _imports_schemas(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "src.schemas" or (
                node.module is not None and node.module.startswith("src.schemas.")
            ):
                return True
        elif isinstance(node, ast.Import):
            if any(
                alias.name == "src.schemas" or alias.name.startswith("src.schemas.")
                for alias in node.names
            ):
                return True
    return False


def package_schema_import_file_count() -> int:
    return sum(
        _imports_schemas(path)
        for package_dir in _package_dirs()
        for path in package_dir.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def base_schema_import_files() -> list[str]:
    """Return forbidden package-base dependencies on delivery schemas."""
    violations: list[str] = []
    for package_dir in _package_dirs():
        base_dir = package_dir / "base"
        if not base_dir.is_dir():
            continue
        violations.extend(
            _relative_to_root(path)
            for path in base_dir.rglob("*.py")
            if "__pycache__" not in path.parts and _imports_schemas(path)
        )
    return sorted(violations)


def _load_baseline() -> dict[str, object]:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    router_files = baseline.get("router_files")
    if not isinstance(router_files, list) or not all(
        isinstance(path, str) for path in router_files
    ):
        raise ValueError("api-surface ratchet baseline requires router_files list")
    if type(baseline.get("package_schema_import_files")) is not int:
        raise ValueError(
            "api-surface ratchet baseline requires package_schema_import_files int"
        )
    return baseline


def _write_baseline(*, current_routers: set[str], current_import_files: int) -> None:
    BASELINE_PATH.write_text(
        json.dumps(
            {
                "router_files": sorted(current_routers),
                "package_schema_import_files": current_import_files,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if set(args) - {"--update"}:
        print("usage: api_surface_ratchet.py [--update]", file=sys.stderr)
        return 2

    baseline = _load_baseline()
    current_routers = router_files()
    current_import_files = package_schema_import_file_count()
    forbidden_base_imports = base_schema_import_files()
    baseline_routers = set(baseline["router_files"])
    baseline_import_files = baseline["package_schema_import_files"]
    assert isinstance(baseline_import_files, int)

    new_routers = sorted(current_routers - baseline_routers)
    import_growth = current_import_files > baseline_import_files
    if new_routers or import_growth or forbidden_base_imports:
        errors = []
        if new_routers:
            errors.append(f"new flat router files: {', '.join(new_routers)}")
        if import_growth:
            errors.append(
                "package files importing src.schemas grew "
                f"({baseline_import_files} -> {current_import_files})"
            )
        if forbidden_base_imports:
            errors.append(
                "base layers import src.schemas: " + ", ".join(forbidden_base_imports)
            )
        prefix = "REFUSED" if "--update" in args else "ERROR"
        print(f"{prefix}: {'; '.join(errors)}", file=sys.stderr)
        return 1

    if "--update" in args:
        _write_baseline(
            current_routers=current_routers,
            current_import_files=current_import_files,
        )
        print("api-surface ratchet baseline tightened")
        return 0

    print(
        "api-surface-ratchet: "
        f"routers {len(current_routers)} <= {len(baseline_routers)}, "
        "package files importing schemas "
        f"{current_import_files} <= {baseline_import_files}, base imports 0"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
