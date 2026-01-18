#!/usr/bin/env python3
"""
Frontend dev server with proper resource lifecycle management.

Usage: python scripts/dev_frontend.py

Resources managed (only those started by THIS script):
- Next.js dev server (tracked by PID)

Lifecycle: Starts with script, stops on Ctrl+C (SIGINT/SIGTERM)

NOTE: Does NOT kill other Next.js processes - only the one we started.
"""

import os
import signal
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

# Track resources started by THIS script
_started_resources: dict = {
    "next_proc": None,
}


def cleanup(signum=None, frame=None):
    """Clean up only the resources WE started."""
    print("\n🧹 Cleaning up frontend resources...")

    # Stop Next.js process (only ours)
    proc = _started_resources.get("next_proc")
    if proc and proc.poll() is None:
        print("  ✓ Stopping Next.js dev server...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    print("✅ Cleanup complete")
    sys.exit(0)


def main():
    # Set up signal handlers
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    app_url = os.getenv("NEXT_PUBLIC_APP_URL", "http://localhost:3000")
    print(f"🚀 Starting Next.js dev server on {app_url}")
    print("   Press Ctrl+C to stop")
    print()

    # Start Next.js and track the process
    frontend_dir = REPO_ROOT / "apps" / "frontend"
    proc = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=frontend_dir,
    )
    _started_resources["next_proc"] = proc

    # Wait for process
    try:
        proc.wait()
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
