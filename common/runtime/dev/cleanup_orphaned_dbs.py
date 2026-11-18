#!/usr/bin/env python3
"""
Clean up orphaned worker databases left by interrupted test runs.

Uses the active_namespaces.json tracker to find leaked resources.

Usage:
    python tools/cleanup_orphaned_dbs.py [--dry-run] [--all]

Options:
    --dry-run   Show what would be cleaned without actually deleting
    --all       Clean ALL test databases (not just orphaned ones)
"""

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
DB_CONTAINER_NAME = "finance-report-db"
_DB_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"


def log(msg, color=RESET):
    print(f"{color}{msg}{RESET}")


def get_container_runtime():
    for runtime in ["podman", "docker"]:
        if subprocess.run(["which", runtime], capture_output=True).returncode == 0:
            return runtime
    return None


def _host_psql_target() -> tuple[str, str, str, str]:
    raw_url = os.environ.get("DATABASE_URL", "").strip()
    if raw_url:
        parsed = urlparse(raw_url)
        host = parsed.hostname or "127.0.0.1"
        port = str(parsed.port or 5432)
        user = parsed.username or "postgres"
        password = parsed.password or ""
        return host, port, user, password
    return "127.0.0.1", "5432", "postgres", ""


def _psql_cmd(target: str, sql: str, *, tuples_only: bool = False) -> list[str]:
    flags = ["-t", "-A"] if tuples_only else []
    if target == "host":
        host, port, user, _ = _host_psql_target()
        return ["psql", "-h", host, "-p", port, "-U", user, "-d", "postgres", *flags, "-c", sql]
    return [target, "exec", DB_CONTAINER_NAME, "psql", "-U", "postgres", *(["-t"] if tuples_only else []), "-c", sql]


def _stdout_text(result) -> str:
    raw = getattr(result, "stdout", "")
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return raw or ""


def _run_psql(target: str, sql: str, *, tuples_only: bool = False, check: bool = True):
    cmd = _psql_cmd(target, sql, tuples_only=tuples_only)
    kwargs: dict = {"capture_output": True}
    if check:
        kwargs["text"] = True
        kwargs["check"] = True
    if target == "host":
        _, _, _, password = _host_psql_target()
        if password:
            kwargs["env"] = {**os.environ, "PGPASSWORD": password}
    return subprocess.run(cmd, **kwargs)


def host_postgres_ready() -> bool:
    if not shutil.which("psql"):
        return False
    try:
        res = _run_psql("host", "SELECT 1", tuples_only=True, check=False)
        return getattr(res, "returncode", 1) == 0 and _stdout_text(res).strip() == "1"
    except (OSError, subprocess.SubprocessError):
        return False


def load_active_namespaces():
    if not ACTIVE_NAMESPACES_FILE.exists():
        return []
    try:
        return json.loads(ACTIVE_NAMESPACES_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        log("⚠️  Warning: Corrupted active namespaces file", YELLOW)
        return []


def list_test_databases(runtime):
    try:
        result = _run_psql(
            runtime,
            "SELECT datname FROM pg_database WHERE datname LIKE 'finance_report_test%'",
            tuples_only=True,
        )
        databases = [db.strip() for db in result.stdout.strip().split("\n") if db.strip()]
        return databases
    except subprocess.CalledProcessError as e:
        log(f"❌ Failed to list databases: {e}", RED)
        return []


def list_active_databases(runtime) -> set[str]:
    try:
        result = _run_psql(
            runtime,
            "SELECT datname FROM pg_stat_database WHERE datname LIKE 'finance_report_test%' AND numbackends > 0",
            tuples_only=True,
            check=False,
        )
        if getattr(result, "returncode", 1) != 0:
            return set()
        return {db.strip() for db in _stdout_text(result).strip().splitlines() if db.strip()}
    except (OSError, subprocess.SubprocessError):
        return set()


def extract_namespace(db_name):
    match = re.match(r"finance_report_test_([^_]+(?:_[^_]+)*?)(?:_gw\d+)?$", db_name)
    if match:
        return match.group(1)
    return None


def drop_database(runtime, db_name, dry_run=False):
    if not _DB_NAME_RE.fullmatch(db_name):
        return False
    if dry_run:
        log(f"   [DRY RUN] Would drop: {db_name}", YELLOW)
        return True

    try:
        _run_psql(runtime, f'DROP DATABASE IF EXISTS "{db_name}";')
        return True
    except subprocess.CalledProcessError:
        return False


def _resolve_target() -> str | None:
    runtime = get_container_runtime()
    if runtime:
        container_check = subprocess.run(
            [runtime, "ps", "-q", "-f", f"name={DB_CONTAINER_NAME}"],
            capture_output=True,
        )
        if container_check.stdout.strip():
            return runtime
    if host_postgres_ready():
        log("   Using host PostgreSQL (container not running)", YELLOW)
        return "host"
    if not runtime:
        log("❌ No container runtime (docker/podman) or host PostgreSQL found.", RED)
    else:
        log(f"⚠️  Container '{DB_CONTAINER_NAME}' not running and host PostgreSQL unavailable", YELLOW)
        log("   Start infrastructure: moon run :dev -- --infra", YELLOW)
    return None


def cleanup_orphaned(dry_run=False, clean_all=False):
    log("🔍 Checking for orphaned test databases...", YELLOW)
    target = _resolve_target()
    if not target:
        return 1

    databases = list_test_databases(target)
    if not databases:
        log("✅ No test databases found", GREEN)
        return 0

    log(f"   Found {len(databases)} test database(s)", YELLOW)
    active_dbs = list_active_databases(target)

    if clean_all:
        log("   Mode: Clean ALL test databases", YELLOW)
        to_clean = [db for db in databases if db not in active_dbs]
        for db in databases:
            if db in active_dbs:
                log(f"   SKIP (in use): {db}", GREEN)
    else:
        active_namespaces = load_active_namespaces()
        log(f"   Active namespaces: {active_namespaces or 'none'}", YELLOW)

        to_clean = []
        for db in databases:
            if db in active_dbs:
                log(f"   SKIP (in use): {db}", GREEN)
                continue
            namespace = extract_namespace(db)
            if namespace and namespace in active_namespaces:
                log(f"   SKIP (active): {db} (namespace: {namespace})", GREEN)
            else:
                to_clean.append(db)

    if not to_clean:
        log("✅ No orphaned databases to clean", GREEN)
        return 0

    log(
        f"\n🧹 {'[DRY RUN] Would clean' if dry_run else 'Cleaning'} {len(to_clean)} database(s):",
        YELLOW,
    )

    success_count = 0
    for db in to_clean:
        if drop_database(target, db, dry_run):
            log(f"   ✓ {db}", GREEN)
            success_count += 1
        else:
            log(f"   ✗ Failed to drop {db}", RED)

    if dry_run:
        log(
            f"\n💡 Run without --dry-run to actually clean {success_count} database(s)",
            YELLOW,
        )
    else:
        log(f"\n✅ Cleaned {success_count}/{len(to_clean)} database(s)", GREEN)

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clean up orphaned test databases from interrupted test runs")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be cleaned without actually deleting",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Clean ALL test databases (not just orphaned ones)",
    )
    args = parser.parse_args() if argv is None else parser.parse_args(argv)

    return cleanup_orphaned(dry_run=args.dry_run, clean_all=args.all)


if __name__ == "__main__":
    raise SystemExit(main())
