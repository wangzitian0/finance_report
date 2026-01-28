#!/usr/bin/env python3
"""
Unified debugging tool for Finance Report

Automatically detects environment and uses appropriate log viewing method:
- Local/CI: Docker logs (fast, direct)
- Staging/Production: SigNoz logs (centralized, searchable)

Usage:
    # View logs
    python scripts/debug.py logs backend
    python scripts/debug.py logs frontend --tail 100
    python scripts/debug.py logs backend --env staging

    # Service management (remote only)
    python scripts/debug.py restart backend --env staging
    python scripts/debug.py status backend

    # Container info
    python scripts/debug.py containers --env production
"""

import argparse
import os
import re
import shlex
import subprocess
import sys
from enum import Enum
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


class Environment(Enum):
    """Deployment environment types"""

    LOCAL = "local"
    CI = "ci"
    STAGING = "staging"
    PRODUCTION = "production"


class Service(Enum):
    """Available services"""

    BACKEND = "backend"
    FRONTEND = "frontend"
    POSTGRES = "postgres"
    REDIS = "redis"


# Container name patterns per environment
CONTAINER_PATTERNS = {
    Environment.LOCAL: {
        Service.BACKEND: "finance-report-backend",
        Service.FRONTEND: "finance-report-frontend",
        Service.POSTGRES: "finance-report-db",
        Service.REDIS: "finance-report-redis",
    },
    Environment.CI: {
        Service.BACKEND: "finance-report-backend",
        Service.FRONTEND: "finance-report-frontend",
        Service.POSTGRES: "finance-report-db",
        Service.REDIS: "finance-report-redis",
    },
    Environment.STAGING: {
        Service.BACKEND: "finance_report-backend-staging",
        Service.FRONTEND: "finance_report-frontend-staging",
        Service.POSTGRES: "finance_report-postgres-staging",
        Service.REDIS: "finance_report-redis-staging",
    },
    Environment.PRODUCTION: {
        Service.BACKEND: "finance_report-backend",
        Service.FRONTEND: "finance_report-frontend",
        Service.POSTGRES: "finance_report-postgres",
        Service.REDIS: "finance_report-redis",
    },
}


def detect_environment() -> Environment:
    """Auto-detect current environment from context"""
    # Check GitHub Actions
    if os.getenv("GITHUB_ACTIONS") == "true":
        return Environment.CI

    # Check if we can connect to local Docker
    try:
        subprocess.run(
            ["docker", "ps"],
            capture_output=True,
            check=True,
            timeout=5,
        )
        return Environment.LOCAL
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ):
        pass

    # Default to production for remote operations
    return Environment.PRODUCTION


def get_container_name(service: Service, env: Environment) -> str:
    """Get container name for service in given environment"""
    return CONTAINER_PATTERNS.get(env, {}).get(
        service, f"finance-report-{service.value}"
    )


def view_local_logs(service: Service, tail: int = 50, follow: bool = False) -> None:
    """View Docker logs locally"""
    env = Environment.LOCAL
    container = get_container_name(service, env)

    print(f"📋 Viewing logs for {container} (local)")

    cmd = ["docker", "logs", container, "--tail", str(tail)]
    if follow:
        cmd.append("-f")

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to get logs: {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("❌ Docker not found. Is Docker installed and running?", file=sys.stderr)
        sys.exit(1)


def validate_hostname(hostname: str) -> bool:
    """Validate hostname matches domain or IP pattern"""
    # Allows dots, hyphens, alphanumeric, but disallows leading hyphens
    # to prevent SSH option injection (e.g. -oProxyCommand)
    if not hostname:
        return False
    return bool(re.match(r"^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$", hostname))


def validate_username(username: str) -> bool:
    """Validate username matches unix pattern"""
    # Allows alphanumeric, hyphens, underscores
    if not username:
        return False
    return bool(re.match(r"^[a-z_][a-z0-9_-]*$", username))


def view_remote_logs_docker(
    service: Service, env: Environment, tail: int = 50, follow: bool = False
) -> None:
    """View Docker logs on remote environment via SSH"""
    container = get_container_name(service, env)

    # Get VPS host from environment
    vps_host = os.getenv("VPS_HOST")
    if not vps_host:
        print(
            "❌ VPS_HOST not set. Set it via environment before running this command.",
            file=sys.stderr,
        )
        print("   Example: export VPS_HOST=1.2.3.4", file=sys.stderr)
        sys.exit(1)

    # Validate VPS_HOST to prevent command injection
    if not validate_hostname(vps_host):
        print(f"❌ Invalid VPS_HOST value: {vps_host}", file=sys.stderr)
        sys.exit(1)

    print(f"📋 Viewing logs for {container} on {env.value} ({vps_host})")

    # Configurable SSH user (default: root)
    ssh_user = os.getenv("VPS_USER", "root")
    if not validate_username(ssh_user):
        print(f"❌ Invalid VPS_USER value: {ssh_user}", file=sys.stderr)
        sys.exit(1)

    # Use shlex.quote to prevent command injection in the remote command
    remote_cmd = f"docker logs {shlex.quote(container)} --tail {int(tail)}"
    if follow:
        remote_cmd += " -f"

    cmd = [
        "ssh",
        f"{ssh_user}@{vps_host}",
        remote_cmd,
    ]

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to get remote logs: {e}", file=sys.stderr)
        sys.exit(1)


def view_remote_logs_signoz(service: Service, env: Environment) -> None:
    """View logs via SigNoz (placeholder for future implementation)"""
    print(f"📊 SigNoz logs for {service.value} in {env.value}")
    print()
    print("🔗 Open SigNoz UI:")

    internal_domain = os.getenv("INTERNAL_DOMAIN", "zitian.party")
    # All environments use the same SigNoz instance
    signoz_url = f"https://signoz.{internal_domain}"

    print(f"   {signoz_url}")
    print()
    print("📝 Query:")
    print(f'   service_name = "finance-report-{service.value}"')
    if env != Environment.PRODUCTION:
        print(f'   deployment.environment = "{env.value}"')
    print()
    print("💡 Future: Direct SigNoz API integration")


def restart_service(service: Service, env: Environment) -> None:
    """Restart service via Dokploy API"""
    if env == Environment.LOCAL:
        print(
            "❌ Restart not supported for local environment. Use Docker directly.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"🔄 Restarting {service.value} in {env.value}...")

    # Map service to container ID
    container = get_container_name(service, env)

    # Note: Dokploy API doesn't have direct log endpoints
    # This requires SSH access or using Dokploy UI
    print(f"⚠️  Dokploy API doesn't support direct container restart")
    print(f"💡 Use: ssh root@$VPS_HOST docker restart {container}")


def list_containers(env: Environment) -> None:
    """List all Finance Report containers in environment"""
    print(f"📦 Finance Report containers in {env.value}:")
    print()

    for service in Service:
        container = get_container_name(service, env)
        print(f"  - {service.value:12} → {container}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified debugging tool for Finance Report",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s logs backend
  %(prog)s logs frontend --tail 100 --follow
  %(prog)s logs backend --env staging
  %(prog)s status backend --env production
  %(prog)s containers --env staging
        """,
    )

    subparsers = parser.add_subparsers(
        dest="command", required=True, help="Command to run"
    )

    # Logs command
    logs_parser = subparsers.add_parser("logs", help="View service logs")
    logs_parser.add_argument(
        "service",
        type=str,
        choices=[s.value for s in Service],
        help="Service to view logs for",
    )
    logs_parser.add_argument(
        "--tail",
        type=int,
        default=50,
        help="Number of lines to show (default: 50)",
    )
    logs_parser.add_argument(
        "--follow",
        "-f",
        action="store_true",
        help="Follow log output",
    )
    logs_parser.add_argument(
        "--env",
        type=str,
        choices=[e.value for e in Environment],
        help="Target environment (default: auto-detect)",
    )
    logs_parser.add_argument(
        "--method",
        type=str,
        choices=["docker", "signoz"],
        default="docker",
        help="Log viewing method (default: docker)",
    )

    # Status command (alias for logs without follow)
    status_parser = subparsers.add_parser("status", help="Check service status")
    status_parser.add_argument(
        "service",
        type=str,
        choices=[s.value for s in Service],
        help="Service to check",
    )
    status_parser.add_argument(
        "--env",
        type=str,
        choices=[e.value for e in Environment],
        help="Target environment (default: auto-detect)",
    )

    # Containers command
    containers_parser = subparsers.add_parser(
        "containers", help="List all container names"
    )
    containers_parser.add_argument(
        "--env",
        type=str,
        choices=[e.value for e in Environment],
        default=Environment.PRODUCTION.value,
        help="Target environment (default: production)",
    )

    args = parser.parse_args()

    # Execute command
    if args.command == "logs":
        service = Service(args.service)
        env = Environment(args.env) if args.env else detect_environment()

        if args.method == "signoz":
            view_remote_logs_signoz(service, env)
        elif env in (Environment.LOCAL, Environment.CI):
            view_local_logs(service, tail=args.tail, follow=args.follow)
        else:
            view_remote_logs_docker(service, env, tail=args.tail, follow=args.follow)

    elif args.command == "status":
        service = Service(args.service)
        env = Environment(args.env) if args.env else detect_environment()

        # Status = logs --tail 20 without follow
        if env in (Environment.LOCAL, Environment.CI):
            view_local_logs(service, tail=20, follow=False)
        else:
            view_remote_logs_docker(service, env, tail=20, follow=False)

    elif args.command == "containers":
        env = Environment(args.env)
        list_containers(env)


if __name__ == "__main__":
    main()
