"""Advisory mutation reproof runner for ledger and classification invariants (#2448).

Applies each declared mutation from ``common/testing/data/money-mutations.json`` one at a time,
runs its targeted pytest guard in ``apps/backend`` with ``-n0 --no-cov -x -q``, requires a
genuine assertion failure (exit code ``1`` — rejecting pytest collection/usage/empty-selection
exit codes ``2..5``), and restores the source file in a ``finally`` block.

In advisory mode (``--advisory``), surviving mutations emit ``::warning::`` annotations and
exit ``0``. In strict mode (default), surviving mutations exit ``1``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPO_ROOT / "common" / "testing" / "data" / "money-mutations.json"
TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class Mutation:
    """A single source-code mutation and the pytest guard that must reject it."""

    id: str
    guard: str
    file: str
    find: str
    replace: str
    command: tuple[str, ...]
    cwd: str


def load(path: Path = DEFAULT_MANIFEST) -> list[Mutation]:
    """Load declared mutations from the JSON manifest."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        Mutation(
            id=entry["id"],
            guard=entry["guard"],
            file=entry["file"],
            find=entry["find"],
            replace=entry["replace"],
            command=tuple(entry["command"]),
            cwd=entry["cwd"],
        )
        for entry in raw["mutations"]
    ]


def _resolve_command(command: tuple[str, ...], python: str) -> list[str]:
    return [python if part == "{python}" else part for part in command]


def _mutation_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("TEST_NAMESPACE", f"mutation_{os.getpid()}")
    return env


def apply_and_run(
    mutation: Mutation,
    *,
    repo_root: Path = REPO_ROOT,
    python: str | None = None,
    timeout: int = TIMEOUT_SECONDS,
) -> tuple[bool, str]:
    """Apply ``mutation``, run its guard command, restore the file, and return ``(caught, reason)``."""
    target = repo_root / mutation.file
    original = target.read_text(encoding="utf-8")
    matches = original.count(mutation.find)
    if matches == 0:
        return (
            False,
            f"anchor not found in {mutation.file} — the mutation no longer applies",
        )
    if matches > 1:
        return (
            False,
            f"anchor matches {matches} times in {mutation.file} — pin it to a unique context",
        )

    resolved_cmd = _resolve_command(mutation.command, python or sys.executable)
    target.write_text(
        original.replace(mutation.find, mutation.replace, 1), encoding="utf-8"
    )
    try:
        result = subprocess.run(
            resolved_cmd,
            cwd=repo_root / mutation.cwd,
            env=_mutation_env(),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return (
            False,
            f"the guard did not finish within {timeout}s — the property is unproven",
        )
    finally:
        target.write_text(original, encoding="utf-8")

    if result.returncode == 1:
        return True, ""
    if result.returncode == 5:
        return False, "the guard collected 0 tests (pytest exit code 5)"
    if result.returncode != 0:
        return (
            False,
            f"the guard exited with status {result.returncode} instead of test-failure exit code 1",
        )
    return False, "the guard passed with the property broken"


def run(
    *,
    only: str = "",
    advisory: bool = False,
    mutations: Sequence[Mutation] | None = None,
    manifest: Path = DEFAULT_MANIFEST,
    repo_root: Path = REPO_ROOT,
    python: str | None = None,
) -> int:
    """Execute the declared mutations and return exit code (0 when caught or advisory, 1 when inert)."""
    declared = list(mutations if mutations is not None else load(manifest))
    if only:
        declared = [mutation for mutation in declared if mutation.id == only]
        if not declared:
            print(f"no mutation named {only!r}", file=sys.stderr)
            return 1

    inert: list[str] = []
    for mutation in declared:
        caught, why = apply_and_run(mutation, repo_root=repo_root, python=python)
        if caught:
            print(f"  caught   {mutation.id}")
        else:
            print(f"  INERT    {mutation.id}: {why}")
            inert.append(f"{mutation.id} ({mutation.guard}): {why}")

    if inert:
        print("", file=sys.stderr)
        for entry in inert:
            if advisory:
                print(f"::warning::guard is inert: {entry}", flush=True)
            else:
                print(f"guard is inert: {entry}", file=sys.stderr)
        summary = (
            f"{len(inert)} of {len(declared)} declared money/classification properties "
            f"survived mutation."
        )
        if advisory:
            print(f"::warning::{summary} (advisory mode, exit 0)", flush=True)
            return 0
        print(f"\n{summary}", file=sys.stderr)
        return 1

    print(f"\nall {len(declared)} declared money/classification properties are guarded")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        default="",
        help="Run only the mutation with this id.",
    )
    parser.add_argument(
        "--advisory",
        action="store_true",
        help="Emit warnings instead of failing when a mutation survives.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Path to the mutation manifest JSON file.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return run(
        only=args.only,
        advisory=args.advisory,
        manifest=args.manifest,
    )


if __name__ == "__main__":
    raise SystemExit(main())
