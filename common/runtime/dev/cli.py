#!/usr/bin/env python3
"""
Unified CLI for development and background jobs.

Usage:
    python -m common.runtime.dev.cli <command> [options]

Commands:
    setup   - Install dependencies
    dev     - Start development environment
    test    - Run tests
    lint    - Code quality checks
    build   - Build projects
    clean   - Clean up resources
    job     - List or run background jobs
"""

import argparse
import importlib.util
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from common.runtime.dev.toolchain import get_compose_cmd, get_runtime_version, uv_run

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_DIR = REPO_ROOT / "apps" / "backend"
FRONTEND_DIR = REPO_ROOT / "apps" / "frontend"


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
        run(["uv", "sync", "--python", get_runtime_version("python")], cwd=BACKEND_DIR)
    if args.frontend or not args.backend:
        run(["npm", "ci"], cwd=FRONTEND_DIR)


def cmd_dev(args):
    """Start development environment."""
    compose_cmd = get_compose_cmd()

    if args.infra or (not args.backend and not args.frontend):
        run([*compose_cmd, "--profile", "infra", "up", "-d"])

    if args.migrate:
        run(uv_run("python", "-m", "alembic", "upgrade", "head"), cwd=BACKEND_DIR)
        return

    if args.check:
        run(uv_run("python", "-m", "src.boot", "--mode=full"), cwd=BACKEND_DIR)
        return

    if args.backend:
        run(
            uv_run("uvicorn", "src.main:app", "--reload", "--port", "8000"),
            cwd=BACKEND_DIR,
        )
    elif args.frontend:
        run(["npm", "run", "dev"], cwd=FRONTEND_DIR)
    elif not args.infra:
        print("\n🚀 Infrastructure started. Now run in separate terminals:")
        print("   make backend")
        print("   make frontend")


def cmd_test(args, extra_args: list[str]):
    """Run tests."""
    if args.frontend:
        run(["npm", "run", "test"] + extra_args, cwd=FRONTEND_DIR)
        return
    if getattr(args, "backend_e2e", False):
        run(
            uv_run(
                "python",
                "-m",
                "pytest",
                "tests/tooling/test_benchmark_scenario_suite.py",
            )
            + extra_args,
            cwd=REPO_ROOT,
        )
        return
    if args.e2e:
        run(
            uv_run("python", "-m", "pytest", "-m", "e2e", "tests/e2e/") + extra_args,
            cwd=REPO_ROOT,
        )
        return
    if args.perf:
        run(
            uv_run(
                "python",
                "-m",
                "locust",
                "-f",
                "tests/locustfile.py",
                "--host=http://localhost:8000",
                "--users",
                "10",
                "--spawn-rate",
                "2",
                "--run-time",
                "30s",
                "--headless",
            ),
            cwd=BACKEND_DIR,
        )
        return

    cov_override = (
        ["--no-cov"]
        if not any(a.startswith("--cov") or a == "--no-cov" for a in extra_args)
        else []
    )
    run(uv_run("python", "-m", "pytest") + cov_override + extra_args, cwd=BACKEND_DIR)


def cmd_lint(args):
    """Run linting and formatting."""
    if args.backend or not args.frontend:
        if args.fix:
            run(
                uv_run("python", "-m", "ruff", "format", "src", "tests"),
                cwd=BACKEND_DIR,
            )
            run(
                uv_run("python", "-m", "ruff", "check", "src", "tests", "--fix"),
                cwd=BACKEND_DIR,
            )
        else:
            run(
                uv_run("python", "-m", "ruff", "check", "src", "tests"),
                cwd=BACKEND_DIR,
            )
            run(
                uv_run("python", "-m", "ruff", "format", "src", "tests", "--check"),
                cwd=BACKEND_DIR,
            )

    if args.frontend or not args.backend:
        if args.fix:
            run(["npm", "run", "lint", "--", "--fix"], cwd=FRONTEND_DIR, check=False)
        else:
            run(["npm", "run", "lint"], cwd=FRONTEND_DIR)
            run(["npm", "run", "typecheck"], cwd=FRONTEND_DIR)


def cmd_build(args):
    """Build projects."""
    # Currently only frontend needs explicit build
    run(["npm", "run", "build"], cwd=FRONTEND_DIR)


def cmd_clean(args):
    """Clean up resources."""
    compose_cmd = get_compose_cmd()

    if args.containers or args.db:
        run([*compose_cmd, "--profile", "infra", "down"])
    else:
        cmd = ["bash", str(REPO_ROOT / "tools" / "cleanup_dev_resources.sh")]
        if args.all:
            cmd.append("--all")
        elif args.force:
            cmd.append("--force")
        run(cmd)


def _load_background_jobs():
    jobs_path = BACKEND_DIR / "src" / "runtime" / "base" / "jobs.py"
    spec = importlib.util.spec_from_file_location("runtime_base_jobs", jobs_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.BACKGROUND_JOBS


def cmd_job(args):
    """List or manually run a registered backend background job."""
    if args.list:
        for job in _load_background_jobs():
            print(
                f"{job.cli_name}\t{job.concurrency}\t{job.failure_metric}\t{job.summary}"
            )
        return

    python_bin = BACKEND_DIR / ".venv" / "bin" / "python"
    script = (
        "import asyncio, json, sys; "
        "from src.main import run_background_job_once; "
        "print(json.dumps(asyncio.run(run_background_job_once(sys.argv[1]))))"
    )
    if python_bin.exists():
        cmd = [str(python_bin), "-c", script, args.run_once]
    else:
        cmd = uv_run("python", "-c", script, args.run_once)
    run(cmd, cwd=BACKEND_DIR)


def main(argv: Sequence[str] | None = None) -> int:
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
    p_test.add_argument(
        "--e2e",
        action="store_true",
        help="Root deployment E2E tests from tests/e2e/",
    )
    p_test.add_argument(
        "--backend-e2e",
        action="store_true",
        help="Backend scenario benchmark tests from tests/tooling/test_benchmark_scenario_suite.py",
    )
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
    p_clean.add_argument("--db", action="store_true", help="Stop containers")
    p_clean.add_argument("--containers", action="store_true", help="Stop containers")
    p_clean.add_argument(
        "--force", action="store_true", help="Force clean processes/leaked containers"
    )
    p_clean.add_argument(
        "--all", action="store_true", help="Deep clean (including volumes)"
    )

    # job
    p_job = subparsers.add_parser("job", help="List or manually run background jobs")
    job_group = p_job.add_mutually_exclusive_group(required=True)
    job_group.add_argument("--list", action="store_true", help="List background jobs")
    job_group.add_argument(
        "--run-once", metavar="CLI_NAME", help="Run one pass of a background job"
    )

    # Use parse_known_args for test command to allow pass-through of pytest args
    args, extra = (
        parser.parse_known_args() if argv is None else parser.parse_known_args(argv)
    )

    if args.command == "test":
        cmd_test(args, extra)
    else:
        commands = {
            "setup": cmd_setup,
            "dev": cmd_dev,
            "lint": cmd_lint,
            "build": cmd_build,
            "clean": cmd_clean,
            "job": cmd_job,
        }
        commands[args.command](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
