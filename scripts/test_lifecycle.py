#!/usr/bin/env python3
"""
scripts/test_lifecycle.py

A robust, Python-based test runner that manages the entire lifecycle
of the backend test environment, replacing fragile shell scripts.

Key Features:
- Manages Docker container lifecycle (Postgres) using context managers.
- Ensures cleanup on both success, failure, and interrupts (Ctrl+C).
- Integrates with 'moon' and 'pytest'.

Usage:
    python scripts/test_lifecycle.py [pytest_args]
"""

import os
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

# Constants
REPO_ROOT = Path(__file__).parent.parent.absolute()
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
BACKEND_DIR = REPO_ROOT / "apps" / "backend"
DB_CONTAINER_PREFIX = "finance-report-db"

# ANSI Colors
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"

def log(msg, color=RESET):
    print(f"{color}{msg}{RESET}")

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
            check=True, capture_output=True
        )
        return True
    except subprocess.CalledProcessError:
        return False

@contextmanager
def test_database():
    """Context manager to spin up and tear down the test database."""
    runtime = get_container_runtime()
    if not runtime:
        log("❌ No container runtime (docker/podman) found.", RED)
        sys.exit(1)

    # Use a unique suffix for CI/Test isolation if needed, or default to standard
    # For local testing, we might want to reuse 'finance-report-db' or use a test-specific one.
    # To match 'test_backend.sh' behavior (which tried to reuse), let's keep it simple first:
    # We will start the standard dev environment DB if not running, or use a dedicated test one?
    # The original script used a complex locking mechanism to share the DB.
    # To Simplify: Let's use the standard docker-compose service 'postgres'.
    
    # Check if already running
    # We use 'docker compose' to manage the service 'postgres'
    compose_cmd = [runtime, "compose", "-f", str(COMPOSE_FILE)]
    
    log("🐘 Ensuring database is up...", YELLOW)
    try:
        subprocess.run([*compose_cmd, "up", "-d", "postgres"], check=True)
    except subprocess.CalledProcessError:
        log("❌ Failed to start database.", RED)
        raise

    # Find the actual container name (in case of compose project name variations)
    # We look for the one defined in docker-compose.yml or generated
    # Simple approach: ask compose for the container name
    try:
        res = subprocess.run([*compose_cmd, "ps", "--format", "{{.Name}}", "postgres"], capture_output=True, text=True)
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
        # We don't tear down here if it was already running?
        # Actually, if we just started it, maybe we should.
        # But for 'dev' usage, maybe not.
        raise Exception("Database not ready")

    # Create Test Database if it doesn't exist
    log("🛠  Setting up test database...", YELLOW)
    create_db_cmd = [
        runtime, "exec", container_name, 
        "psql", "-U", "postgres", 
        "-tc", "SELECT 1 FROM pg_database WHERE datname='finance_report_test'"
    ]
    res = subprocess.run(create_db_cmd, capture_output=True, text=True)
    if "1" not in res.stdout:
        subprocess.run([
            runtime, "exec", container_name,
            "psql", "-U", "postgres", "-c", "CREATE DATABASE finance_report_test;"
        ], check=True)
        log("   Created 'finance_report_test' database.", GREEN)
    else:
        log("   'finance_report_test' database exists.", GREEN)
    
    # Run Migrations on Test DB
    # We need to run alembic against the TEST database.
    # We can use 'uv run alembic' from backend dir.
    # But we need to override DATABASE_URL.
    
    # Determine the port
    # 'docker compose port' can tell us the host port
    port_res = subprocess.run([*compose_cmd, "port", "postgres", "5432"], capture_output=True, text=True)
    host_port = "5432"
    if port_res.stdout.strip():
        # output is like "0.0.0.0:5432"
        host_port = port_res.stdout.strip().split(":")[-1]
    
    # On macOS/Seatbelt/Podman, sometimes localhost mapping is tricky, but let's assume standard behavior first.
    test_db_url = f"postgresql+asyncpg://postgres:postgres@localhost:{host_port}/finance_report_test"
    
    log(f"   Running migrations on {test_db_url}...", YELLOW)
    env = os.environ.copy()
    env["DATABASE_URL"] = test_db_url
    
    try:
        subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head"],
            cwd=BACKEND_DIR,
            env=env,
            check=True,
            capture_output=True 
        )
        log("   Migrations applied.", GREEN)
    except subprocess.CalledProcessError as e:
        log(f"❌ Migration failed:\n{e.stderr.decode()}", RED)
        raise

    try:
        yield test_db_url
    finally:
        # Cleanup Logic
        # For 'test', we might WANT to shut down the DB if we started it.
        # But if it's 'dev' and we are just running tests alongside, we might want to keep it.
        # User said: "Local CI, runs and releases".
        # So we should probably shut it down if we are in "CI mode".
        # But for local dev iteration, keeping it up is faster.
        # Let's verify if user passed a flag or if we just leave it up.
        # The Shell script had complex logic for "managed" vs "started_existing".
        # Let's simplify: If we are in CI (env var) or explicit flag, we down.
        # Otherwise, we leave it running for faster subsequent tests?
        # NO, user explicitly complained about "resource leaks".
        # So default behavior should probably be CLEANUP for a test runner.
        # Unless we implement the "shared" logic again.
        
        # Let's try to be safe: Stop what we started?
        # Docker Compose is idempotent.
        # If we run 'down', it kills everything.
        
        # Let's assume for this "Test Runner", we want isolation.
        # So we should probably tear down.
        log("🧹 Tearing down database...", YELLOW)
        subprocess.run([*compose_cmd, "stop", "postgres"], stderr=subprocess.DEVNULL)
        # We don't remove volumes to preserve cache/speed? Or remove?
        # For CI, we might want fresh.
        # Let's just 'stop' for now to release ports/resources.
        log("   Database stopped.", GREEN)

def main():
    # Capture CLI args for pytest
    pytest_args = sys.argv[1:]
    
    # Handle Signals
    def signal_handler(sig, frame):
        log("\n🛑 Interrupt received, shutting down...", RED)
        sys.exit(1) # Triggers finally blocks in context managers if we were inside one?
        # No, sys.exit raises SystemExit.
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        with test_database() as db_url:
            log("🚀 Starting Tests...", GREEN)
            
            # Prepare Environment
            env = os.environ.copy()
            env["DATABASE_URL"] = db_url
            env["S3_ACCESS_KEY"] = "minio"
            env["S3_SECRET_KEY"] = "minio_local_secret"
            env["S3_ENDPOINT"] = "http://localhost:9000" # Assumptions
            env["S3_BUCKET"] = "statements"

            # Run Pytest (via uv)
            # We call the 'moon' defined test command, OR directly pytest?
            # Calling 'moon' recursively might be weird if this script is CALLED by moon.
            # So we call 'uv run pytest' directly.
            
            cmd = ["uv", "run", "pytest", "-v", "--cov=src", "--cov-report=term-missing"] + pytest_args
            
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
