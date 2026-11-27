"""Reap orphaned PostgreSQL test databases left by interrupted or ephemeral runs."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlparse

CACHE_DIR = Path.home() / ".cache" / "finance_report"
ACTIVE_NAMESPACES_FILE = CACHE_DIR / "active_namespaces.json"
TEST_DB_PREFIX = "finance_report_test_"
_DB_IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _psql_connection_params(
    database_url: str | None = None,
) -> tuple[str, str, str, str]:
    raw_url = (database_url or os.environ.get("DATABASE_URL") or "").strip()
    if raw_url:
        parsed = urlparse(raw_url)
        return (
            parsed.hostname or "127.0.0.1",
            str(parsed.port or 5432),
            parsed.username or "postgres",
            parsed.password or "",
        )
    return "127.0.0.1", "55432", "postgres", ""


def _run_psql(
    sql: str,
    *,
    database_url: str | None = None,
    tuples_only: bool = False,
    timeout: float = 5.0,
) -> subprocess.CompletedProcess[str] | None:
    if not shutil.which("psql"):
        return None
    host, port, user, password = _psql_connection_params(database_url)
    env = {**os.environ, "PGCONNECT_TIMEOUT": "2"}
    if password:
        env["PGPASSWORD"] = password
    flags = ["-t", "-A"] if tuples_only else []
    cmd = [
        "psql",
        "-h",
        host,
        "-p",
        port,
        "-U",
        user,
        "-d",
        "postgres",
        *flags,
        "-c",
        sql,
    ]
    try:
        return subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def extract_namespace(db_name: str) -> str | None:
    match = re.match(r"finance_report_test_([^_]+(?:_[^_]+)*?)(?:_gw\d+)?$", db_name)
    return match.group(1) if match else None


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def is_live_ephemeral_pid(namespace: str | None) -> bool:
    if not namespace:
        return False
    match = re.fullmatch(r"(?:preflight|mutation)_(\d+)", namespace)
    return bool(match and _is_pid_alive(int(match.group(1))))


def is_ephemeral_db_name(db_name: str) -> bool:
    return db_name.startswith(
        (
            f"{TEST_DB_PREFIX}preflight_",
            f"{TEST_DB_PREFIX}mutation_",
            f"{TEST_DB_PREFIX}planner_seq_",
        )
    )


def load_active_namespaces(path: Path = ACTIVE_NAMESPACES_FILE) -> list[str]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, list):
        return [str(ns) for ns in data if isinstance(ns, str) and ns]
    if isinstance(data, dict):
        return [
            str(ns)
            for ns, pids in data.items()
            if isinstance(ns, str)
            and ns
            and isinstance(pids, list)
            and any(isinstance(p, int) and _is_pid_alive(int(p)) for p in pids)
        ]
    return []


def _shorten_db_ident(value: str, max_len: int = 43) -> str:
    if len(value) <= max_len:
        return value
    import hashlib

    digest = hashlib.sha256(value.encode()).hexdigest()[:8]
    return f"{value[: max_len - 9].rstrip('_-')}_{digest}"


def active_worktree_db_names(repo_root: Path | None = None) -> set[str]:
    """Return base DB names (without `_gwN`) belonging to checked-out git worktrees."""
    root = repo_root or Path(__file__).resolve().parents[2]
    if not (root / ".git").exists():
        return set()
    try:
        res = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if res.returncode != 0:
        return set()
    import hashlib

    names: set[str] = set()
    cur_path: str | None = None
    cur_branch: str | None = None
    entries: list[tuple[Path, str | None]] = []
    for line in [*res.stdout.splitlines(), ""]:
        if not line.strip():
            if cur_path:
                entries.append((Path(cur_path), cur_branch))
            cur_path, cur_branch = None, None
        elif line.startswith("worktree "):
            cur_path = line.removeprefix("worktree ").strip()
        elif line.startswith("branch refs/heads/"):
            cur_branch = line.removeprefix("branch refs/heads/").strip()
    for wt_path, branch in entries:
        if not wt_path.exists() or not branch:
            continue
        safe = re.sub(
            r"[^a-z0-9_]", "_", branch.lower().replace("/", "_").replace("-", "_")
        )
        while "__" in safe:
            safe = safe.replace("__", "_")
        safe = safe.strip("_")
        if not safe:
            continue
        for candidate in (wt_path.resolve(), (wt_path / "apps" / "backend").resolve()):
            path_hash = hashlib.sha256(str(candidate).encode()).hexdigest()[:8]
            names.add(f"{TEST_DB_PREFIX}{_shorten_db_ident(f'{safe}_{path_hash}')}")
    return names


def _matches_active_worktree_db(db_name: str, worktree_dbs: set[str]) -> bool:
    if not worktree_dbs:
        return False
    if db_name in worktree_dbs:
        return True
    if "_gw" in db_name:
        prefix = db_name.rsplit("_gw", 1)[0]
        return any(
            wt_db[: len(prefix)] == prefix
            for wt_db in worktree_dbs
            if len(wt_db) >= len(prefix)
        )
    return False


def list_test_databases(*, database_url: str | None = None) -> list[str]:
    res = _run_psql(
        "SELECT datname FROM pg_database WHERE datname LIKE 'finance_report_test\\_%' ESCAPE '\\' ORDER BY datname;",
        database_url=database_url,
        tuples_only=True,
    )
    if res is None or res.returncode != 0:
        return []
    return [line.strip() for line in res.stdout.splitlines() if line.strip()]


def list_active_databases(*, database_url: str | None = None) -> set[str]:
    res = _run_psql(
        "SELECT datname FROM pg_stat_database WHERE datname LIKE 'finance_report_test\\_%' ESCAPE '\\' AND numbackends > 0;",
        database_url=database_url,
        tuples_only=True,
    )
    if res is None or res.returncode != 0:
        return set()
    return {line.strip() for line in res.stdout.splitlines() if line.strip()}


def drop_database(
    db_name: str,
    *,
    dry_run: bool = False,
    database_url: str | None = None,
) -> bool:
    if not _DB_IDENT_RE.fullmatch(db_name) or not db_name.startswith(TEST_DB_PREFIX):
        return False
    if dry_run:
        return True
    res = _run_psql(
        f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE);',
        database_url=database_url,
    )
    return res is not None and res.returncode == 0


def drop_namespace_databases(
    namespace: str,
    *,
    database_url: str | None = None,
) -> int:
    """Drop ephemeral databases created for ``namespace`` (including ``_gw*`` workers)."""
    if not namespace or os.environ.get("KEEP_TEST_DB") == "1":
        return 0
    safe = re.sub(r"[^a-z0-9_]", "_", namespace.lower()).strip("_")
    if not safe:
        return 0
    prefix = f"{TEST_DB_PREFIX}{safe}"[:63]
    escaped = prefix.replace("\\", "\\\\").replace("_", "\\_")
    res = _run_psql(
        f"SELECT datname FROM pg_database WHERE datname = '{prefix}' OR datname LIKE '{escaped}\\_gw%' ESCAPE '\\';",
        database_url=database_url,
        tuples_only=True,
    )
    if res is None or res.returncode != 0:
        return 0
    dropped = 0
    for name in (line.strip() for line in res.stdout.splitlines() if line.strip()):
        if drop_database(name, database_url=database_url):
            dropped += 1
    return dropped


def reap_orphaned_test_databases(
    *,
    dry_run: bool = False,
    clean_all: bool = False,
    ephemeral_only: bool = False,
    repo_root: Path | None = None,
    database_url: str | None = None,
) -> tuple[int, int]:
    """Drop idle orphaned ``finance_report_test_*`` databases; return ``(reaped, total)``."""
    databases = list_test_databases(database_url=database_url)
    if not databases:
        return 0, 0
    if ephemeral_only and not any(is_ephemeral_db_name(db) for db in databases):
        return 0, len(databases)
    active_dbs = list_active_databases(database_url=database_url)
    active_namespaces = set(load_active_namespaces())
    worktree_dbs = (
        set() if clean_all or ephemeral_only else active_worktree_db_names(repo_root)
    )
    reaped = 0
    for db in databases:
        if db in active_dbs:
            continue
        if ephemeral_only and not is_ephemeral_db_name(db):
            continue
        if not clean_all:
            if _matches_active_worktree_db(db, worktree_dbs):
                continue
            ns = extract_namespace(db)
            if ns and (ns in active_namespaces or is_live_ephemeral_pid(ns)):
                continue
        if dry_run:
            print(f"[DRY RUN] Would drop: {db}")
            reaped += 1
        elif drop_database(db, database_url=database_url):
            print(f"Dropped: {db}")
            reaped += 1
    return reaped, len(databases)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="List databases without dropping"
    )
    parser.add_argument(
        "--all", action="store_true", help="Drop all idle test databases"
    )
    args = parser.parse_args(argv)
    reaped, total = reap_orphaned_test_databases(
        dry_run=args.dry_run, clean_all=args.all
    )
    action = "Would drop" if args.dry_run else "Dropped"
    print(f"reap_test_dbs: {action} {reaped}/{total} test database(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
