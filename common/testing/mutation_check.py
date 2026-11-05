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
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPO_ROOT / "common" / "testing" / "data" / "money-mutations.json"
TIMEOUT_SECONDS = 120
DEFAULT_TOTAL_TIMEOUT = 150.0


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


def _mutation_env(
    scratch_root: Path | None = None,
    mutation: Mutation | None = None,
) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("TEST_NAMESPACE", f"mutation_{os.getpid()}")
    if scratch_root is not None:
        prefixes: list[str] = []
        if mutation is not None:
            prefixes.append(str((scratch_root / mutation.cwd).resolve()))
        prefixes.append(str(scratch_root.resolve()))
        existing = env.get("PYTHONPATH", "")
        if existing:
            prefixes.append(existing)
        env["PYTHONPATH"] = os.pathsep.join(prefixes)
    return env


def _materialise_scratch_tree(
    scratch_root: Path,
    repo_root: Path,
    mutation: Mutation,
    mutated_text: str,
) -> Path:
    """Materialise real directories along ``mutation.cwd`` and ``mutation.file`` in ``scratch_root``.

    Every sibling entry at each materialised directory level is symlinked to ``repo_root``,
    and the mutated file contents are written to ``scratch_root / mutation.file`` so
    ``repo_root`` is never modified in place (#2712).
    """
    real_dirs: set[Path] = {Path(".")}
    for rel_str in (mutation.cwd, str(Path(mutation.file).parent)):
        rel = Path(rel_str)
        if rel == Path("."):
            continue
        cur = Path(".")
        for part in rel.parts:
            cur = cur / part
            real_dirs.add(cur)

    target_rel = Path(mutation.file)
    for rel_dir in sorted(real_dirs, key=lambda p: len(p.parts)):
        src_dir = repo_root / rel_dir
        dst_dir = scratch_root / rel_dir
        dst_dir.mkdir(parents=True, exist_ok=True)
        for child in src_dir.iterdir():
            child_rel = child.relative_to(repo_root)
            if child_rel in real_dirs or child_rel == target_rel:
                continue
            dst_child = scratch_root / child_rel
            if not dst_child.exists() and not dst_child.is_symlink():
                dst_child.symlink_to(child)

    scratch_target = scratch_root / target_rel
    scratch_target.parent.mkdir(parents=True, exist_ok=True)
    scratch_target.write_text(mutated_text, encoding="utf-8")
    return scratch_target


def _kill_process_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):  # pragma: no cover - race on exit
        pass


def apply_and_run(
    mutation: Mutation,
    *,
    repo_root: Path = REPO_ROOT,
    python: str | None = None,
    timeout: float = TIMEOUT_SECONDS,
) -> tuple[bool, str]:
    """Materialise ``mutation`` in an isolated scratch tree, run its guard, and return ``(caught, reason)``."""
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
    mutated_text = original.replace(mutation.find, mutation.replace, 1)
    with tempfile.TemporaryDirectory(prefix="mutation-check-") as tmp_dir:
        scratch_root = Path(tmp_dir)
        _materialise_scratch_tree(scratch_root, repo_root, mutation, mutated_text)
        proc = subprocess.Popen(
            resolved_cmd,
            cwd=scratch_root / mutation.cwd,
            env=_mutation_env(scratch_root, mutation),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_process_group(proc.pid)
            proc.wait()
            return (
                False,
                f"the guard did not finish within {timeout:g}s — the property is unproven",
            )
        except BaseException:  # pragma: no cover - interrupted by signal
            _kill_process_group(proc.pid)
            proc.wait()
            raise

    if proc.returncode == 1:
        return True, ""
    if proc.returncode == 5:
        return False, "the guard collected 0 tests (pytest exit code 5)"
    if proc.returncode != 0:
        return (
            False,
            f"the guard exited with status {proc.returncode} instead of test-failure exit code 1",
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
    total_timeout: float = DEFAULT_TOTAL_TIMEOUT,
) -> int:
    """Execute the declared mutations and return exit code (0 when caught or advisory, 1 when inert)."""
    declared = list(mutations if mutations is not None else load(manifest))
    if only:
        declared = [mutation for mutation in declared if mutation.id == only]
        if not declared:
            print(f"no mutation named {only!r}", file=sys.stderr)
            return 1

    deadline = time.monotonic() + total_timeout
    inert: list[str] = []
    for mutation in declared:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            why = "unproven (total deadline exceeded)"
            print(f"  INERT    {mutation.id}: {why}")
            inert.append(f"{mutation.id} ({mutation.guard}): {why}")
            continue
        effective_timeout = min(float(TIMEOUT_SECONDS), remaining)
        caught, why = apply_and_run(
            mutation,
            repo_root=repo_root,
            python=python,
            timeout=effective_timeout,
        )
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
        repo_root=REPO_ROOT,
    )


if __name__ == "__main__":
    raise SystemExit(main())
