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


def ssh_command(
    host: str, user: str, ssh_key: str | None, remote_command: str
) -> list[str]:
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


def list_remote_preview_resources(
    host: str, user: str, ssh_key: str | None
) -> dict[int, PreviewResource]:
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
    prune_stopped_containers: bool = True,
    prune_networks: bool = True,
    vacuum_journal: bool = True,
    builder_prune_until: str,
    image_prune_until: str,
    container_prune_until: str = "24h",
    network_prune_until: str = "168h",
    journal_vacuum_time: str = "14d",
    journal_vacuum_size: str = "1G",
    docker_log_truncate_size_mib: int = 100,
    disk_warning_percent: int = 85,
    disk_error_percent: int = 95,
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
        f"DOCKER_LOG_TRUNCATE_SIZE_MIB='{docker_log_truncate_size_mib}'",
        f"DISK_WARNING_PERCENT='{disk_warning_percent}'",
        f"DISK_ERROR_PERCENT='{disk_error_percent}'",
        'DISK_PATHS="/"',
        'if [ -d /data ]; then DISK_PATHS="$DISK_PATHS /data"; fi',
        'echo "Disk usage before cleanup:"',
        "df -h $DISK_PATHS",
        'echo "Docker usage before cleanup:"',
        "docker system df -v || docker system df",
        'echo "Stale PR previews: ${PRS:-none}"',
        'echo "Compose projects: ${PROJECTS:-none}"',
        "for pr in $PRS; do",
        '  echo "Cleaning stale PR preview #${pr}"',
        (
            '  docker ps -a --format "{{.Names}}" | grep -E '
            '"^finance-report-(backend|frontend|db|minio)-pr-${pr}$"'
            f" | xargs -r {mode} docker rm -f"
        ),
        "done",
        "for project in $PROJECTS; do",
        '  echo "Cleaning compose volumes for ${project}"',
        (
            '  docker volume ls --format "{{.Name}}" | grep -E "^${project}_"'
            f" | xargs -r {mode} docker volume rm"
        ),
        "done",
    ]

    if docker_log_truncate_size_mib > 0:
        lines.extend(
            [
                'echo "Checking PR preview Docker log sizes"',
                (
                    "docker ps -a --format '{{.Names}}' | grep -E "
                    '"^finance-report-(backend|frontend|db|minio)-pr-[0-9]+$"'
                    " | while read -r container; do"
                ),
                "  log_path=$(docker inspect -f '{{.LogPath}}' \"$container\" 2>/dev/null || true)",
                (
                    '  if [ -z "$log_path" ] || [ "$log_path" = "<no value>" ] '
                    '|| [ ! -f "$log_path" ]; then'
                ),
                "    continue",
                "  fi",
                "  size_mib=$(du -m \"$log_path\" | awk '{print $1}')",
                '  if [ "$size_mib" -gt "$DOCKER_LOG_TRUNCATE_SIZE_MIB" ]; then',
                '    echo "Truncating oversized Docker log for ${container}: ${size_mib}MiB"',
                (
                    "    " + mode + ' sh -c \': > "$1"\' sh "$log_path"'
                    if dry_run
                    else '    : > "$log_path"'
                ),
                "  fi",
                "done",
            ]
        )

    if prune_stopped_containers:
        if dry_run:
            lines.append(
                f'echo "[dry-run] docker container prune -f --filter until={container_prune_until}"'
            )
        else:
            lines.append(
                f'docker container prune -f --filter "until={container_prune_until}"'
            )

    if prune_build_cache:
        if dry_run:
            lines.append(
                f'echo "[dry-run] docker builder prune -af --filter until={builder_prune_until}"'
            )
        else:
            lines.append(
                f'docker builder prune -af --filter "until={builder_prune_until}"'
            )

    if prune_images:
        if dry_run:
            lines.append(
                f'echo "[dry-run] docker image prune -af --filter until={image_prune_until}"'
            )
        else:
            lines.append(f'docker image prune -af --filter "until={image_prune_until}"')

    if prune_networks:
        if dry_run:
            lines.append(
                f'echo "[dry-run] docker network prune -f --filter until={network_prune_until}"'
            )
        else:
            lines.append(
                f'docker network prune -f --filter "until={network_prune_until}"'
            )

    if vacuum_journal:
        if dry_run:
            lines.append(
                f'echo "[dry-run] journalctl --vacuum-time={journal_vacuum_time} '
                f'--vacuum-size={journal_vacuum_size}"'
            )
        else:
            lines.extend(
                [
                    "if command -v journalctl >/dev/null 2>&1; then",
                    (
                        f'  journalctl --vacuum-time="{journal_vacuum_time}" '
                        f'--vacuum-size="{journal_vacuum_size}" '
                        '|| echo "::warning::journalctl vacuum failed; continuing"'
                    ),
                    "else",
                    '  echo "::warning::journalctl is unavailable; skipping systemd journal vacuum"',
                    "fi",
                ]
            )

    lines.extend(
        [
            'echo "Disk usage after cleanup:"',
            "df -h $DISK_PATHS",
            'echo "Docker usage after cleanup:"',
            "docker system df -v || docker system df",
            'df -P $DISK_PATHS | awk -v warn="$DISK_WARNING_PERCENT" '
            '-v err="$DISK_ERROR_PERCENT" \''
            'NR > 1 { usage=$5; gsub(/%/, "", usage); '
            "if (usage + 0 >= err + 0) { "
            'printf "::error::Disk usage for %s is %s%%; critical threshold is %s%%\\n", '
            "$6, usage, err; failed=1 } "
            "else if (usage + 0 >= warn + 0) { "
            'printf "::warning::Disk usage for %s is %s%%; warning threshold is %s%%\\n", '
            "$6, usage, warn } } "
            "END { exit failed ? 1 : 0 }'",
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
        prune_stopped_containers=not getattr(
            args, "no_prune_stopped_containers", False
        ),
        prune_networks=not getattr(args, "no_prune_networks", False),
        vacuum_journal=not getattr(args, "no_vacuum_journal", False),
        builder_prune_until=args.builder_prune_until,
        image_prune_until=args.image_prune_until,
        container_prune_until=getattr(args, "container_prune_until", "24h"),
        network_prune_until=getattr(args, "network_prune_until", "168h"),
        journal_vacuum_time=getattr(args, "journal_vacuum_time", "14d"),
        journal_vacuum_size=getattr(args, "journal_vacuum_size", "1G"),
        docker_log_truncate_size_mib=getattr(args, "docker_log_truncate_size_mib", 100),
        disk_warning_percent=getattr(args, "disk_warning_percent", 85),
        disk_error_percent=getattr(args, "disk_error_percent", 95),
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
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print cleanup actions without deleting resources",
    )
    parser.add_argument(
        "--no-prune-build-cache",
        action="store_true",
        help="Do not prune old Docker build cache",
    )
    parser.add_argument(
        "--no-prune-images",
        action="store_true",
        help="Do not prune old unused Docker images",
    )
    parser.add_argument(
        "--no-prune-stopped-containers",
        action="store_true",
        help="Do not prune old stopped Docker containers",
    )
    parser.add_argument(
        "--no-prune-networks",
        action="store_true",
        help="Do not prune old unused Docker networks",
    )
    parser.add_argument(
        "--no-vacuum-journal",
        action="store_true",
        help="Do not vacuum systemd journal logs",
    )
    parser.add_argument(
        "--builder-prune-until", default="24h", help="Docker builder prune age filter"
    )
    parser.add_argument(
        "--image-prune-until", default="168h", help="Docker image prune age filter"
    )
    parser.add_argument(
        "--container-prune-until",
        default="24h",
        help="Stopped container prune age filter",
    )
    parser.add_argument(
        "--network-prune-until", default="168h", help="Docker network prune age filter"
    )
    parser.add_argument(
        "--journal-vacuum-time", default="14d", help="systemd journal retention time"
    )
    parser.add_argument(
        "--journal-vacuum-size",
        default="1G",
        help="systemd journal maximum retained size",
    )
    parser.add_argument(
        "--docker-log-truncate-size-mib",
        type=int,
        default=100,
        help="Truncate PR preview Docker json logs larger than this size; set 0 to disable",
    )
    parser.add_argument(
        "--disk-warning-percent",
        type=int,
        default=85,
        help="Warn when root/data disk usage exceeds this",
    )
    parser.add_argument(
        "--disk-error-percent",
        type=int,
        default=95,
        help="Fail when root/data disk usage exceeds this",
    )
    return cleanup(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
