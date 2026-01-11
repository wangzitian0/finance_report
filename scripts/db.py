#!/usr/bin/env python3
"""Database lifecycle management for development and testing.

Usage:
    python scripts/db.py start          # Start dev database (persistent)
    python scripts/db.py start --test   # Start ephemeral test database
    python scripts/db.py stop           # Stop dev database
    python scripts/db.py status         # Check database status
    python scripts/db.py destroy        # Remove dev database and data

Environment Variables:
    CONTAINER_RUNTIME: "podman" (default) or "docker"
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time

CONTAINER_RUNTIME = os.getenv("CONTAINER_RUNTIME", "podman")
CONTAINER_PREFIX = "fr"
DEV_CONTAINER = f"{CONTAINER_PREFIX}_dev_db"
POSTGRES_IMAGE = "postgres:15-alpine"
DEFAULT_PASSWORD = "postgres"
DEFAULT_DB = "finance_report"
TEST_DB = "finance_report_test"


def _run(cmd: list[str], check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    """Run a command with the configured container runtime."""
    full_cmd = [CONTAINER_RUNTIME] + cmd
    return subprocess.run(full_cmd, check=check, capture_output=capture, text=True)


def _container_exists(name: str) -> bool:
    """Check if a container exists (running or stopped)."""
    result = _run(["ps", "-aq", "-f", f"name=^{name}$"], check=False, capture=True)
    return bool(result.stdout.strip())


def _container_running(name: str) -> bool:
    """Check if a container is running."""
    result = _run(["ps", "-q", "-f", f"name=^{name}$"], check=False, capture=True)
    return bool(result.stdout.strip())


def _find_free_port() -> int:
    """Find a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _wait_for_postgres(port: int, timeout: int = 30) -> bool:
    """Wait for PostgreSQL to be ready."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                s.connect(("localhost", port))
                return True
        except (socket.error, ConnectionRefusedError):
            time.sleep(0.5)
    return False


def _get_container_port(name: str) -> int | None:
    """Get the host port mapped to container's 5432."""
    result = _run(["port", name, "5432"], check=False, capture=True)
    if result.returncode == 0 and result.stdout.strip():
        # Output format: "0.0.0.0:12345" or ":::12345"
        port_str = result.stdout.strip().split(":")[-1]
        return int(port_str)
    return None


def start(*, ephemeral: bool = False) -> tuple[str, int]:
    """Start a database container.
    
    Args:
        ephemeral: If True, create a temporary container with tmpfs storage.
        
    Returns:
        Tuple of (container_name, port)
    """
    if ephemeral:
        # Ephemeral container for testing
        name = f"{CONTAINER_PREFIX}_test_{os.getpid()}"
        port = _find_free_port()
        
        cmd = [
            "run", "-d", "--rm",
            "--name", name,
            "--tmpfs", "/var/lib/postgresql/data:rw,noexec,nosuid,size=512m",
            "-p", f"{port}:5432",
            "-e", f"POSTGRES_PASSWORD={DEFAULT_PASSWORD}",
            "-e", f"POSTGRES_DB={TEST_DB}",
            POSTGRES_IMAGE,
        ]
        _run(cmd)
        
        if _wait_for_postgres(port):
            print(f"✓ Ephemeral database started: {name} on port {port}")
        else:
            print(f"✗ Failed to start database (timeout)", file=sys.stderr)
            sys.exit(1)
            
        return name, port
    
    # Development container (persistent)
    name = DEV_CONTAINER
    port = 5432
    
    if _container_running(name):
        print(f"✓ Database already running: {name}")
        return name, port
    
    if _container_exists(name):
        print(f"Starting existing container: {name}")
        _run(["start", name])
    else:
        print(f"Creating new container: {name}")
        cmd = [
            "run", "-d",
            "--name", name,
            "-v", f"{name}_data:/var/lib/postgresql/data",
            "-p", f"{port}:5432",
            "-e", f"POSTGRES_PASSWORD={DEFAULT_PASSWORD}",
            "-e", f"POSTGRES_DB={DEFAULT_DB}",
            POSTGRES_IMAGE,
        ]
        _run(cmd)
    
    if _wait_for_postgres(port):
        print(f"✓ Database ready: {name} on port {port}")
        # Ensure test database exists
        time.sleep(1)  # Give postgres a moment
        _run([
            "exec", name,
            "psql", "-U", "postgres", "-c",
            f"CREATE DATABASE {TEST_DB}",
        ], check=False)
    else:
        print(f"✗ Failed to start database (timeout)", file=sys.stderr)
        sys.exit(1)
    
    return name, port


def stop() -> None:
    """Stop the development database container."""
    if _container_running(DEV_CONTAINER):
        print(f"Stopping {DEV_CONTAINER}...")
        _run(["stop", DEV_CONTAINER])
        print(f"✓ Stopped")
    else:
        print(f"Container {DEV_CONTAINER} is not running")


def status() -> None:
    """Show database container status."""
    result = _run(
        ["ps", "-a", "--filter", f"name={CONTAINER_PREFIX}", 
         "--format", "table {{.Names}}\t{{.Status}}\t{{.Ports}}"],
        check=False, capture=True
    )
    if result.stdout.strip():
        print(result.stdout)
    else:
        print("No finance_report database containers found")


def destroy() -> None:
    """Remove the development container and its data volume."""
    if _container_exists(DEV_CONTAINER):
        print(f"Removing container {DEV_CONTAINER}...")
        _run(["rm", "-f", DEV_CONTAINER], check=False)
    
    # Remove volume
    volume_name = f"{DEV_CONTAINER}_data"
    result = _run(["volume", "ls", "-q", "-f", f"name={volume_name}"], check=False, capture=True)
    if result.stdout.strip():
        print(f"Removing volume {volume_name}...")
        _run(["volume", "rm", volume_name], check=False)
    
    print("✓ Cleanup complete")


def main() -> None:
    parser = argparse.ArgumentParser(description="Database lifecycle management")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    start_parser = subparsers.add_parser("start", help="Start database container")
    start_parser.add_argument("--test", action="store_true", help="Start ephemeral test database")
    
    subparsers.add_parser("stop", help="Stop database container")
    subparsers.add_parser("status", help="Show database status")
    subparsers.add_parser("destroy", help="Remove database and data")
    
    args = parser.parse_args()
    
    if args.command == "start":
        name, port = start(ephemeral=args.test)
        # Output connection string for scripting
        db = TEST_DB if args.test else DEFAULT_DB
        print(f"\nDATABASE_URL=postgresql+asyncpg://postgres:{DEFAULT_PASSWORD}@localhost:{port}/{db}")
    elif args.command == "stop":
        stop()
    elif args.command == "status":
        status()
    elif args.command == "destroy":
        destroy()


if __name__ == "__main__":
    main()
