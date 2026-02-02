#!/usr/bin/env python3
"""
scripts/cleanup_orphaned_dbs.py

Clean up orphaned worker databases left by interrupted test runs.
Uses the active_namespaces.json tracker to find leaked resources.

Usage:
    python scripts/cleanup_orphaned_dbs.py [--dry-run] [--all]

Options:
    --dry-run   Show what would be cleaned without actually deleting
    --all       Clean ALL test databases (not just orphaned ones)
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

CACHE_DIR = Path.home() / ".cache" / "finance_report"
ACTIVE_NAMESPACES_FILE = CACHE_DIR / "active_namespaces.json"
DB_CONTAINER_NAME = "finance-report-db"

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
        result = subprocess.run(
            [
                runtime,
                "exec",
                DB_CONTAINER_NAME,
                "psql",
                "-U",
                "postgres",
                "-t",
                "-c",
                "SELECT datname FROM pg_database WHERE datname LIKE 'finance_report_test_%'",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        databases = [
            db.strip() for db in result.stdout.strip().split("\n") if db.strip()
        ]
        return databases
    except subprocess.CalledProcessError as e:
        log(f"❌ Failed to list databases: {e}", RED)
        return []


def extract_namespace(db_name):
    match = re.match(r"finance_report_test_([^_]+(?:_[^_]+)*?)(?:_gw\d+)?$", db_name)
    if match:
        return match.group(1)
    return None


def drop_database(runtime, db_name, dry_run=False):
    if dry_run:
        log(f"   [DRY RUN] Would drop: {db_name}", YELLOW)
        return True

    try:
        subprocess.run(
            [
                runtime,
                "exec",
                DB_CONTAINER_NAME,
                "psql",
                "-U",
                "postgres",
                "-c",
                f"DROP DATABASE IF EXISTS {db_name};",
            ],
            capture_output=True,
            check=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def cleanup_orphaned(dry_run=False, clean_all=False):
    runtime = get_container_runtime()
    if not runtime:
        log("❌ No container runtime (docker/podman) found.", RED)
        return 1

    log("🔍 Checking for orphaned test databases...", YELLOW)

    container_check = subprocess.run(
        [runtime, "ps", "-q", "-f", f"name={DB_CONTAINER_NAME}"],
        capture_output=True,
    )
    if not container_check.stdout.strip():
        log(f"⚠️  Container '{DB_CONTAINER_NAME}' not running", YELLOW)
        log("   Start infrastructure: moon run :infra", YELLOW)
        return 1

    databases = list_test_databases(runtime)
    if not databases:
        log("✅ No test databases found", GREEN)
        return 0

    log(f"   Found {len(databases)} test database(s)", YELLOW)

    if clean_all:
        log("   Mode: Clean ALL test databases", YELLOW)
        to_clean = databases
    else:
        active_namespaces = load_active_namespaces()
        log(f"   Active namespaces: {active_namespaces or 'none'}", YELLOW)

        to_clean = []
        for db in databases:
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
        if drop_database(runtime, db, dry_run):
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


def main():
    parser = argparse.ArgumentParser(
        description="Clean up orphaned test databases from interrupted test runs"
    )
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
    args = parser.parse_args()

    return cleanup_orphaned(dry_run=args.dry_run, clean_all=args.all)


if __name__ == "__main__":
    sys.exit(main())
