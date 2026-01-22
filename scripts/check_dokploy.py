"""
Check Dokploy compose service configuration and environment variables.

Usage:
    python scripts/check_dokploy.py [compose_id]

Environment Variables:
    COMPOSE_ID: Default compose ID if not provided as argument
"""

import os
import sys
from libs.dokploy import get_dokploy


def check_service(compose_id: str | None = None) -> None:
    """Check compose service configuration."""
    client = get_dokploy()

    # Use provided ID, environment variable, or default
    if not compose_id:
        compose_id = os.getenv("COMPOSE_ID", "A6V-hbJlgHMwgPDoTDnhH")

    try:
        compose = client.get_compose(compose_id)
        print(f"Service Name: {compose.get('name')}")
        print(f"Project Name: {compose.get('project', {}).get('name')}")
        print(f"Environment Name: {compose.get('environment', {}).get('name')}")
        print("\nEnvironment Variables:")
        print(compose.get("env", "No env vars found"))
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    compose_id = sys.argv[1] if len(sys.argv) > 1 else None
    check_service(compose_id)
