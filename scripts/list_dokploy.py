"""
List all Dokploy projects, environments, and compose services.

Usage:
    python scripts/list_dokploy.py
"""

from libs.dokploy import get_dokploy


def check_all_services() -> None:
    """List all projects, environments, and compose services."""
    client = get_dokploy()
    projects = client.list_projects()

    for project in projects:
        print(f"Project: {project.get('name')} ({project.get('projectId')})")
        for env in project.get("environments", []):
            print(f"  Environment: {env.get('name')} ({env.get('environmentId')})")
            for compose in env.get("compose", []):
                print(
                    f"    Compose: {compose.get('name')} ({compose.get('composeId')})"
                )


if __name__ == "__main__":
    check_all_services()
