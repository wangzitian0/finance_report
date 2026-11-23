"""The work list of the blind-except rule only shrinks (#2964, #3153).

`apps/backend/pyproject.toml` selects `BLE` and lists, in `per-file-ignores`, the files of `src` that still hold a
blind `except Exception` without a reason. A file that is clean must leave the list, and a file that holds a new
blind catch must carry a reason (`# noqa: BLE001 - <why>`): the list is not a place to add files.
"""

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "apps" / "backend"
CLEAN_PACKAGES = ("src/llm/", "src/reconciliation/")


def _work_list() -> set[str]:
    config = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    ignores = config["tool"]["ruff"]["lint"]["per-file-ignores"]
    return {path for path, rules in ignores.items() if path.startswith("src/") and "BLE001" in rules}


def _files_with_a_blind_catch() -> set[str]:
    """Run ruff without the work list: the files that hold a blind catch with no reason."""
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "src", "--select", "BLE001", "--isolated", "--output-format", "concise"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "BLE001" in result.stdout or "All checks passed" in result.stdout, result.stdout + result.stderr
    return {line.split(":")[0] for line in result.stdout.splitlines() if "BLE001" in line}


def test_the_work_list_names_exactly_the_files_that_still_hold_a_blind_catch() -> None:
    work_list, found = _work_list(), _files_with_a_blind_catch()
    assert sorted(found - work_list) == [], "a file holds a blind catch and is not on the work list: add a reason"
    assert sorted(work_list - found) == [], "a file on the work list is clean: remove its entry"


def test_the_packages_of_the_model_call_paths_are_not_on_the_work_list() -> None:
    assert [path for path in _work_list() if path.startswith(CLEAN_PACKAGES)] == []
    assert len(_work_list()) > 10  # the list is read, not empty by accident
