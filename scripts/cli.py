#!/usr/bin/env python3
"""
scripts/cli.py - Unified CLI entry point for all moon commands.

Usage:
    python scripts/cli.py <command> [options]

Commands:
    setup   - Install dependencies
    dev     - Start development environment
    test    - Run tests
    lint    - Code quality checks
    build   - Build projects
    clean   - Clean up resources
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.absolute()
BACKEND_DIR = REPO_ROOT / "apps" / "backend"
FRONTEND_DIR = REPO_ROOT / "apps" / "frontend"


def get_compose_cmd() -> list[str]:
    """Detect container runtime (podman or docker) and return compose command."""
    if shutil.which("podman"):
        return ["podman", "compose"]
    elif shutil.which("docker"):
        return ["docker", "compose"]
    else:
        print("ERROR: Neither podman nor docker found in PATH")
        sys.exit(1)


def run(cmd: list[str], cwd: Path = REPO_ROOT, env: dict = None, check: bool = True):
    """Run a command with proper error handling."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    print(f"▶ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd, env=full_env)
    if check and result.returncode != 0:
        sys.exit(result.returncode)
    return result


def cmd_setup(args):
    """Install dependencies."""
    if args.backend or not args.frontend:
        run(["uv", "sync"], cwd=BACKEND_DIR)
    if args.frontend or not args.backend:
        run(["npm", "install"], cwd=FRONTEND_DIR)


def cmd_dev(args):
    """Start development environment."""
    compose_cmd = get_compose_cmd()
    
    if args.infra or (not args.backend and not args.frontend):
        run([*compose_cmd, "--profile", "infra", "up", "-d"])
    
    if args.migrate:
        run(["uv", "run", "alembic", "upgrade", "head"], cwd=BACKEND_DIR)
        return
    
    if args.check:
        run(["uv", "run", "python", "-m", "src.boot", "--mode=full"], cwd=BACKEND_DIR)
        return

    if args.backend:
        run(["python", "../../scripts/dev_backend.py"], cwd=BACKEND_DIR)
    elif args.frontend:
        run(["python", "../../scripts/dev_frontend.py"], cwd=FRONTEND_DIR)
    elif not args.infra:
        print("\n🚀 Infrastructure started. Now run in separate terminals:")
        print("   moon run :dev -- --backend")
        print("   moon run :dev -- --frontend")


def cmd_test(args, extra_args: list[str]):
    """Run tests."""
    if args.frontend:
        run(["npm", "run", "test"] + extra_args, cwd=FRONTEND_DIR)
        return
    
    if args.e2e:
        run(["uv", "run", "pytest", "-m", "e2e", "tests/e2e/"] + extra_args, cwd=BACKEND_DIR)
        return
    
    if args.perf:
        run([
            "uv", "run", "locust", "-f", "tests/locustfile.py",
            "--host=http://localhost:8000", "--users", "10",
            "--spawn-rate", "2", "--run-time", "30s", "--headless"
        ], cwd=BACKEND_DIR)
        return
    
    # Default: use test_lifecycle.py
    lifecycle_args = []
    if args.fast:
        lifecycle_args.append("--fast")
    if args.smart:
        lifecycle_args.append("--smart")
    if args.ephemeral:
        lifecycle_args.append("--ephemeral")
    
    lifecycle_args.extend(extra_args)
    run(["python", "../../scripts/test_lifecycle.py"] + lifecycle_args, cwd=BACKEND_DIR)


def cmd_lint(args):
    """Run linting and formatting."""
    if args.backend or not args.frontend:
        if args.fix:
            run(["uv", "run", "ruff", "format", "src/"], cwd=BACKEND_DIR)
            run(["uv", "run", "ruff", "check", "src/", "--fix"], cwd=BACKEND_DIR)
        else:
            run(["uv", "run", "ruff", "check", "src/"], cwd=BACKEND_DIR)
            run(["uv", "run", "ruff", "format", "src/", "--check"], cwd=BACKEND_DIR, check=False)
    
    if args.frontend or not args.backend:
        if args.fix:
            run(["npm", "run", "lint", "--", "--fix"], cwd=FRONTEND_DIR, check=False)
        else:
            run(["npm", "run", "lint"], cwd=FRONTEND_DIR)


def cmd_build(args):
    """Build projects."""
    # Currently only frontend needs explicit build
    run(["npm", "run", "build"], cwd=FRONTEND_DIR)


def cmd_clean(args):
    """Clean up resources."""
    compose_cmd = get_compose_cmd()
    
    if args.db:
        run(["python", "scripts/cleanup_orphaned_dbs.py"])
    elif args.containers:
        run([*compose_cmd, "--profile", "infra", "down"])
    else:
        cmd = ["bash", "scripts/cleanup_dev_resources.sh"]
        if args.force:
            cmd.append("--force")
        if args.all:
            cmd.append("--all")
        run(cmd)


def main():
    parser = argparse.ArgumentParser(description="Unified CLI for finance_report")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # setup
    p_setup = subparsers.add_parser("setup", help="Install dependencies")
    p_setup.add_argument("--backend", action="store_true", help="Backend only")
    p_setup.add_argument("--frontend", action="store_true", help="Frontend only")

    # dev
    p_dev = subparsers.add_parser("dev", help="Start development environment")
    p_dev.add_argument("--infra", action="store_true", help="Infrastructure only")
    p_dev.add_argument("--backend", action="store_true", help="Backend server")
    p_dev.add_argument("--frontend", action="store_true", help="Frontend server")
    p_dev.add_argument("--migrate", action="store_true", help="Run migrations")
    p_dev.add_argument("--check", action="store_true", help="Environment check")

    # test - use parse_known_args for transparent pass-through
    p_test = subparsers.add_parser("test", help="Run tests")
    p_test.add_argument("--fast", action="store_true", help="No coverage, fast")
    p_test.add_argument("--smart", action="store_true", help="Coverage on changed files")
    p_test.add_argument("--ephemeral", action="store_true", help="Ephemeral mode: destroy all infra after run")
    p_test.add_argument("--e2e", action="store_true", help="E2E tests")
    p_test.add_argument("--perf", action="store_true", help="Performance tests")
    p_test.add_argument("--frontend", action="store_true", help="Frontend tests")

    # lint
    p_lint = subparsers.add_parser("lint", help="Code quality checks")
    p_lint.add_argument("--fix", action="store_true", help="Auto-fix issues")
    p_lint.add_argument("--backend", action="store_true", help="Backend only")
    p_lint.add_argument("--frontend", action="store_true", help="Frontend only")

    # build
    p_build = subparsers.add_parser("build", help="Build projects")
    p_build.add_argument("--frontend", action="store_true", help="Frontend only")

    # clean
    p_clean = subparsers.add_parser("clean", help="Clean up resources")
    p_clean.add_argument("--db", action="store_true", help="Clean test databases")
    p_clean.add_argument("--containers", action="store_true", help="Stop containers")
    p_clean.add_argument("--force", action="store_true", help="Force clean processes/leaked containers")
    p_clean.add_argument("--all", action="store_true", help="Deep clean (including volumes)")

    # Use parse_known_args for test command to allow pass-through of pytest args
    args, extra = parser.parse_known_args()

    if args.command == "test":
        cmd_test(args, extra)
    else:
        commands = {
            "setup": cmd_setup,
            "dev": cmd_dev,
            "lint": cmd_lint,
            "build": cmd_build,
            "clean": cmd_clean,
        }
        commands[args.command](args)


if __name__ == "__main__":
    main()
