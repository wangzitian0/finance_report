#!/usr/bin/env python3
"""
Get changed Python files for smart coverage testing.

Usage:
    python scripts/get_changed_files.py [--base BRANCH]

Returns pytest --cov flag for changed files only.
"""

import argparse
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent.absolute()


def get_changed_files(base_branch: str = "main") -> list[str]:
    try:
        files_set: set[str] = set()

        diff_commands: list[list[str]] = [
            ["git", "diff", "--name-status", f"{base_branch}...HEAD"],
            ["git", "diff", "--name-status", "HEAD"],
            ["git", "diff", "--name-status", "--cached"],
        ]

        for cmd in diff_commands:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
            )
            stdout = result.stdout.strip()
            if not stdout:
                continue
            for line in stdout.split("\n"):
                line = line.strip()
                if not line:
                    continue
                parts = line.split(maxsplit=1)
                if len(parts) != 2:
                    continue
                status, filepath = parts
                if status == "D":
                    continue
                files_set.add(filepath)

        files = sorted(files_set)

        changed_py_files = [
            f for f in files if f.startswith("apps/backend/src/") and f.endswith(".py")
        ]

        modules = []
        for file in changed_py_files:
            file_path = REPO_ROOT / file
            if not file_path.exists():
                continue

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
