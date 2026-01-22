"""
Check deployment history for a Dokploy compose service.

Usage:
    python scripts/check_deployments.py [compose_id]

Environment Variables:
    COMPOSE_ID: Default compose ID if not provided as argument
"""

import sys
from libs.dokploy import get_dokploy


def check_deployments(compose_id: str | None = None) -> None:
    """Check deployment history for a compose service."""
    client = get_dokploy()

    # Use provided ID, environment variable, or default
    if not compose_id:
        import os

        compose_id = os.getenv("COMPOSE_ID", "A6V-hbJlgHMwgPDoTDnhH")

    try:
        # Get service details
        compose = client.get_compose(compose_id)
        print(f"Service: {compose.get('name')}")

        # Dokploy API may not expose a public method in libs.dokploy to list deployments directly
        # but we can inspect the current state via the details returned by get_compose or by calling
        # the API path directly to retrieve the deployment list
        endpoint = f"compose.deployments?composeId={compose_id}"
        deployments = client._request("GET", endpoint)

        print("\nRecent Deployments:")
        for dep in deployments[:5]:  # Only show the 5 most recent deployments
            print(f"- ID: {dep.get('deploymentId')}")
            print(f"  Status: {dep.get('status')}")
            print(f"  Created: {dep.get('createdAt')}")
            if dep.get("log"):
                print(f"  Log Snippet: {dep.get('log')[:200]}...")
            print("-" * 20)

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    compose_id = sys.argv[1] if len(sys.argv) > 1 else None
    check_deployments(compose_id)
