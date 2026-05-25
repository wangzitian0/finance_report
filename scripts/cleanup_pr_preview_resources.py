#!/usr/bin/env python3
"""Clean stale PR preview resources from the VPS.

The PR close workflow is the primary cleanup path. This script is the scheduled
fallback for missed close events, failed Dokploy deletes, or skipped SSH volume
cleanup.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field

PREVIEW_CONTAINER_RE = re.compile(
    r"^finance-report-(?:backend|frontend|db|minio)-pr-(?P<pr>\d+)$"
)
SAFE_COMPOSE_PROJECT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass
class PreviewResource:
    pr_number: int
    containers: set[str] = field(default_factory=set)
    compose_projects: set[str] = field(default_factory=set)


def run_command(
    cmd: list[str],
    *,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        input=input_text,
        capture_output=True,
        text=True,
        check=check,
    )


def ssh_command(host: str, user: str, ssh_key: str | None, remote_command: str) -> list[str]:
    cmd = ["ssh", "-o", "StrictHostKeyChecking=accept-new"]
    if ssh_key:
        cmd.extend(["-i", ssh_key])
    cmd.append(f"{user}@{host}")
    cmd.append(remote_command)
    return cmd


def parse_open_pr_numbers(output: str) -> set[int]:
    pr_numbers: set[int] = set()
    for line in output.splitlines():
        stripped = line.strip()
        if stripped:
            pr_numbers.add(int(stripped))
    return pr_numbers


def list_open_pr_numbers() -> set[int]:
    result = run_command(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "open",
            "--limit",
            "1000",
            "--json",
            "number",
            "--jq",
            ".[].number",
        ]
    )
    return parse_open_pr_numbers(result.stdout)


def parse_preview_resources(output: str) -> dict[int, PreviewResource]:
    resources: dict[int, PreviewResource] = {}
    for line in output.splitlines():
        name, _, project = line.partition("\t")
        match = PREVIEW_CONTAINER_RE.match(name.strip())
        if not match:
            continue

        pr_number = int(match.group("pr"))
        resource = resources.setdefault(pr_number, PreviewResource(pr_number=pr_number))
        resource.containers.add(name.strip())

        project = project.strip()
        if project and project != "<no value>":
            resource.compose_projects.add(project)

    return resources


def list_remote_preview_resources(host: str, user: str, ssh_key: str | None) -> dict[int, PreviewResource]:
    result = run_command(
        ssh_command(
            host,
            user,
            ssh_key,
            "docker ps -a --format '{{.Names}}\\t{{.Label \"com.docker.compose.project\"}}'",
        )
    )
    return parse_preview_resources(result.stdout)


def select_stale_resources(
    resources: dict[int, PreviewResource],
    open_pr_numbers: set[int],
) -> dict[int, PreviewResource]:
    return {
        pr_number: resource
        for pr_number, resource in sorted(resources.items())
        if pr_number not in open_pr_numbers
    }


def _shell_words(values: list[int] | list[str]) -> str:
    return " ".join(str(value) for value in values)


def build_remote_cleanup_script(
    stale_resources: dict[int, PreviewResource],
    *,
    dry_run: bool,
    prune_build_cache: bool,
    prune_images: bool,
    builder_prune_until: str,
    image_prune_until: str,
) -> str:
    pr_numbers = sorted(stale_resources)
    projects = sorted(
        {
            project
            for resource in stale_resources.values()
            for project in resource.compose_projects
            if SAFE_COMPOSE_PROJECT_RE.match(project)
        }
    )

    mode = "echo [dry-run]" if dry_run else ""
    lines = [
        "set -eu",
        f"PRS='{_shell_words(pr_numbers)}'",
        f"PROJECTS='{_shell_words(projects)}'",
        'echo "Stale PR previews: ${PRS:-none}"',
        'echo "Compose projects: ${PROJECTS:-none}"',
        'for pr in $PRS; do',
        '  echo "Cleaning stale PR preview #${pr}"',
        (
            '  docker ps -a --format "{{.Names}}" | grep -E '
            '\'"^finance-report-(backend|frontend|db|minio)-pr-${pr}$"\''
            f' | xargs -r {mode} docker rm -f'
        ),
        "done",
        'for project in $PROJECTS; do',
        '  echo "Cleaning compose volumes for ${project}"',
        (
            '  docker volume ls --format "{{.Name}}" | grep -E "^${project}_"'
            f' | xargs -r {mode} docker volume rm'
        ),
        "done",
    ]

    if prune_build_cache:
        if dry_run:
            lines.append(f'echo "[dry-run] docker builder prune -af --filter until={builder_prune_until}"')
        else:
            lines.append(f'docker builder prune -af --filter "until={builder_prune_until}"')

    if prune_images:
        if dry_run:
            lines.append(f'echo "[dry-run] docker image prune -af --filter until={image_prune_until}"')
        else:
            lines.append(f'docker image prune -af --filter "until={image_prune_until}"')

    lines.extend(
        [
            "df -h / /data 2>/dev/null || df -h /",
            "docker system df",
        ]
    )
    return "\n".join(lines) + "\n"


def cleanup(args: argparse.Namespace) -> int:
    open_prs = list_open_pr_numbers()
    resources = list_remote_preview_resources(args.host, args.user, args.ssh_key)
    stale_resources = select_stale_resources(resources, open_prs)

    print(f"Open PRs: {sorted(open_prs)}")
    print(f"Preview PRs on VPS: {sorted(resources)}")
    print(f"Stale preview PRs: {sorted(stale_resources)}")

    script = build_remote_cleanup_script(
        stale_resources,
        dry_run=args.dry_run,
        prune_build_cache=not args.no_prune_build_cache,
        prune_images=not args.no_prune_images,
        builder_prune_until=args.builder_prune_until,
        image_prune_until=args.image_prune_until,
    )

    result = run_command(
        ssh_command(args.host, args.user, args.ssh_key, "sh -s"),
        input_text=script,
        check=False,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)

    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="VPS host to clean")
    parser.add_argument("--user", default="root", help="SSH user")
    parser.add_argument("--ssh-key", help="Path to SSH private key")
    parser.add_argument("--dry-run", action="store_true", help="Print cleanup actions without deleting resources")
    parser.add_argument("--no-prune-build-cache", action="store_true", help="Do not prune old Docker build cache")
    parser.add_argument("--no-prune-images", action="store_true", help="Do not prune old unused Docker images")
    parser.add_argument("--builder-prune-until", default="24h", help="Docker builder prune age filter")
    parser.add_argument("--image-prune-until", default="168h", help="Docker image prune age filter")
    return cleanup(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
