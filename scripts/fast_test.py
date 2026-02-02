#!/usr/bin/env python3
"""
Ultra-fast test mode: Skip all coverage collection.
Uses test_lifecycle.py for proper database management.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.absolute()

pytest_args = [
    "-n",
    "auto",
    "-m",
    "not slow and not e2e",
    "--dist",
    "worksteal",
    "--tb=short",
]

print("🚀 Ultra-Fast Test Mode: No coverage collection")
print("━" * 60)
print()

test_lifecycle_path = REPO_ROOT / "scripts" / "test_lifecycle.py"
sys.exit(subprocess.call([sys.executable, str(test_lifecycle_path)] + pytest_args))
