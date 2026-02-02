#!/usr/bin/env python3
"""
scripts/test_lifecycle.py

A robust, Python-based test runner that manages the entire lifecycle
of the backend test environment, replacing fragile shell scripts.

Key Features:
- Manages Docker container lifecycle (Postgres) using context managers.
- Ensures cleanup on both success, failure, and interrupts (Ctrl+C).
- Integrates with 'moon' and 'pytest'.
- Tracks active namespaces for orphaned resource cleanup.

Usage:
    python scripts/test_lifecycle.py [pytest_args]
"""

import json
import os
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from isolation_utils import get_namespace, get_s3_bucket, get_test_db_name  # noqa: E402

# Constants
REPO_ROOT = Path(__file__).parent.parent.absolute()
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
BACKEND_DIR = REPO_ROOT / "apps" / "backend"
DB_CONTAINER_PREFIX = "finance-report-db"
CACHE_DIR = Path.home() / ".cache" / "finance_report"
ACTIVE_NAMESPACES_FILE = CACHE_DIR / "active_namespaces.json"

# ANSI Colors
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"


def log(msg, color=RESET):
    print(f"{color}{msg}{RESET}")


def load_active_namespaces():
    """Load list of active namespaces from persistent storage."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not ACTIVE_NAMESPACES_FILE.exists():
        return []
    try:
        return json.loads(ACTIVE_NAMESPACES_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        log("⚠️  Warning: Corrupted active namespaces file, resetting...", YELLOW)
        return []


def save_active_namespaces(namespaces):
    """Save list of active namespaces to persistent storage."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        ACTIVE_NAMESPACES_FILE.write_text(json.dumps(namespaces, indent=2))
    except OSError as e:
        log(f"⚠️  Warning: Failed to save active namespaces: {e}", YELLOW)


def register_namespace(namespace):
    """Register a namespace as active."""
    namespaces = load_active_namespaces()
    if namespace not in namespaces:
        namespaces.append(namespace)
        save_active_namespaces(namespaces)
        log(f"   Registered namespace: {namespace}", YELLOW)


def unregister_namespace(namespace):
    """Unregister a namespace (cleanup complete)."""
    namespaces = load_active_namespaces()
    if namespace in namespaces:
        namespaces.remove(namespace)
        save_active_namespaces(namespaces)
        log(f"   Unregistered namespace: {namespace}", YELLOW)


def get_container_runtime():
    """Detect podman or docker."""
    if subprocess.run(["which", "podman"], capture_output=True).returncode == 0:
        return "podman"
    if subprocess.run(["which", "docker"], capture_output=True).returncode == 0:
        return "docker"
    return None


def is_db_ready(runtime, container_name):
    """Check if Postgres is ready to accept connections."""
    try:
        subprocess.run(
            [runtime, "exec", container_name, "pg_isready", "-U", "postgres"],
            check=True,
            capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def cleanup_worker_databases(runtime, container_name, namespace):
    """Clean up pytest-xdist worker databases after test run."""
    log("🧹 Cleaning up worker databases...", YELLOW)

    # Validate namespace to prevent SQL injection (defense in depth)
    if not namespace.replace("_", "").replace("-", "").isalnum():
        log(f"   WARNING: Invalid namespace '{namespace}', skipping cleanup", YELLOW)
        return

    # Verify container is running before attempting cleanup
    check_cmd = [runtime, "ps", "-q", "-f", f"name={container_name}"]
    try:
        container_check = subprocess.run(check_cmd, capture_output=True, check=True)
        if not container_check.stdout.strip():
            log(
                f"   Container '{container_name}' not running, skipping cleanup", YELLOW
            )
            return
    except subprocess.CalledProcessError:
        log(f"   Cannot verify container '{container_name}', skipping cleanup", YELLOW)
        return

    pattern = f"finance_report_test_{namespace}_gw%"
    list_cmd = [
        runtime,
        "exec",
        container_name,
        "psql",
        "-U",
        "postgres",
        "-t",
        "-c",
        f"SELECT datname FROM pg_database WHERE datname LIKE '{pattern}'",
    ]

    try:
        result = subprocess.run(list_cmd, capture_output=True, text=True, check=True)
        databases = [
            db.strip() for db in result.stdout.strip().split("\n") if db.strip()
        ]

        if not databases:
            log("   No worker databases to clean.", YELLOW)
            return

        import re

        db_pattern = re.compile(r"^finance_report_test_[\w]+(_gw\d+)?$")

        for db_name in databases:
            if not db_pattern.match(db_name):
                log(f"   Skipping invalid database name: {db_name}", YELLOW)
                continue

            log(f"   Dropping {db_name}...", YELLOW)
            subprocess.run(
                [
                    runtime,
                    "exec",
                    container_name,
                    "psql",
                    "-U",
                    "postgres",
                    "-c",
                    f"DROP DATABASE IF EXISTS {db_name};",
                ],
                capture_output=True,
            )

        log(f"   Cleaned {len(databases)} worker database(s).", GREEN)
    except subprocess.CalledProcessError as e:
        log(f"   Warning: Failed to clean worker databases: {e}", YELLOW)


@contextmanager
def test_database():
    """Context manager to spin up and tear down the test database with namespace isolation."""
    runtime = get_container_runtime()
    if not runtime:
        log("❌ No container runtime (docker/podman) found.", RED)
        sys.exit(1)

    namespace = get_namespace()
    test_db_name = get_test_db_name(namespace)

    log(f"🔧 Test namespace: {namespace}", YELLOW)
    log(f"🔧 Test database: {test_db_name}", YELLOW)

    # Register namespace for orphan cleanup tracking
    register_namespace(namespace)

    compose_cmd = [runtime, "compose", "-f", str(COMPOSE_FILE)]

    log("🐘 Ensuring infrastructure is up...", YELLOW)
    try:
        subprocess.run([*compose_cmd, "--profile", "infra", "up", "-d"], check=True)
    except subprocess.CalledProcessError:
        log("❌ Failed to start database.", RED)
        unregister_namespace(namespace)
        raise

    # Find the actual container name (in case of compose project name variations)
    # We look for the one defined in docker-compose.yml or generated
    # Simple approach: ask compose for the container name
    try:
        res = subprocess.run(
            [*compose_cmd, "ps", "--format", "{{.Name}}", "postgres"],
            capture_output=True,
            text=True,
        )
        container_name = res.stdout.strip()
        if not container_name:
            # Fallback if format not supported or empty
            # Just try standard name
            container_name = "finance-report-db"
    except Exception:
        container_name = "finance-report-db"

    log(f"   Container: {container_name}", YELLOW)

    # Wait for Readiness
    log("⏳ Waiting for Postgres...", YELLOW)
    ready = False
    for i in range(30):
        if is_db_ready(runtime, container_name):
            ready = True
            break
        time.sleep(1)

    if not ready:
        log("❌ Database failed to become ready.", RED)
        unregister_namespace(namespace)
        raise Exception("Database not ready")

    log("🛠  Setting up test database...", YELLOW)
    create_db_cmd = [
        runtime,
        "exec",
        container_name,
        "psql",
        "-U",
        "postgres",
        "-tc",
        f"SELECT 1 FROM pg_database WHERE datname='{test_db_name}'",
    ]
    res = subprocess.run(create_db_cmd, capture_output=True, text=True)
    if "1" in res.stdout:
        log(f"   Dropping existing '{test_db_name}' database...", YELLOW)
        subprocess.run(
            [
                runtime,
                "exec",
                container_name,
                "psql",
                "-U",
                "postgres",
                "-c",
                f"DROP DATABASE {test_db_name};",
            ],
            check=True,
        )

    subprocess.run(
        [
            runtime,
            "exec",
            container_name,
            "psql",
            "-U",
            "postgres",
            "-c",
            f"CREATE DATABASE {test_db_name};",
        ],
        check=True,
    )
    log(f"   Created '{test_db_name}' database.", GREEN)

    port_res = subprocess.run(
        [*compose_cmd, "port", "postgres", "5432"], capture_output=True, text=True
    )
    host_port = "5432"
    if port_res.stdout.strip():
        host_port = port_res.stdout.strip().split(":")[-1]

    test_db_url = (
        f"postgresql+asyncpg://postgres:postgres@localhost:{host_port}/{test_db_name}"
    )

    log(f"   Running migrations on {test_db_url}...", YELLOW)
    env = os.environ.copy()
    env["DATABASE_URL"] = test_db_url
    env["TEST_NAMESPACE"] = namespace

    try:
        subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head"],
            cwd=BACKEND_DIR,
            env=env,
            check=True,
            capture_output=True,
        )
        log("   Migrations applied.", GREEN)
    except subprocess.CalledProcessError as e:
        log(f"❌ Migration failed:\n{e.stderr.decode()}", RED)
        unregister_namespace(namespace)
        raise

    try:
        yield (test_db_url, namespace)
    finally:
        cleanup_worker_databases(runtime, container_name, namespace)

        log("🧹 Tearing down infrastructure...", YELLOW)
        subprocess.run(
            [*compose_cmd, "--profile", "infra", "stop"], stderr=subprocess.DEVNULL
        )
        log("   Database stopped.", GREEN)

        # Unregister namespace after successful cleanup
        unregister_namespace(namespace)


def main():
    # Capture CLI args for pytest
    pytest_args = sys.argv[1:]

    # Handle Signals
    def signal_handler(sig, frame):
        log("\n🛑 Interrupt received, shutting down...", RED)
        sys.exit(
            1
        )  # Triggers finally blocks in context managers if we were inside one?
        # No, sys.exit raises SystemExit.

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        with test_database() as (db_url, namespace):
            log("🚀 Starting Tests...", GREEN)

            env = os.environ.copy()
            env["DATABASE_URL"] = db_url
            env["TEST_NAMESPACE"] = namespace
            env["S3_ACCESS_KEY"] = "minio"
            env["S3_SECRET_KEY"] = "minio_local_secret"
            env["S3_ENDPOINT"] = "http://localhost:9000"
            env["S3_BUCKET"] = get_s3_bucket(namespace)

            # Run Pytest (via uv)
            # We call the 'moon' defined test command, OR directly pytest?
            # Calling 'moon' recursively might be weird if this script is CALLED by moon.
            # So we call 'uv run pytest' directly.

            cmd = [
                "uv",
                "run",
                "pytest",
                "-v",
            ] + pytest_args

            log(f"   Command: {' '.join(cmd)}", YELLOW)
            result = subprocess.run(cmd, cwd=BACKEND_DIR, env=env)

            if result.returncode != 0:
                log("❌ Tests Failed.", RED)
                sys.exit(result.returncode)

            log("✅ Tests Passed.", GREEN)

    except Exception as e:
        log(f"❌ Error: {e}", RED)
        sys.exit(1)


if __name__ == "__main__":
    main()
