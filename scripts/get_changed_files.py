#!/usr/bin/env python3
"""
Get changed Python files for smart coverage testing.

Usage:
    python scripts/get_changed_files.py [--base BRANCH]

Returns pytest --cov flag for changed files only.
"""

import argparse
import subprocess
import sys
from pathlib import Path


def get_changed_files(base_branch: str = "main") -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base_branch}...HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )

        if not result.stdout.strip():
            result = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )

        if not result.stdout.strip():
            result = subprocess.run(
                ["git", "diff", "--name-only", "--cached"],
                capture_output=True,
                text=True,
                check=True,
            )

        files = result.stdout.strip().split("\n")

        changed_py_files = [
            f for f in files if f.startswith("apps/backend/src/") and f.endswith(".py")
        ]

        modules = []
        for file in changed_py_files:
            rel_path = file.replace("apps/backend/", "").replace(".py", "")
            module = rel_path.replace("/", ".")
            modules.append(module)

        return modules

    except subprocess.CalledProcessError:
        return []


def main():
    parser = argparse.ArgumentParser(
        description="Get changed Python files for coverage"
    )
    parser.add_argument(
        "--base",
        default="main",
        help="Base branch to compare against (default: main)",
    )
    parser.add_argument(
        "--format",
        choices=["pytest", "list", "count"],
        default="pytest",
        help="Output format",
    )
    args = parser.parse_args()

    modules = get_changed_files(args.base)

    if args.format == "count":
        print(len(modules))
    elif args.format == "list":
        for module in modules:
            print(module)
    else:
        if modules:
            cov_flags = " ".join([f"--cov={module}" for module in modules])
            print(cov_flags)
        else:
            print("--cov=src")


if __name__ == "__main__":
    main()
