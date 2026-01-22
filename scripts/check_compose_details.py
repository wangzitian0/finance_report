"""
Inspect full compose service details as JSON.

Usage:
    python scripts/check_compose_details.py [compose_id]

Environment Variables:
    COMPOSE_ID: Default compose ID if not provided as argument
"""

import os
import sys
import json
from libs.dokploy import get_dokploy


def check_compose_details(compose_id: str | None = None) -> None:
    """Print complete compose object to find deployment information."""
    client = get_dokploy()

    # Use provided ID, environment variable, or default
    if not compose_id:
        compose_id = os.getenv("COMPOSE_ID", "A6V-hbJlgHMwgPDoTDnhH")

    try:
        compose = client.get_compose(compose_id)
        # Print the complete compose object to find deployment information
        print(json.dumps(compose, indent=2))
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    compose_id = sys.argv[1] if len(sys.argv) > 1 else None
    check_compose_details(compose_id)
