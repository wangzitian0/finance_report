"""Diff-aware pre-push verification dispatcher."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PY = "{python}"
MATCHING_PATHS = "{matching_paths}"

Runner = Callable[[Sequence[str], str], int]
Git = Callable[[Sequence[str]], str]

TIERS: tuple[str, ...] = ("static",)
DEFAULT_SUBPROCESS_TIMEOUT: int = 180


@dataclass(frozen=True)
class Check:
    """A named gate that runs ``commands`` when a changed path matches ``globs``."""

    name: str
    globs: tuple[str, ...]
    commands: tuple[tuple[str, ...], ...]
    why: str
    cwd: str = "."
    tier: str = "static"


def _py_check(
    name: str,
    globs: tuple[str, ...],
    script: str,
    *args: str,
    why: str,
    cwd: str = ".",
    tier: str = "static",
) -> Check:
    return Check(
        name=name,
        globs=globs,
        commands=((PY, script, *args),),
        why=why,
        cwd=cwd,
        tier=tier,
    )


OPENAPI_INPUT_GLOBS: tuple[str, ...] = (
    "apps/backend/src/routers/*.py",
    "apps/backend/src/*/extension/api/*.py",
    "apps/backend/src/schemas/*.py",
    "apps/backend/src/main.py",
)

CHECKS: tuple[Check, ...] = (
    _py_check(
        "migration-risk",
        ("apps/backend/migrations/*",),
        "tools/check_migration_risk.py",
        why="Alembic migration changed: classify migration risk",
    ),
    Check(
        name="backend-format",
        globs=("apps/backend/*.py",),
        commands=(
            (PY, "-m", "ruff", "check", "src", "tests"),
            (PY, "-m", "ruff", "format", "--check", "src", "tests"),
        ),
        why="backend Python changed: ruff lint + format check",
        cwd="apps/backend",
    ),
    _py_check(
        "env-manifests",
        (
            "apps/backend/src/config.py",
            "apps/frontend/required-env.manifest.json",
            "common/runtime/env_manifests.py",
            "runtime-hooks.manifest.json",
            ".env.example",
            ".env",
            ".env.*",
        ),
        "tools/env_manifests.py",
        "--check",
        why="config.py, env files, or a manifest changed: the infra2 SDK manifest check and the .env.example block must pass",
    ),
    Check(
        name="openapi-spec",
        globs=OPENAPI_INPUT_GLOBS,
        commands=(
            (PY, "tools/generate_openapi_spec.py", "--check"),
            (PY, "tools/check_api_types.py"),
        ),
        why="router/schema changed: openapi.json and frontend api-types must remain in sync (#1004, #2134)",
    ),
    _py_check(
        "toolchain-contract",
        (
            "toolchain.toml",
            ".python-version",
            ".node-version",
            ".tool-versions",
            ".moon/toolchain.yml",
            "apps/frontend/package.json",
            "tools/check_toolchain_contract.py",
            "common/runtime/check_toolchain_contract.py",
            ".github/workflows/*.yml",
            ".github/actions/**/*.yml",
            "docker-compose*.yml",
            "apps/*/Dockerfile",
        ),
        "tools/check_toolchain_contract.py",
        why="toolchain contracts and version declarations must not drift",
    ),
    _py_check(
        "lockfile-registry",
        (
            "package-lock.json",
            "*package-lock.json",
            "apps/frontend/package.json",
            "tools/check_lockfile_registry.py",
            "common/testing/lockfile_registry.py",
        ),
        "tools/check_lockfile_registry.py",
        why="lockfile or registry gate changed: every resolved package URL must use https://registry.npmjs.org/ (#2668)",
    ),
    Check(
        name="frontend-static",
        globs=(
            "apps/frontend/src/*",
            "apps/frontend/package.json",
            "apps/frontend/tsconfig.json",
            "apps/frontend/openapi.json",
        ),
        commands=(
            ("npm", "run", "lint"),
            ("npm", "run", "typecheck"),
            ("npm", "run", "check:api-types"),
        ),
        why="frontend changed: eslint + tsc typecheck + openapi api-types contract sync",
        cwd="apps/frontend",
    ),
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool


def _matches(path: str, glob: str) -> bool:
    return fnmatch.fnmatch(path, glob)


def select_checks(
    changed_files: Iterable[str],
    *,
    checks: Sequence[Check] = CHECKS,
    tier: str = "full",
) -> list[Check]:
    """Return checks whose globs match at least one changed file for ``tier``."""
    if tier != "full" and tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}: expected one of {('full', *TIERS)}")
    files = list(changed_files)
    return [
        check
        for check in checks
        if (tier == "full" or check.tier == tier)
        and any(_matches(f, g) for f in files for g in check.globs)
    ]


def select_named_checks(
    names: Iterable[str],
    *,
    checks: Sequence[Check] = CHECKS,
) -> list[Check]:
    """Return checks with the given names in registry order, failing on unknowns."""
    wanted = list(dict.fromkeys(names))
    known = {check.name for check in checks}
    unknown = [name for name in wanted if name not in known]
    if unknown:
        raise ValueError(
            f"unknown gate name(s): {', '.join(unknown)}; known: {', '.join(sorted(known))}"
        )
    return [check for check in checks if check.name in wanted]


def _default_git(args: Sequence[str]) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    ).stdout


def changed_files(base: str | None = None, *, git: Git = _default_git) -> list[str]:
    """Union of committed-vs-base, staged, unstaged, and untracked paths."""
    if base is None:
        base = git(["merge-base", "HEAD", "origin/main"]).strip() or "HEAD"
    out: set[str] = set()
    for args in (
        ["diff", "--name-only", base],
        ["diff", "--name-only"],
        ["diff", "--name-only", "--cached"],
        ["ls-files", "--others", "--exclude-standard"],
    ):
        out.update(line for line in git(args).splitlines() if line.strip())
    return sorted(out)


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("TEST_NAMESPACE", f"preflight_{os.getpid()}")
    return env


def _exec_runner(argv: Sequence[str], cwd: str, *, quiet: bool = False) -> int:
    try:
        kwargs = (
            {"capture_output": True, "text": True, "errors": "replace"} if quiet else {}
        )
        proc = subprocess.run(
            list(argv),
            cwd=cwd,
            env=_child_env(),
            check=False,
            timeout=DEFAULT_SUBPROCESS_TIMEOUT,
            **kwargs,
        )
        if quiet and proc.returncode != 0:
            for stream, buf in ((sys.stdout, proc.stdout), (sys.stderr, proc.stderr)):
                if buf:
                    stream.write(buf)
                    stream.flush()
        return proc.returncode
    except subprocess.TimeoutExpired:
        print(
            f"::error::Gate command timed out after {DEFAULT_SUBPROCESS_TIMEOUT}s: {' '.join(argv)}",
            flush=True,
        )
        return 124


def _default_runner(argv: Sequence[str], cwd: str) -> int:
    return _exec_runner(argv, cwd, quiet=False)


def _default_quiet_runner(argv: Sequence[str], cwd: str) -> int:
    return _exec_runner(argv, cwd, quiet=True)


def _resolve(
    command: tuple[str, ...],
    python: str,
    *,
    matching_paths: Sequence[str] = (),
) -> list[str]:
    resolved: list[str] = []
    for part in command:
        if part == PY:
            resolved.append(python)
        elif part == MATCHING_PATHS:
            resolved.extend(matching_paths)
        else:
            resolved.append(part)
    return resolved


def _unquote_porcelain_path(raw: str) -> str:
    if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return raw


def _working_tree_snapshot(repo_root: Path = REPO_ROOT) -> dict[str, str]:
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:  # pragma: no cover - non-git dir fallback
        return {}
    snapshot: dict[str, str] = {"__porcelain__": proc.stdout}
    for line in proc.stdout.splitlines():
        rel_path = line[3:]
        if " -> " in rel_path:
            rel_path = rel_path.split(" -> ", 1)[1]
        rel_path = _unquote_porcelain_path(rel_path)
        full_path = repo_root / rel_path
        snapshot[rel_path] = (
            hashlib.sha256(full_path.read_bytes()).hexdigest()
            if full_path.is_file()
            else "<non-file>"
        )
    return snapshot


def run_checks(
    checks: Sequence[Check],
    *,
    changed_files: Sequence[str] = (),
    runner: Runner = _default_runner,
    python: str | None = None,
    ci: bool = False,
    quiet: bool = False,
    repo_root: Path | None = None,
) -> list[CheckResult]:
    """Run each check's commands, failing fast on the first non-zero command."""
    python = python or sys.executable
    root = repo_root or REPO_ROOT
    is_default_runner = runner in (_default_runner, _default_quiet_runner)
    guard_tree = is_default_runner or repo_root is not None
    dedup_results: dict[tuple[tuple[str, ...], str], bool] = {}

    prepared: list[tuple[Check, str, list[tuple[str, ...]]]] = []
    for check in checks:
        cwd = str(root / check.cwd)
        matching_paths = tuple(
            path
            for path in changed_files
            if any(_matches(path, glob) for glob in check.globs)
        )
        resolved_cmds = [
            tuple(_resolve(command, python, matching_paths=matching_paths))
            for command in check.commands
        ]
        prepared.append((check, cwd, resolved_cmds))

    batch_snapshot = (
        _working_tree_snapshot(root)
        if guard_tree and is_default_runner and len(prepared) > 1
        else None
    )
    results: list[CheckResult] = []
    for check, cwd, resolved_cmds in prepared:
        if ci and not quiet:
            print(f"::group::Gate [{check.tier}] {check.name}", flush=True)
        if is_default_runner and all(
            dedup_results.get((cmd, cwd)) is True for cmd in resolved_cmds
        ):
            ok = True
        else:
            before_snapshot = (
                batch_snapshot
                if batch_snapshot is not None
                else (_working_tree_snapshot(root) if guard_tree else {})
            )
            ok = True
            for cmd in resolved_cmds:
                if is_default_runner and dedup_results.get((cmd, cwd)) is True:
                    continue
                if runner(list(cmd), cwd) != 0:
                    ok = False
                    break
                if is_default_runner:
                    dedup_results[(cmd, cwd)] = True
            if (
                batch_snapshot is None
                and guard_tree
                and _working_tree_snapshot(root) != before_snapshot
            ):
                ok = False
                for cmd in resolved_cmds:
                    dedup_results.pop((cmd, cwd), None)
                print(
                    f"::error::Gate {check.name} mutated the working tree during execution",
                    file=sys.stderr,
                    flush=True,
                )
        if ci:
            if not quiet:
                print("::endgroup::", flush=True)
            if not ok:
                print(f"::error::Gate {check.name} failed: {check.why}", flush=True)
        results.append(CheckResult(check.name, ok))
    if (
        batch_snapshot is not None
        and _working_tree_snapshot(root) != batch_snapshot
    ):
        last_name = results[-1].name if results else "static"
        print(
            f"::error::Gate {last_name} mutated the working tree during execution",
            file=sys.stderr,
            flush=True,
        )
        results = [CheckResult(r.name, False) for r in results]
    return results


def _collect_matching_tests(
    search_dir: Path, base_root: Path, stem: str, dest: set[str]
) -> None:
    if search_dir.is_dir():
        for match in search_dir.rglob(f"test_{stem}*.py"):
            if match.is_file():
                dest.add(str(match.relative_to(base_root)))


def resolve_changed_pytest_targets(
    changed_files_list: Iterable[str],
    *,
    repo_root: Path = REPO_ROOT,
) -> tuple[list[str], list[str]]:
    """Map changed repo-relative paths to (root_test_targets, backend_test_targets)."""
    root_selected: set[str] = set()
    backend_selected: set[str] = set()
    backend_root = repo_root / "apps" / "backend"
    backend_tests_dir = backend_root / "tests"
    root_tests_dir = repo_root / "tests"

    for rel in changed_files_list:
        path_obj = Path(rel)
        if not rel.endswith(".py"):
            continue
        if rel.startswith("apps/backend/tests/") and path_obj.name.startswith("test_"):
            if (repo_root / rel).is_file():
                backend_selected.add(rel.removeprefix("apps/backend/"))
            continue
        if rel.startswith("tests/") and path_obj.name.startswith("test_"):
            if (repo_root / rel).is_file():
                root_selected.add(rel)
            continue
        stem = path_obj.stem
        if stem == "__init__":
            continue
        if rel.startswith("apps/backend/src/"):
            _collect_matching_tests(
                backend_tests_dir, backend_root, stem, backend_selected
            )
        elif rel.startswith(("common/", "tools/")):
            _collect_matching_tests(root_tests_dir, repo_root, stem, root_selected)
            if rel.startswith("common/"):
                _collect_matching_tests(
                    backend_tests_dir, backend_root, stem, backend_selected
                )

    return sorted(root_selected), sorted(backend_selected)


def _static_cache_path(repo_root: Path, git: Git) -> Path | None:
    git_dir = git(["rev-parse", "--git-dir"]).strip()
    if not git_dir:
        return None
    path = Path(git_dir)
    if not path.is_absolute():
        path = repo_root / path
    return path / "preflight-static.stamp"


def _static_fingerprint(
    repo_root: Path, base: str | None, files: Sequence[str], git: Git
) -> str:
    head_sha = git(["rev-parse", "HEAD"]).strip()
    base_ref = (
        git(["merge-base", "HEAD", "origin/main"]).strip()
        if base is None
        else git(["rev-parse", base]).strip()
    )
    snapshot = _working_tree_snapshot(repo_root)
    payload = {
        "head": head_sha,
        "base": base_ref,
        "files": list(files),
        "snapshot": snapshot,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _read_static_stamp(cache_file: Path | None) -> str:
    if cache_file is None or not cache_file.is_file():
        return ""
    try:
        return cache_file.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _write_static_stamp(cache_file: Path | None, fingerprint: str) -> None:
    if cache_file is None:
        return
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(f"{fingerprint}\n", encoding="utf-8")
    except OSError:
        pass


def run(
    argv: Sequence[str] | None = None,
    *,
    runner: Runner = _default_runner,
    git: Git = _default_git,
    repo_root: Path | None = None,
    cache_file: Path | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        description="Run the gate checks relevant to the current diff."
    )
    parser.add_argument("--base", default=None)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--changed", nargs="*", default=None)
    parser.add_argument("--tier", choices=("full", *TIERS), default="static")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--only", action="append", default=None, metavar="NAME")
    parser.add_argument("--pytest-changed", action="store_true")
    parser.add_argument("--ci", action="store_true")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args(argv)

    root = repo_root or REPO_ROOT
    if args.only:
        if args.all or args.changed is not None:
            parser.error("--only cannot combine with --all or --changed")
        try:
            selected = select_named_checks(args.only)
        except ValueError as exc:
            parser.error(str(exc))
        files: Sequence[str] = ()
    elif args.all:
        files = ()
        selected = [
            check for check in CHECKS if args.tier == "full" or check.tier == args.tier
        ]
    else:
        files = (
            args.changed
            if args.changed is not None
            else changed_files(args.base, git=git)
        )
        selected = select_checks(files, tier=args.tier)

    if args.list:
        if not selected or args.all:
            inventory = [
                check
                for check in CHECKS
                if args.tier == "full" or check.tier == args.tier
            ]
            print(
                f"Registered preflight gate inventory ({args.tier} tier, {len(inventory)} gates):"
            )
            for check in inventory:
                print(f"  [{check.tier}] {check.name}: {check.why}")
            return 0
        for check in selected:
            print(f"  [{check.tier}] {check.name}: {check.why}")
        return 0

    effective_runner = (
        _default_quiet_runner if runner is _default_runner and args.quiet else runner
    )
    root_targets, backend_targets = (
        resolve_changed_pytest_targets(files, repo_root=root)
        if args.pytest_changed
        else ([], [])
    )
    if not selected and not root_targets and not backend_targets:
        print("preflight: no relevant gates for the current diff.")
        return 0

    use_cache = (
        args.tier == "static"
        and not args.only
        and not args.all
        and args.changed is None
        and not args.pytest_changed
        and not args.ci
        and os.environ.get("PREFLIGHT_NO_CACHE") != "1"
        and (
            cache_file is not None
            or (runner is _default_runner and git is _default_git)
        )
    )
    resolved_cache_file = (
        cache_file
        if cache_file is not None
        else (_static_cache_path(root, git) if use_cache else None)
    )
    fingerprint = _static_fingerprint(root, args.base, files, git) if use_cache else ""
    if (
        use_cache
        and fingerprint
        and _read_static_stamp(resolved_cache_file) == fingerprint
    ):
        print(
            f"preflight: static cache hit ({fingerprint[:12]}); skipping duplicate run."
        )
        return 0

    def _report_result(name: str, ok: bool) -> None:
        if not args.quiet:
            print(f"  [{'ok' if ok else 'FAIL'}] {name}")
        elif not ok:
            print(f"  [FAIL] {name}")

    had_external_ns = "TEST_NAMESPACE" in os.environ
    generated_ns = f"preflight_{os.getpid()}"
    if not had_external_ns:
        os.environ["TEST_NAMESPACE"] = generated_ns

    failed: list[str] = []
    pytest_suites_ran = 0
    ran_pytest = bool(args.pytest_changed and (root_targets or backend_targets)) or any(
        cmd[1:3] == ("-m", "pytest") for check in selected for cmd in check.commands
    )
    try:
        if selected:
            if not args.quiet:
                msg = (
                    f"preflight: running {len(selected)} named gate(s)..."
                    if args.only
                    else f"preflight: running {len(selected)} gate(s) for {len(files)} changed file(s)..."
                )
                print(msg)
            results = run_checks(
                selected,
                changed_files=files,
                runner=effective_runner,
                ci=args.ci,
                quiet=args.quiet,
                repo_root=root,
            )
            for result in results:
                _report_result(result.name, result.ok)
                if not result.ok:
                    failed.append(result.name)

        if args.pytest_changed and not failed:
            for label, targets, target_cwd in (
                ("pytest-changed:root", root_targets, root),
                ("pytest-changed:backend", backend_targets, root / "apps" / "backend"),
            ):
                if not targets or failed:
                    continue
                pytest_suites_ran += 1
                cmd = [
                    sys.executable,
                    "-m",
                    "pytest",
                    *targets,
                    "-x",
                    "-q",
                    "--no-cov",
                    "-n",
                    "0",
                    "-o",
                    "addopts=",
                ]
                ok = effective_runner(cmd, str(target_cwd)) == 0
                _report_result(label, ok)
                if not ok:
                    failed.append(label)
    finally:
        if not had_external_ns:
            os.environ.pop("TEST_NAMESPACE", None)
            if runner is _default_runner and ran_pytest:
                from common.testing.reap_test_dbs import (
                    drop_namespace_databases,
                    reap_orphaned_test_databases,
                )

                drop_namespace_databases(generated_ns)
                reap_orphaned_test_databases(ephemeral_only=True, repo_root=root)

    if failed:
        print(f"preflight: {len(failed)} gate(s) failed: {', '.join(failed)}")
        return 1
    if use_cache and fingerprint:
        _write_static_stamp(resolved_cache_file, fingerprint)
    if args.quiet:
        print(f"preflight: all {len(selected) + pytest_suites_ran} gates passed.")
    else:
        print("preflight: all relevant gates passed.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)
