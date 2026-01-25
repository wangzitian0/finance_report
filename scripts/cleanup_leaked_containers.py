#!/usr/bin/env python3
"""
scripts/cleanup_leaked_containers.py

Precise cleanup of leaked finance-report database containers and state files.
This script:
1.  Reads state files from ~/.cache/finance_report/ to find tracked containers.
2.  Scans Podman/Docker for containers matching 'finance-report-db-*'.
3.  Stops and removes these containers.
4.  Cleans up the state files.
"""

import os
import glob
import subprocess
import shutil
from pathlib import Path

# Configuration
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "finance_report"
CONTAINER_PREFIX = "finance-report-db"
RUNTIME = "podman"  # Default to podman based on environment check

def check_runtime():
    """Verify if podman or docker is available."""
    global RUNTIME
    if shutil.which("podman"):
        RUNTIME = "podman"
    elif shutil.which("docker"):
        RUNTIME = "docker"
    else:
        print("❌ Neither podman nor docker found. Cannot clean containers.")
        return False
    return True

def get_containers_from_state_files():
    """Read container IDs from state files."""
    containers = {}
    if not CACHE_DIR.exists():
        return containers

    for state_file in CACHE_DIR.glob("db-*.state"):
        try:
            with open(state_file, "r") as f:
                content = f.read()
                # Simple parsing of key=value
                data = dict(line.split("=", 1) for line in content.splitlines() if "=" in line)
                cid = data.get("container_id", "").strip()
                if cid:
                    containers[cid] = state_file
        except Exception as e:
            print(f"⚠️  Error reading {state_file}: {e}")
    return containers

def get_leaked_containers_from_runtime():
    """List all containers matching the prefix."""
    try:
        cmd = [RUNTIME, "ps", "-a", "--format", "{{.ID}} {{.Names}}"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        leaked = []
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                cid = parts[0]
                name = parts[1]
                if name.startswith(CONTAINER_PREFIX):
                    leaked.append((cid, name))
        return leaked
    except subprocess.CalledProcessError as e:
        print(f"❌ Error listing containers: {e}")
        return []

def cleanup():
    if not check_runtime():
        return

    print(f"🔍 Scanning for leaked resources using {RUNTIME}...")
    
    # 1. containers from state files
    tracked_containers = get_containers_from_state_files()
    
    # 2. containers from runtime
    runtime_containers = get_leaked_containers_from_runtime()
    
    to_remove = set()
    
    # Add tracked containers
    for cid in tracked_containers:
        to_remove.add(cid)
        
    # Add runtime containers (by ID)
    for cid, name in runtime_containers:
        if name == "finance-report-db":
            print(f"ℹ️  Found main dev container '{name}' ({cid}). Skipping to preserve local dev data.")
            # Note: We skip the main 'finance-report-db' to be safe, unless it's explicitly tracked in a state file?
            # Actually, state files often track ephemeral ones. 
            # If a state file points to the main DB, it might be 'managed=false'.
            # Let's check if we should remove it.
            # For now, let's SKIP the main one to be non-violent.
            if cid in to_remove:
                to_remove.remove(cid)
            continue
        
        print(f"found leaked container: {name} ({cid})")
        to_remove.add(cid)

    if not to_remove:
        print("✅ No leaked containers found.")
    else:
        print(f"🧹 Removing {len(to_remove)} leaked containers...")
        for cid in to_remove:
            try:
                print(f"   Stopping/Removing {cid}...")
                subprocess.run([RUNTIME, "rm", "-f", cid], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception as e:
                print(f"   Failed to remove {cid}: {e}")

    # 3. Clean up state files
    print("🧹 Cleaning up state files...")
    count = 0
    if CACHE_DIR.exists():
        for state_file in CACHE_DIR.glob("db-*.state"):
            try:
                # Only delete if we decided it was a leak (or just clean all state files to reset?)
                # Cleaning all state files is safer to reset the logic in test_backend.sh
                state_file.unlink()
                count += 1
            except Exception as e:
                print(f"   Failed to remove {state_file}: {e}")
    print(f"   Removed {count} state files.")

    print("✨ Cleanup complete.")

if __name__ == "__main__":
    cleanup()
