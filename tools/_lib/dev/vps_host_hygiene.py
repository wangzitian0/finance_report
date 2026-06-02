#!/usr/bin/env python3
"""Run generic VPS host hygiene without Dokploy or GitHub credentials."""

from __future__ import annotations

import argparse
import subprocess
import sys


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


def build_hygiene_script(
    *,
    dry_run: bool,
    container_prune_until: str,
    builder_prune_until: str,
    image_prune_until: str,
    network_prune_until: str,
    journal_vacuum_time: str,
    journal_vacuum_size: str,
    docker_log_truncate_size_mib: int,
    disk_warning_percent: int,
    disk_error_percent: int,
) -> str:
    lines = [
        "set -eu",
        f"DOCKER_LOG_TRUNCATE_SIZE_MIB='{docker_log_truncate_size_mib}'",
        f"DISK_WARNING_PERCENT='{disk_warning_percent}'",
        f"DISK_ERROR_PERCENT='{disk_error_percent}'",
        'DISK_PATHS="/"',
        'if [ -d /data ]; then DISK_PATHS="$DISK_PATHS /data"; fi',
        'echo "Disk usage before host hygiene:"',
        "df -h $DISK_PATHS",
        'echo "Docker usage before host hygiene:"',
        "if command -v docker >/dev/null 2>&1; then",
        '  docker system df -v || docker system df || echo "::warning::docker system df unavailable"',
        "else",
        '  echo "::warning::docker unavailable; skipping Docker usage summary"',
        "fi",
    ]

    if docker_log_truncate_size_mib > 0:
        lines.extend(
            [
                'echo "Checking Docker json log sizes"',
                "if [ -d /var/lib/docker/containers ]; then",
                "  find /var/lib/docker/containers -name '*-json.log' -type f "
                "| while read -r log_path; do",
                "  size_mib=$(du -m \"$log_path\" | awk '{print $1}')",
                '  if [ "$size_mib" -gt "$DOCKER_LOG_TRUNCATE_SIZE_MIB" ]; then',
                '    echo "Truncating oversized Docker log: ${size_mib}MiB ${log_path}"',
                (
                    '    echo "[dry-run] truncate Docker json log ${log_path}"'
                    if dry_run
                    else '    : > "$log_path"'
                ),
                "  fi",
                "done",
                "else",
                '  echo "::warning::Docker container log directory unavailable; skipping log truncation"',
                "fi",
            ]
        )

    prune_commands = [
        (
            f"docker container prune -f --filter until={container_prune_until}",
            f'docker container prune -f --filter "until={container_prune_until}"',
        ),
        (
            f"docker builder prune -af --filter until={builder_prune_until}",
            f'docker builder prune -af --filter "until={builder_prune_until}"',
        ),
        (
            f"docker image prune -af --filter until={image_prune_until}",
            f'docker image prune -af --filter "until={image_prune_until}"',
        ),
        (
            f"docker network prune -f --filter until={network_prune_until}",
            f'docker network prune -f --filter "until={network_prune_until}"',
        ),
        (
            f"journalctl --vacuum-time={journal_vacuum_time} --vacuum-size={journal_vacuum_size}",
            f'journalctl --vacuum-time="{journal_vacuum_time}" --vacuum-size="{journal_vacuum_size}"',
        ),
    ]
    for dry_run_command, command in prune_commands:
        if dry_run:
            lines.append(f'echo "[dry-run] {dry_run_command}"')
        elif command.startswith("journalctl "):
            lines.extend(
                [
                    "if command -v journalctl >/dev/null 2>&1; then",
                    f'  {command} || echo "::warning::journalctl vacuum failed; continuing"',
                    "else",
                    '  echo "::warning::journalctl unavailable; skipping journal vacuum"',
                    "fi",
                ]
            )
        else:
            lines.append(command)

    lines.extend(
        [
            'echo "Disk usage after host hygiene:"',
        "df -h $DISK_PATHS",
        'echo "Docker usage after host hygiene:"',
        "if command -v docker >/dev/null 2>&1; then",
        '  docker system df -v || docker system df || echo "::warning::docker system df unavailable"',
        "else",
        '  echo "::warning::docker unavailable; skipping Docker usage summary"',
        "fi",
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--container-prune-until", default="24h")
    parser.add_argument("--builder-prune-until", default="24h")
    parser.add_argument("--image-prune-until", default="168h")
    parser.add_argument("--network-prune-until", default="168h")
    parser.add_argument("--journal-vacuum-time", default="14d")
    parser.add_argument("--journal-vacuum-size", default="1G")
    parser.add_argument("--docker-log-truncate-size-mib", type=int, default=100)
    parser.add_argument("--disk-warning-percent", type=int, default=85)
    parser.add_argument("--disk-error-percent", type=int, default=95)
    args = parser.parse_args(argv)

    script = build_hygiene_script(
        dry_run=args.dry_run,
        container_prune_until=args.container_prune_until,
        builder_prune_until=args.builder_prune_until,
        image_prune_until=args.image_prune_until,
        network_prune_until=args.network_prune_until,
        journal_vacuum_time=args.journal_vacuum_time,
        journal_vacuum_size=args.journal_vacuum_size,
        docker_log_truncate_size_mib=args.docker_log_truncate_size_mib,
        disk_warning_percent=args.disk_warning_percent,
        disk_error_percent=args.disk_error_percent,
    )
    result = run_command(["sh", "-s"], input_text=script, check=False)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
