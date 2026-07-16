#!/usr/bin/env python3
"""
Backend dev server with proper resource lifecycle management.

Usage: python tools/dev_backend.py

Resources managed (only those started by THIS script):
- uvicorn dev server (tracked by PID)
- Development database container (tracked by container ID)

Lifecycle: Starts with script, stops on Ctrl+C (SIGINT/SIGTERM)
"""

import os
import signal
import subprocess
from collections.abc import Sequence
from pathlib import Path

from tools._lib.dev.toolchain import (  # noqa: F401
    get_compose_cmd,
    get_runtime_version,
    uv_run,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_FILE = os.environ.get("COMPOSE_FILE", str(REPO_ROOT / "docker-compose.yml"))

# Track resources started by THIS script
_started_resources: dict = {
    "uvicorn_proc": None,
    "stack_started": False,
}


def check_database_ready() -> bool:
    """Check if the database is accessible and run migrations."""
    print("🐘 Checking database connection...")

    # We use a simple socket check or pg_isready via shell if available
    # But since we want to run migrations, let's just try to run alembic check/upgrade
    # If that works, the DB is ready.

    try:
        # Check connectivity first to fail fast with a good message
        # (Optional: could use socket here, but alembic is the ultimate test)
        pass
    except Exception:
        pass

    # Try running migrations
    print("  🚀 Running migrations...")
    try:
        subprocess.run(
            uv_run("python", "-m", "alembic", "upgrade", "head"),
            cwd=REPO_ROOT / "apps" / "backend",
            check=True,
            capture_output=True,  # Capture output to avoid noise if it fails
        )
        print("  ✓ Migrations completed (Database is ready)")
        return True
    except subprocess.CalledProcessError as e:
        print("\n❌ Error connecting to database or running migrations.")
        print(
            f"   Stderr: {e.stderr.decode().strip() if e.stderr else 'Unknown error'}"
        )
        print("\n💡 TIP: Did you forget to run the infrastructure?")
        print("   Run 'bash tools/infra.sh up' in a separate terminal first.")
        return False


def cleanup() -> None:
    """Clean up resources."""
    print("\n🧹 Stopping uvicorn...")

    proc = _started_resources.get("uvicorn_proc")
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _request_shutdown(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt


def main(argv: Sequence[str] | None = None) -> int:
    # Set up signal handlers
    signal.signal(signal.SIGINT, _request_shutdown)
    signal.signal(signal.SIGTERM, _request_shutdown)

    # Set environment defaults (Localhost)
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/finance_report",
    )
    os.environ.setdefault("S3_ENDPOINT", "http://localhost:9000")
    os.environ.setdefault("S3_ACCESS_KEY", "minio")
    os.environ.setdefault("S3_SECRET_KEY", "minio_local_secret")
    os.environ.setdefault("S3_BUCKET", "statements")

    # Check dependencies
    if not check_database_ready():
        return 1

    print("\n🚀 Starting FastAPI dev server on http://localhost:8000")
    print("   Press Ctrl+C to stop (Infrastructure will keep running)")
    print()

    # Start uvicorn
    backend_dir = REPO_ROOT / "apps" / "backend"
    proc = subprocess.Popen(
        uv_run(
            "python",
            "-m",
            "uvicorn",
            "src.main:app",
            "--reload",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
        ),
        cwd=backend_dir,
    )
    _started_resources["uvicorn_proc"] = proc

    # Wait for process
    try:
        return proc.wait() or 0
    except KeyboardInterrupt:
        cleanup()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
