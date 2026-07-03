"""``check_package_directory_coverage`` — no directory under ``common/`` goes ungoverned.

``check_package_contract`` discovers packages *additively*: it globs
``common/*/contract.py`` and validates whatever it finds. That makes it easy to
add a package, but it means a directory dropped into ``common/`` WITHOUT a
``contract.py`` is invisible to it -- exactly how ``common/ci``, ``common/shell``,
and ``common/ssot`` accumulated as undeclared "junk drawers" that this repo spent
five PRs dissolving back into real packages (#1564-#1568).

This gate closes that gap from the other direction: it enumerates every
directory directly under ``common/`` and requires each one to either ship a
``contract.py`` or be a documented, reasoned entry in
:data:`UNGOVERNED_EXCEPTIONS` (a pending SSOT-only domain, or leftover files with
no clean package fit yet). A brand-new directory with neither is rejected, so the
junk-drawer pattern cannot silently recur.

stdlib only (no pyyaml/pydantic) so the gate runs anywhere, including the
lightweight CI lint environment.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# This module lives at common/meta/extension/check_package_directory_coverage.py,
# so the repo root is three parents up (extension -> meta -> common -> repo).
REPO_ROOT = Path(__file__).resolve().parents[3]

IGNORED_DIR_NAMES = {"__pycache__"}

# Directories under common/ that are deliberately, not accidentally, ungoverned
# today. Each entry names the reason so the exception can be audited and
# eventually retired (once the directory ships a contract.py or is dissolved).
UNGOVERNED_EXCEPTIONS: dict[str, str] = {
    "ssot": (
        "Leftover from the common/ci + common/ssot dissolution (#1564-#1568): "
        "houses three generator scripts with no clean package fit yet "
        "(generate_api_reference.py, generate_db_schema_reference.py, "
        "generate_openapi_spec.py) -- not a bounded context itself."
    ),
}


def discover_common_dirs(repo_root: Path) -> list[str]:
    """Every directory directly under common/, excluding caches and dotdirs."""
    common_dir = repo_root / "common"
    return sorted(
        p.name
        for p in common_dir.iterdir()
        if p.is_dir()
        and p.name not in IGNORED_DIR_NAMES
        and not p.name.startswith(".")
    )


def check_directory_coverage(repo_root: Path) -> list[str]:
    """Every common/<dir> ships a contract.py or is a documented exception."""
    errors: list[str] = []
    for name in discover_common_dirs(repo_root):
        contract_path = repo_root / "common" / name / "contract.py"
        if contract_path.exists():
            continue
        if name in UNGOVERNED_EXCEPTIONS:
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

    print("[DIRECTORY COVERAGE] PASSED: every common/ directory is governed or excepted.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
