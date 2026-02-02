#!/usr/bin/env python3
"""
Smart test strategy: Full tests + Targeted coverage on changed files only.
Uses test_lifecycle.py for proper database management.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from get_changed_files import get_changed_files


def main():
    print("🧪 Smart Test Strategy: Full tests + Targeted coverage")
    print("━" * 60)
    print()

    modules = get_changed_files()
    changed_count = len(modules)

    print("📊 Test Plan:")
    print(f"  ├─ Changed modules: {changed_count}")
    print("  ├─ Coverage target: Only changed files (99%)")
    print("  └─ Test scope: All tests (fast, no coverage overhead)")
    print()

    pytest_args = [
        "-n",
        "auto",
        "-m",
        "not slow and not e2e",
        "--dist",
        "worksteal",
    ]

    if changed_count == 0:
        print("✅ No source changes detected - running full coverage")
        print()
        pytest_args.extend(
            [
                "--cov=src",
                "--cov-report=lcov",
                "--cov-report=term-missing",
                "--cov-branch",
                "--cov-fail-under=94",
            ]
        )
    else:
        print("⚡ Smart mode: Full tests + Coverage on changed files only")
        for module in modules:
            print(f"  • {module}")
        print()

        for module in modules:
            pytest_args.append(f"--cov={module}")

        pytest_args.extend(
            [
                "--cov-report=lcov",
                "--cov-report=term-missing",
                "--cov-branch",
                "--cov-fail-under=99",
            ]
        )

    test_lifecycle_path = REPO_ROOT / "scripts" / "test_lifecycle.py"
    sys.exit(subprocess.call([sys.executable, str(test_lifecycle_path)] + pytest_args))


if __name__ == "__main__":
    main()
