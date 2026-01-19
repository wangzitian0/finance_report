#!/usr/bin/env python3
"""
Backend dev server with proper resource lifecycle management.

Usage: python scripts/dev_backend.py

Resources managed (only those started by THIS script):
- uvicorn dev server (tracked by PID)
- Development database container (tracked by container ID)

Lifecycle: Starts with script, stops on Ctrl+C (SIGINT/SIGTERM)
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
COMPOSE_FILE = os.environ.get("COMPOSE_FILE", str(REPO_ROOT / "docker-compose.yml"))

# Track resources started by THIS script
_started_resources: dict = {
    "uvicorn_proc": None,
    "db_container_id": None,
}


def get_compose_cmd() -> list[str]:
    """Detect available compose command."""
    for cmd in [
        ["podman", "compose"],
        ["docker", "compose"],
    ]:
        try:
            subprocess.run(
                [*cmd, "version"],
                capture_output=True,
                check=True,
            )
            return cmd
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    return []


def start_database(compose_cmd: list[str]) -> str | None:
    """Start the development database, return container ID."""
    if not compose_cmd:
        print("⚠️  No compose command found, skipping database")
        return None

    print("🐘 Starting development database...")
    subprocess.run(
        [*compose_cmd, "-f", COMPOSE_FILE, "up", "-d", "postgres"],
        check=True,
    )

    # Get container ID
    result = subprocess.run(
        [compose_cmd[0], "ps", "-a", "--filter", "name=finance-report-db", "--format", "{{.ID}}"],
        capture_output=True,
        text=True,
    )
    container_id = result.stdout.strip().split("\n")[0] if result.stdout.strip() else None

    # Wait for database to be ready
    for _ in range(30):
        try:
            subprocess.run(
                [*compose_cmd, "-f", COMPOSE_FILE, "exec", "-T", "postgres", "pg_isready", "-U", "postgres"],
                capture_output=True,
                check=True,
            )
            print("  ✓ Database ready")
            
            # --- 新增：自动运行迁移 ---
            print("  🚀 Running migrations for development...")
            subprocess.run(
                ["uv", "run", "alembic", "upgrade", "head"],
                cwd=REPO_ROOT / "apps" / "backend",
                check=True,
            )
            print("  ✓ Migrations completed")
            
            return container_id
        except subprocess.CalledProcessError:
            time.sleep(1)


    print("  ⚠️  Database may not be ready")
    return container_id


def stop_database(compose_cmd: list[str], container_id: str | None):
    """Stop the database container we started."""
    if not container_id or not compose_cmd:
        return

    print("  ✓ Stopping dev database...")
    try:
        subprocess.run(
            [compose_cmd[0], "stop", container_id],
            capture_output=True,
            timeout=10,
        )
    except Exception:
        pass


def cleanup(signum=None, frame=None):
    """Clean up only the resources WE started."""
    print("\n🧹 Cleaning up dev resources...")

    # Stop uvicorn process (only ours)
    proc = _started_resources.get("uvicorn_proc")
    if proc and proc.poll() is None:
        print("  ✓ Stopping uvicorn...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    # Stop database (only if we started it)
    compose_cmd = get_compose_cmd()
    container_id = _started_resources.get("db_container_id")
    if container_id:
        stop_database(compose_cmd, container_id)

    print("✅ Cleanup complete")
    sys.exit(0)


def main():
    # Set up signal handlers
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    compose_cmd = get_compose_cmd()

    # Start database and track container ID
    container_id = start_database(compose_cmd)
    _started_resources["db_container_id"] = container_id

    # Set environment
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/finance_report"
    )
    os.environ.setdefault("S3_ACCESS_KEY", "minio")
    os.environ.setdefault("S3_SECRET_KEY", "minio123")

    print("🚀 Starting FastAPI dev server on http://localhost:8000")
    print("   Press Ctrl+C to stop")
    print()

    # Start uvicorn and track the process
    backend_dir = REPO_ROOT / "apps" / "backend"
    proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "src.main:app", "--reload", "--host", "0.0.0.0", "--port", "8000"],
        cwd=backend_dir,
    )
    _started_resources["uvicorn_proc"] = proc

    # Wait for process
    try:
        proc.wait()
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
