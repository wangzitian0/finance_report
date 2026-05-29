#!/usr/bin/env python3
"""
Backend test lifecycle implementation.

A robust, Python-based test runner that manages the entire lifecycle
of the backend test environment.

Key Features:
- Manages Docker container lifecycle (Postgres) using context managers.
- Ensures cleanup on both success, failure, and interrupts (Ctrl+C).
- Integrates with 'moon' and 'pytest'.
- Tracks active namespaces for orphaned resource cleanup.
- Supports --fast (no coverage) and --smart (changed files only) modes.

Usage:
    python tools/test_lifecycle.py [--fast|--smart|--ephemeral] [pytest_args]
"""

import os
import signal
import subprocess
import sys
import time
import tomllib
from contextlib import contextmanager
from pathlib import Path

# Constants
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from common import test_isolation  # noqa: E402

COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
BACKEND_DIR = REPO_ROOT / "apps" / "backend"
DB_CONTAINER_PREFIX = "finance-report-db"
CACHE_DIR = test_isolation.CACHE_DIR
ACTIVE_NAMESPACES_FILE = test_isolation.ACTIVE_NAMESPACES_FILE
MAX_POSTGRES_IDENTIFIER_LENGTH = test_isolation.MAX_POSTGRES_IDENTIFIER_LENGTH
TEST_DB_PREFIX = test_isolation.TEST_DB_PREFIX
MAX_NAMESPACE_LENGTH = test_isolation.MAX_NAMESPACE_LENGTH
MAX_S3_BUCKET_LENGTH = test_isolation.MAX_S3_BUCKET_LENGTH

# ANSI Colors
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"


def get_runtime_version(name: str) -> str:
    """Read a runtime version from the repository toolchain contract."""
    with (REPO_ROOT / "toolchain.toml").open("rb") as fh:
        toolchain = tomllib.load(fh)
    return str(toolchain["runtime"][name])


def uv_run(*args: str) -> list[str]:
    """Build a uv run command pinned to the SSOT Python runtime."""
    return ["uv", "run", "--python", get_runtime_version("python"), *args]


# === Isolation Utilities ===


def get_namespace() -> str:
    """Generate unique namespace for test isolation based on branch/repo."""
    return test_isolation.get_namespace(run=subprocess.run, cwd_getter=Path.cwd)


def _sanitize_namespace(name: str) -> str:
    """Convert branch name to safe identifier."""
    return test_isolation.sanitize_namespace(name)


def _shorten_identifier(value: str, max_length: int, separator: str = "_") -> str:
    """Shorten a stable identifier and preserve uniqueness with a hash suffix."""
    return test_isolation.shorten_identifier(value, max_length, separator)


def get_test_db_name(namespace: str) -> str:
    """Generate test database name from namespace."""
    return test_isolation.get_test_db_name(namespace)


def get_s3_bucket(namespace: str, base_bucket: str = "statements") -> str:
    """Generate S3 bucket name from namespace."""
    return test_isolation.get_s3_bucket(namespace, base_bucket)


# === Logging ===


def log(msg, color=RESET):
    print(f"{color}{msg}{RESET}")


def load_active_namespaces():
    """Load list of active namespaces from persistent storage."""
    return test_isolation.load_active_namespaces(ACTIVE_NAMESPACES_FILE, CACHE_DIR)


def save_active_namespaces(namespaces):
    """Save list of active namespaces to persistent storage."""
    try:
        test_isolation.save_active_namespaces(
            namespaces, ACTIVE_NAMESPACES_FILE, CACHE_DIR
        )
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


def cleanup_orphan_databases(runtime, container_name):
    """Clean up databases from orphaned namespaces (previous crashed/interrupted runs).

    This runs BEFORE each test session to prevent database accumulation.
    It finds all finance_report_test_* databases and compares against active namespaces.
    """
    log("🧹 Checking for orphaned test databases...", YELLOW)

    # Get all test databases
    list_cmd = [
        runtime,
        "exec",
        container_name,
        "psql",
        "-U",
        "postgres",
        "-t",
        "-c",
        "SELECT datname FROM pg_database WHERE datname LIKE 'finance_report_test%'",
    ]

    try:
        result = subprocess.run(list_cmd, capture_output=True, text=True, check=True)
        all_dbs = [db.strip() for db in result.stdout.strip().split("\n") if db.strip()]

        if not all_dbs:
            log("   No test databases found.", YELLOW)
            return

        # Get active namespaces
        active_namespaces = load_active_namespaces()
        current_namespace = get_namespace()

        # Keep databases that belong to current or active namespaces
        # Database naming: finance_report_test_{namespace} or finance_report_test_{namespace}_gwX
        import re

        db_pattern = re.compile(r"^finance_report_test_([^_]+(?:_[^_]+)*?)(?:_gw\d+)?$")

        orphan_dbs = []
        for db in all_dbs:
            match = db_pattern.match(db)
            if match:
                db_namespace = match.group(1)
                # Keep if it's the current namespace or in active list
                if (
                    db_namespace != current_namespace
                    and db_namespace not in active_namespaces
                ):
                    orphan_dbs.append(db)
            elif db == "finance_report_test":
                # Legacy database without namespace, safe to drop
                orphan_dbs.append(db)

        if not orphan_dbs:
            log("   No orphaned databases found.", YELLOW)
            return

        log(f"   Found {len(orphan_dbs)} orphaned database(s), cleaning...", YELLOW)
        for db_name in orphan_dbs:
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
                    f'DROP DATABASE IF EXISTS "{db_name}";',
                ],
                capture_output=True,
            )

        log(f"   Cleaned {len(orphan_dbs)} orphaned database(s).", GREEN)

        # Also clear stale namespaces from the file
        stale_namespaces = [ns for ns in active_namespaces if ns != current_namespace]
        if stale_namespaces:
            save_active_namespaces(
                [current_namespace] if current_namespace in active_namespaces else []
            )
            log(
                f"   Cleared {len(stale_namespaces)} stale namespace(s) from tracking.",
                YELLOW,
            )

    except subprocess.CalledProcessError as e:
        log(f"   Warning: Failed to check orphaned databases: {e}", YELLOW)


def get_container_runtime():
    """Detect podman or docker."""
    requested = os.environ.get("CONTAINER_RUNTIME", "").strip().lower()
    if requested:
        if requested not in {"podman", "docker"}:
            log("❌ CONTAINER_RUNTIME must be either 'podman' or 'docker'.", RED)
            return None
        if subprocess.run(["which", requested], capture_output=True).returncode == 0:
            return requested
        log(f"❌ CONTAINER_RUNTIME={requested} not found in PATH.", RED)
        return None

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
def test_database(ephemeral=False):
    """Context manager to spin up and tear down the test database with namespace isolation.
    If ephemeral is True, the entire infrastructure stack (containers, networks, volumes)
    will be destroyed after the test run.
    """
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

    # Use unique project name and ENV_SUFFIX for full isolation
    # This ensures container_name: finance-report-db${ENV_SUFFIX} is unique
    env_suffix = f"-{namespace}"
    project_name = f"finance-report-{namespace}"

    # Inject ENV_SUFFIX into environment for subprocess
    env = os.environ.copy()
    env["ENV_SUFFIX"] = env_suffix

    compose_cmd = [runtime, "compose", "-p", project_name, "-f", str(COMPOSE_FILE)]

    log(
        f"🐘 Ensuring infrastructure is up (Project: {project_name}, Suffix: {env_suffix})...",
        YELLOW,
    )
    try:
        # Start infrastructure services if not running
        # Use --profile infra to only start infra services if needed
        subprocess.run(
            [*compose_cmd, "--profile", "infra", "up", "-d"], env=env, check=True
        )

        # Wait for postgres to be ready
        container_name = f"finance-report-db{env_suffix}"
    except subprocess.CalledProcessError:
        log("❌ Failed to start database.", RED)
        unregister_namespace(namespace)
        raise

    try:
        res = subprocess.run(
            [*compose_cmd, "ps", "--format", "{{.Name}}", "postgres"],
            capture_output=True,
            text=True,
            env=env,
        )
        container_name = res.stdout.strip()
        if not container_name:
            # Fallback if format not supported or empty
            # Use suffixed name to maintain isolation
            container_name = f"finance-report-db{env_suffix}"
    except Exception:
        container_name = f"finance-report-db{env_suffix}"

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

    # Clean up orphaned databases from previous crashed/interrupted runs
    cleanup_orphan_databases(runtime, container_name)

    log("🛠  Setting up test database...", YELLOW)
    # Always try to drop with FORCE to handle active connections from previous interrupted runs
    drop_res = subprocess.run(
        [
            runtime,
            "exec",
            container_name,
            "psql",
            "-U",
            "postgres",
            "-c",
            f'DROP DATABASE IF EXISTS "{test_db_name}" WITH (FORCE);',
        ],
        capture_output=True,
        text=True,
    )
    if drop_res.returncode != 0:
        log(
            f"   Warning: DROP DATABASE failed (might be expected if DB doesn't exist): {drop_res.stderr.strip()}",
            YELLOW,
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
            f'CREATE DATABASE "{test_db_name}";',
        ],
        check=True,
        capture_output=True,
        text=True,
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
    env["DATABASE_URL"] = test_db_url
    env["TEST_NAMESPACE"] = namespace

    try:
        subprocess.run(
            uv_run("python", "-m", "alembic", "upgrade", "head"),
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
        # Clean up worker databases (pytest-xdist)
        cleanup_worker_databases(runtime, container_name, namespace)

        # Drop the main test database we created
        log(f"🧹 Dropping test database: {test_db_name}...", YELLOW)
        try:
            subprocess.run(
                [
                    runtime,
                    "exec",
                    container_name,
                    "psql",
                    "-U",
                    "postgres",
                    "-c",
                    f'DROP DATABASE IF EXISTS "{test_db_name}";',
                ],
                capture_output=True,
                check=True,
            )
            log(f"   Dropped {test_db_name}.", GREEN)
        except subprocess.CalledProcessError as e:
            log(f"   Warning: Failed to drop test database: {e}", YELLOW)

        # Stop and remove infrastructure if ephemeral mode is on
        if ephemeral:
            log(
                f"🌬️  Ephemeral mode: Tearing down infrastructure ({project_name})...",
                YELLOW,
            )
            try:
                subprocess.run([*compose_cmd, "down", "-v"], env=env, check=True)
                log(f"   ✅ Resources released for {project_name}.", GREEN)

                # Explicit pod cleanup if using podman
                if runtime == "podman":
                    pod_name = f"pod_{project_name}"
                    log(f"📦 Checking for lingering pod: {pod_name}...", YELLOW)
                    subprocess.run(
                        ["podman", "pod", "rm", "-f", pod_name], capture_output=True
                    )
            except subprocess.CalledProcessError as e:
                log(f"   Warning: Failed to teardown infrastructure: {e}", YELLOW)
        else:
            log(
                f"📌 Persistent mode: Keeping infrastructure running ({project_name}).",
                YELLOW,
            )

        # Unregister namespace after successful cleanup
        unregister_namespace(namespace)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Run backend tests with DB lifecycle management"
    )
    parser.add_argument(
        "--fast", action="store_true", help="Fast mode: no coverage, -n 4"
    )
    parser.add_argument(
        "--smart",
        action="store_true",
        help="Smart mode: coverage on changed files only",
    )
    parser.add_argument(
        "--ephemeral",
        action="store_true",
        help="Ephemeral mode: destroy all infrastructure after run",
    )
    # Use parse_known_args for transparent pytest flag pass-through (-k, -m, etc.)
    args, extra_pytest_args = parser.parse_known_args()

    # Handle Signals
    def signal_handler(sig, frame):
        log("\n🛑 Interrupt received, shutting down...", RED)
        sys.exit(1)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Build pytest args based on mode
    pytest_args = []

    if args.fast:
        log("🚀 Fast Mode: No coverage, -n 4", GREEN)
        pytest_args = [
            "-n",
            "4",
            "-m",
            "not slow and not e2e",
            "--dist",
            "worksteal",
            "--tb=short",
            "--no-cov",  # Override pyproject.toml addopts
        ]
    elif args.smart:
        log("🧪 Smart Mode: Coverage on changed files only", GREEN)
        changed_modules = _get_changed_files()
        pytest_args = [
            "-n",
            "4",
            "-m",
            "not slow and not e2e",
            "--dist",
            "worksteal",
            "--no-cov",  # Override pyproject.toml addopts first
        ]
        if changed_modules:
            log(f"   Changed modules: {len(changed_modules)}", YELLOW)
            for module in changed_modules[:5]:
                log(f"   • {module}", YELLOW)
            if len(changed_modules) > 5:
                log(f"   • ... and {len(changed_modules) - 5} more", YELLOW)
            for module in changed_modules:
                pytest_args.append(f"--cov={module}")
            pytest_args.extend(
                [
                    "--cov-report=term-missing",
                    "--cov-branch",
                    "--cov-fail-under=99",
                ]
            )
        else:
            log("   No changes detected, running full coverage", YELLOW)
            pytest_args.extend(
                [
                    "--cov=src",
                    "--cov-report=term-missing",
                    "--cov-branch",
                    "--cov-fail-under=94",
                ]
            )
    else:
        # Default mode: use pyproject.toml addopts (includes coverage)
        pass

    # Add any extra pytest args from CLI
    pytest_args.extend(extra_pytest_args)

    try:
        with test_database(ephemeral=args.ephemeral) as (db_url, namespace):
            log("🚀 Starting Tests...", GREEN)

            env = os.environ.copy()
            env["DATABASE_URL"] = db_url
            env["TEST_NAMESPACE"] = namespace
            env["S3_ACCESS_KEY"] = "minio"
            env["S3_SECRET_KEY"] = "minio_local_secret"
            env["S3_ENDPOINT"] = "http://localhost:9000"
            env["S3_BUCKET"] = get_s3_bucket(namespace)

            cmd = uv_run("python", "-m", "pytest", "-v") + pytest_args

            log(f"   Command: {' '.join(cmd)}", YELLOW)
            result = subprocess.run(cmd, cwd=BACKEND_DIR, env=env)

            if result.returncode != 0:
                log("❌ Tests Failed.", RED)
                sys.exit(result.returncode)

            log("✅ Tests Passed.", GREEN)

    except Exception as e:
        log(f"❌ Error: {e}", RED)
        sys.exit(1)


def _get_changed_files(base_branch: str = "main") -> list[str]:
    """Get changed Python modules for smart coverage."""
    try:
        files_set: set[str] = set()
        diff_commands = [
            ["git", "diff", "--name-status", f"{base_branch}...HEAD"],
            ["git", "diff", "--name-status", "HEAD"],
            ["git", "diff", "--name-status", "--cached"],
        ]

        for cmd in diff_commands:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split(maxsplit=1)
                if len(parts) == 2 and parts[0] != "D":
                    files_set.add(parts[1])

        modules = []
        for filepath in sorted(files_set):
            if filepath.startswith("apps/backend/src/") and filepath.endswith(".py"):
                file_path = REPO_ROOT / filepath
                if file_path.exists():
                    rel_path = filepath.replace("apps/backend/", "").replace(".py", "")
                    modules.append(rel_path.replace("/", "."))

        return modules
    except subprocess.CalledProcessError:
        return []


if __name__ == "__main__":
    main()
