#!/usr/bin/env python3
"""Backend test lifecycle runner with container and database namespace isolation."""

import argparse
import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from common.runtime.dev.toolchain import (  # noqa: E402,F401
    get_container_runtime,
    get_runtime_version,
    uv_run,
)
from common.testing import test_isolation  # noqa: E402

COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
BACKEND_DIR = REPO_ROOT / "apps" / "backend"
DB_CONTAINER_PREFIX = "finance-report-db"
CACHE_DIR = test_isolation.CACHE_DIR
ACTIVE_NAMESPACES_FILE = test_isolation.ACTIVE_NAMESPACES_FILE
MAX_POSTGRES_IDENTIFIER_LENGTH = test_isolation.MAX_POSTGRES_IDENTIFIER_LENGTH
TEST_DB_PREFIX = test_isolation.TEST_DB_PREFIX
MAX_NAMESPACE_LENGTH = test_isolation.MAX_NAMESPACE_LENGTH
MAX_S3_BUCKET_LENGTH = test_isolation.MAX_S3_BUCKET_LENGTH

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"

_ORPHAN_DB_RE = re.compile(r"^finance_report_test_([^_]+(?:_[^_]+)*?)(?:_gw\d+)?$")
_WORKER_DB_RE = re.compile(r"^finance_report_test_[\w]+(_gw\d+)?$")


def get_namespace() -> str:
    return test_isolation.get_namespace(run=subprocess.run, cwd_getter=Path.cwd)


def _sanitize_namespace(name: str) -> str:
    return test_isolation.sanitize_namespace(name)


def _shorten_identifier(value: str, max_length: int, separator: str = "_") -> str:
    return test_isolation.shorten_identifier(value, max_length, separator)


def get_test_db_name(namespace: str) -> str:
    return test_isolation.get_test_db_name(namespace)


def get_s3_bucket(namespace: str, base_bucket: str = "statements") -> str:
    return test_isolation.get_s3_bucket(namespace, base_bucket)


def log(msg, color=RESET):
    print(f"{color}{msg}{RESET}")


def load_active_namespaces():
    return test_isolation.load_active_namespaces(ACTIVE_NAMESPACES_FILE, CACHE_DIR)


def save_active_namespaces(namespaces):
    try:
        test_isolation.save_active_namespaces(
            namespaces, ACTIVE_NAMESPACES_FILE, CACHE_DIR
        )
    except OSError as exc:
        log(f"⚠️  Warning: Failed to save active namespaces: {exc}", YELLOW)


def register_namespace(namespace):
    namespaces = load_active_namespaces()
    if namespace not in namespaces:
        namespaces.append(namespace)
        save_active_namespaces(namespaces)
        log(f"   Registered namespace: {namespace}", YELLOW)


def unregister_namespace(namespace):
    namespaces = load_active_namespaces()
    if namespace in namespaces:
        namespaces.remove(namespace)
        save_active_namespaces(namespaces)
        log(f"   Unregistered namespace: {namespace}", YELLOW)


def _psql_cmd(
    runtime: str, container_name: str, sql: str, *, tuples_only: bool = False
) -> list[str]:
    return [
        runtime,
        "exec",
        container_name,
        "psql",
        "-U",
        "postgres",
        *(["-t"] if tuples_only else []),
        "-c",
        sql,
    ]


def cleanup_orphan_databases(runtime, container_name):
    """Drop test databases belonging to inactive/crashed namespaces."""
    log("🧹 Checking for orphaned test databases...", YELLOW)
    list_cmd = _psql_cmd(
        runtime,
        container_name,
        "SELECT datname FROM pg_database WHERE datname LIKE 'finance_report_test%'",
        tuples_only=True,
    )
    try:
        result = subprocess.run(list_cmd, capture_output=True, text=True, check=True)
        all_dbs = [db.strip() for db in result.stdout.strip().split("\n") if db.strip()]
        if not all_dbs:
            log("   No test databases found.", YELLOW)
            return

        active_namespaces = load_active_namespaces()
        current_namespace = get_namespace()
        orphan_dbs: list[str] = []
        for db in all_dbs:
            match = _ORPHAN_DB_RE.match(db)
            if match:
                db_ns = match.group(1)
                if db_ns != current_namespace and db_ns not in active_namespaces:
                    orphan_dbs.append(db)
            elif db == "finance_report_test":
                orphan_dbs.append(db)

        if not orphan_dbs:
            log("   No orphaned databases found.", YELLOW)
            return

        log(f"   Found {len(orphan_dbs)} orphaned database(s), cleaning...", YELLOW)
        for db_name in orphan_dbs:
            log(f"   Dropping {db_name}...", YELLOW)
            subprocess.run(
                _psql_cmd(
                    runtime, container_name, f'DROP DATABASE IF EXISTS "{db_name}";'
                ),
                capture_output=True,
            )
        log(f"   Cleaned {len(orphan_dbs)} orphaned database(s).", GREEN)

        stale = [ns for ns in active_namespaces if ns != current_namespace]
        if stale:
            save_active_namespaces(
                [current_namespace] if current_namespace in active_namespaces else []
            )
            log(f"   Cleared {len(stale)} stale namespace(s) from tracking.", YELLOW)
    except subprocess.CalledProcessError as exc:
        log(f"   Warning: Failed to check orphaned databases: {exc}", YELLOW)


def is_db_ready(runtime, container_name):
    try:
        subprocess.run(
            [runtime, "exec", container_name, "pg_isready", "-U", "postgres"],
            check=True,
            capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def _extract_host_port(port_output):
    for raw_line in port_output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "->" in line:
            line = line.rsplit("->", 1)[1].strip()
        host_port = line.rsplit(":", 1)[-1].strip()
        if host_port.isdigit():
            return host_port
    return None


def resolve_postgres_host_port(runtime, compose_cmd, env, container_name):
    port_res = subprocess.run(
        [*compose_cmd, "port", "postgres", "5432"],
        capture_output=True,
        text=True,
        env=env,
    )
    if host_port := _extract_host_port(port_res.stdout):
        return host_port
    runtime_port_res = subprocess.run(
        [runtime, "port", container_name, "5432/tcp"],
        capture_output=True,
        text=True,
    )
    return _extract_host_port(runtime_port_res.stdout) or "5432"


def cleanup_worker_databases(runtime, container_name, namespace):
    """Drop pytest-xdist worker databases after a test run."""
    log("🧹 Cleaning up worker databases...", YELLOW)
    if not namespace.replace("_", "").replace("-", "").isalnum():
        log(f"   WARNING: Invalid namespace '{namespace}', skipping cleanup", YELLOW)
        return

    try:
        container_check = subprocess.run(
            [runtime, "ps", "-q", "-f", f"name={container_name}"],
            capture_output=True,
            check=True,
        )
        if not container_check.stdout.strip():
            log(
                f"   Container '{container_name}' not running, skipping cleanup", YELLOW
            )
            return
    except subprocess.CalledProcessError:
        log(f"   Cannot verify container '{container_name}', skipping cleanup", YELLOW)
        return

    list_cmd = _psql_cmd(
        runtime,
        container_name,
        f"SELECT datname FROM pg_database WHERE datname LIKE 'finance_report_test_{namespace}_gw%'",
        tuples_only=True,
    )
    try:
        result = subprocess.run(list_cmd, capture_output=True, text=True, check=True)
        databases = [
            db.strip() for db in result.stdout.strip().split("\n") if db.strip()
        ]
        if not databases:
            log("   No worker databases to clean.", YELLOW)
            return

        for db_name in databases:
            if not _WORKER_DB_RE.match(db_name):
                log(f"   Skipping invalid database name: {db_name}", YELLOW)
                continue
            log(f"   Dropping {db_name}...", YELLOW)
            subprocess.run(
                _psql_cmd(
                    runtime, container_name, f"DROP DATABASE IF EXISTS {db_name};"
                ),
                capture_output=True,
            )
        log(f"   Cleaned {len(databases)} worker database(s).", GREEN)
    except subprocess.CalledProcessError as exc:
        log(f"   Warning: Failed to clean worker databases: {exc}", YELLOW)


@contextmanager
def test_database(ephemeral=False):
    """Provision an isolated test database and tear it down on exit."""
    runtime = get_container_runtime()
    if not runtime:
        log("❌ No container runtime (docker/podman) found.", RED)
        sys.exit(1)

    namespace = get_namespace()
    test_db_name = get_test_db_name(namespace)
    log(f"🔧 Test namespace: {namespace}", YELLOW)
    log(f"🔧 Test database: {test_db_name}", YELLOW)
    register_namespace(namespace)

    env_suffix = f"-{namespace}"
    project_name = f"finance-report-{namespace}"
    env = os.environ.copy()
    env["ENV_SUFFIX"] = env_suffix
    env.setdefault("DB_PORTS", "127.0.0.1::5432")
    env.setdefault("MINIO_API_PORTS", "127.0.0.1::9000")
    env.setdefault("MINIO_CONSOLE_PORTS", "127.0.0.1::9001")
    env.setdefault("RESTART_POLICY", "no")

    compose_cmd = [runtime, "compose", "-p", project_name, "-f", str(COMPOSE_FILE)]
    log(
        f"🐘 Ensuring infrastructure is up (Project: {project_name}, Suffix: {env_suffix})...",
        YELLOW,
    )
    try:
        subprocess.run(
            [*compose_cmd, "--profile", "infra", "up", "-d"], env=env, check=True
        )
    except subprocess.CalledProcessError:
        log("❌ Failed to start database.", RED)
        unregister_namespace(namespace)
        raise

    container_name = f"finance-report-db{env_suffix}"
    try:
        res = subprocess.run(
            [*compose_cmd, "ps", "--format", "{{.Name}}", "postgres"],
            capture_output=True,
            text=True,
            env=env,
        )
        container_name = res.stdout.strip() or container_name
    except Exception:
        pass
    log(f"   Container: {container_name}", YELLOW)

    log("⏳ Waiting for Postgres...", YELLOW)
    if not any(
        is_db_ready(runtime, container_name) or time.sleep(1) for _ in range(30)
    ):
        log("❌ Database failed to become ready.", RED)
        unregister_namespace(namespace)
        raise Exception("Database not ready")

    cleanup_orphan_databases(runtime, container_name)
    log("🛠  Setting up test database...", YELLOW)
    drop_res = subprocess.run(
        _psql_cmd(
            runtime,
            container_name,
            f'DROP DATABASE IF EXISTS "{test_db_name}" WITH (FORCE);',
        ),
        capture_output=True,
        text=True,
    )
    if drop_res.returncode != 0:
        log(f"   Warning: DROP DATABASE failed: {drop_res.stderr.strip()}", YELLOW)

    subprocess.run(
        _psql_cmd(runtime, container_name, f'CREATE DATABASE "{test_db_name}";'),
        check=True,
        capture_output=True,
        text=True,
    )
    log(f"   Created '{test_db_name}' database.", GREEN)

    host_port = resolve_postgres_host_port(runtime, compose_cmd, env, container_name)
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
    except subprocess.CalledProcessError as exc:
        log(f"❌ Migration failed:\n{exc.stderr.decode()}", RED)
        unregister_namespace(namespace)
        raise

    try:
        yield (test_db_url, namespace)
    finally:
        cleanup_worker_databases(runtime, container_name, namespace)
        log(f"🧹 Dropping test database: {test_db_name}...", YELLOW)
        try:
            subprocess.run(
                _psql_cmd(
                    runtime,
                    container_name,
                    f'DROP DATABASE IF EXISTS "{test_db_name}";',
                ),
                capture_output=True,
                check=True,
            )
            log(f"   Dropped {test_db_name}.", GREEN)
        except subprocess.CalledProcessError as exc:
            log(f"   Warning: Failed to drop test database: {exc}", YELLOW)

        if ephemeral:
            log(
                f"🌬️  Ephemeral mode: Tearing down infrastructure ({project_name})...",
                YELLOW,
            )
            try:
                subprocess.run([*compose_cmd, "down", "-v"], env=env, check=True)
                log(f"   ✅ Resources released for {project_name}.", GREEN)
                if runtime == "podman":
                    pod_name = f"pod_{project_name}"
                    subprocess.run(
                        ["podman", "pod", "rm", "-f", pod_name], capture_output=True
                    )
            except subprocess.CalledProcessError as exc:
                log(f"   Warning: Failed to teardown infrastructure: {exc}", YELLOW)
        else:
            log(
                f"📌 Persistent mode: Keeping infrastructure running ({project_name}).",
                YELLOW,
            )
        unregister_namespace(namespace)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run backend tests with DB lifecycle management"
    )
    parser.add_argument(
        "--fast", action="store_true", help="Fast mode: no coverage, -n 4"
    )
    parser.add_argument(
        "--smart", action="store_true", help="Smart mode: changed files coverage"
    )
    parser.add_argument(
        "--ephemeral", action="store_true", help="Destroy stack after run"
    )
    args, extra_pytest_args = (
        parser.parse_known_args() if argv is None else parser.parse_known_args(argv)
    )

    def signal_handler(sig, frame):
        log("\n🛑 Interrupt received, shutting down...", RED)
        sys.exit(1)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    base_parallel = ["-n", "4", "-m", "not slow and not e2e", "--dist", "worksteal"]
    pytest_args: list[str] = []
    if args.fast:
        log("🚀 Fast Mode: No coverage, -n 4", GREEN)
        pytest_args = [*base_parallel, "--tb=short", "--no-cov"]
    elif args.smart:
        log("🧪 Smart Mode: Coverage on changed files only", GREEN)
        changed_modules = _get_changed_files()
        pytest_args = [*base_parallel, "--no-cov"]
        if changed_modules:
            log(f"   Changed modules: {len(changed_modules)}", YELLOW)
            for module in changed_modules[:5]:
                log(f"   • {module}", YELLOW)
            if len(changed_modules) > 5:
                log(f"   • ... and {len(changed_modules) - 5} more", YELLOW)
            pytest_args.extend(f"--cov={m}" for m in changed_modules)
            pytest_args.extend(
                ["--cov-report=term-missing", "--cov-branch", "--cov-fail-under=99"]
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
    pytest_args.extend(extra_pytest_args)

    try:
        with test_database(ephemeral=args.ephemeral) as (db_url, namespace):
            log("🚀 Starting Tests...", GREEN)
            env = {
                **os.environ,
                "DATABASE_URL": db_url,
                "TEST_NAMESPACE": namespace,
                "S3_ACCESS_KEY": "minio",
                "S3_SECRET_KEY": "minio_local_secret",
                "S3_ENDPOINT": "http://localhost:9000",
                "S3_BUCKET": get_s3_bucket(namespace),
            }
            cmd = uv_run("python", "-m", "pytest", "-v") + pytest_args
            log(f"   Command: {' '.join(cmd)}", YELLOW)
            result = subprocess.run(cmd, cwd=BACKEND_DIR, env=env)
            if result.returncode != 0:
                log("❌ Tests Failed.", RED)
                return result.returncode
            log("✅ Tests Passed.", GREEN)
    except Exception as exc:
        log(f"❌ Error: {exc}", RED)
        return 1
    return 0


def _get_changed_files(base_branch: str = "main") -> list[str]:
    """Return dotted Python module paths for modified backend source files."""
    try:
        files_set: set[str] = set()
        for diff_target in (f"{base_branch}...HEAD", "HEAD", "--cached"):
            result = subprocess.run(
                ["git", "diff", "--name-status", diff_target],
                capture_output=True,
                text=True,
                check=True,
            )
            for line in result.stdout.strip().split("\n"):
                parts = line.strip().split(maxsplit=1)
                if len(parts) == 2 and parts[0] != "D":
                    files_set.add(parts[1])
        return [
            filepath.removeprefix("apps/backend/").removesuffix(".py").replace("/", ".")
            for filepath in sorted(files_set)
            if filepath.startswith("apps/backend/src/")
            and filepath.endswith(".py")
            and (REPO_ROOT / filepath).exists()
        ]
    except subprocess.CalledProcessError:
        return []


if __name__ == "__main__":
    raise SystemExit(main())
