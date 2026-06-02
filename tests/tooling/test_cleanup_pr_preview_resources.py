"""AC8.13.38: Scheduled PR preview cleanup coverage."""

import argparse
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools._lib.dev import cleanup_pr_preview_resources as cleanup  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def test_AC8_13_38_run_command_uses_checked_text_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(*_args: object, **kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(stdout="ok\n", stderr="", returncode=0)

    monkeypatch.setattr(cleanup.subprocess, "run", fake_run)

    result = cleanup.run_command(
        ["gh", "pr", "list"], input_text="payload", check=False
    )

    assert result.stdout == "ok\n"
    assert calls == [
        {
            "input": "payload",
            "capture_output": True,
            "text": True,
            "check": False,
        }
    ]


def test_AC8_13_38_parse_and_list_open_pr_numbers_uses_github_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def run_command_stub(
        cmd: list[str],
        *,
        input_text: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="\n498\n\n554\n", stderr="")

    monkeypatch.setattr(cleanup, "run_command", run_command_stub)

    assert cleanup.parse_open_pr_numbers("\n434\n\n 498 \n") == {434, 498}
    assert cleanup.list_open_pr_numbers() == {498, 554}
    assert commands == [
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
    ]


def test_AC8_13_38_ssh_command_supports_optional_identity_file() -> None:
    assert cleanup.ssh_command("cloud.zitian.party", "root", None, "docker ps") == [
        "ssh",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "root@cloud.zitian.party",
        "docker ps",
    ]

    assert cleanup.ssh_command(
        "cloud.zitian.party",
        "deploy",
        "/tmp/key",
        "docker ps",
    ) == [
        "ssh",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-i",
        "/tmp/key",
        "deploy@cloud.zitian.party",
        "docker ps",
    ]


def test_AC8_13_38_parse_preview_resources_groups_by_pr() -> None:
    output = "\n".join(
        [
            "finance-report-backend-pr-434\tcompose-old",
            "finance-report-frontend-pr-434\tcompose-old",
            "finance-report-db-pr-498\tcompose-open",
            "finance-report-minio-pr-499\t<no value>",
            "unrelated\tcompose-other",
        ]
    )

    resources = cleanup.parse_preview_resources(output)

    assert sorted(resources) == [434, 498, 499]
    assert resources[434].containers == {
        "finance-report-backend-pr-434",
        "finance-report-frontend-pr-434",
    }
    assert resources[434].compose_projects == {"compose-old"}
    assert resources[499].compose_projects == set()


def test_AC8_13_38_list_remote_preview_resources_uses_safe_ssh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def run_command_stub(
        cmd: list[str],
        *,
        input_text: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        observed["cmd"] = cmd
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout="finance-report-minio-pr-434\t<no value>\n",
            stderr="",
        )

    monkeypatch.setattr(cleanup, "run_command", run_command_stub)

    resources = cleanup.list_remote_preview_resources(
        "cloud.zitian.party",
        "root",
        "/tmp/key",
    )

    assert sorted(resources) == [434]
    assert resources[434].containers == {"finance-report-minio-pr-434"}
    assert resources[434].compose_projects == set()
    assert observed["cmd"] == cleanup.ssh_command(
        "cloud.zitian.party",
        "root",
        "/tmp/key",
        "docker ps -a --format '{{.Names}}\\t{{.Label \"com.docker.compose.project\"}}'",
    )


def test_AC8_13_38_select_stale_resources_preserves_open_prs() -> None:
    resources = cleanup.parse_preview_resources(
        "finance-report-backend-pr-434\tcompose-old\n"
        "finance-report-backend-pr-498\tcompose-open\n"
    )

    stale = cleanup.select_stale_resources(resources, {498})

    assert sorted(stale) == [434]


def test_AC8_13_38_remote_cleanup_script_targets_only_stale_projects() -> None:
    resources = cleanup.parse_preview_resources(
        "finance-report-backend-pr-434\tcompose-old\n"
        "finance-report-frontend-pr-434\tbad project name\n"
        "finance-report-backend-pr-498\tcompose-open\n"
    )
    stale = cleanup.select_stale_resources(resources, {498})

    script = cleanup.build_remote_cleanup_script(
        stale,
        dry_run=True,
        prune_build_cache=True,
        prune_images=True,
        builder_prune_until="24h",
        image_prune_until="168h",
    )

    assert "PRS='434'" in script
    assert "PROJECTS='compose-old'" in script
    assert "pr-${pr}" in script
    assert "grep -E '\"" not in script
    assert "compose-open" not in script
    assert "bad project name" not in script
    assert "[dry-run] docker container prune -f --filter until=24h" in script
    assert "[dry-run] docker builder prune -af --filter until=24h" in script
    assert "[dry-run] docker image prune -af --filter until=168h" in script
    assert "[dry-run] docker network prune -f --filter until=168h" in script
    assert "[dry-run] journalctl --vacuum-time=14d --vacuum-size=1G" in script
    assert "DOCKER_LOG_TRUNCATE_SIZE_MIB='100'" in script
    assert "DISK_WARNING_PERCENT='85'" in script
    assert "DISK_ERROR_PERCENT='95'" in script
    assert "docker system df -v || docker system df" in script
    assert "docker system prune" not in script
    assert "docker volume prune" not in script


def test_AC8_13_38_remote_cleanup_script_can_run_real_prune_commands() -> None:
    stale = cleanup.parse_preview_resources(
        "finance-report-backend-pr-434\tcompose-old\n"
        "finance-report-frontend-pr-435\tcompose;unsafe\n"
    )

    script = cleanup.build_remote_cleanup_script(
        stale,
        dry_run=False,
        prune_build_cache=True,
        prune_images=True,
        prune_stopped_containers=True,
        prune_networks=True,
        vacuum_journal=True,
        builder_prune_until="48h",
        image_prune_until="240h",
        container_prune_until="36h",
        network_prune_until="336h",
        journal_vacuum_time="21d",
        journal_vacuum_size="2G",
        docker_log_truncate_size_mib=64,
        disk_warning_percent=80,
        disk_error_percent=92,
    )

    assert "PROJECTS='compose-old'" in script
    assert "compose;unsafe" not in script
    assert "[dry-run]" not in script
    assert 'docker container prune -f --filter "until=36h"' in script
    assert 'docker builder prune -af --filter "until=48h"' in script
    assert 'docker image prune -af --filter "until=240h"' in script
    assert 'docker network prune -f --filter "until=336h"' in script
    assert 'journalctl --vacuum-time="21d" --vacuum-size="2G"' in script
    assert "DOCKER_LOG_TRUNCATE_SIZE_MIB='64'" in script
    assert "DISK_WARNING_PERCENT='80'" in script
    assert "DISK_ERROR_PERCENT='92'" in script
    assert "docker inspect -f '{{.LogPath}}'" in script
    assert ': > "$log_path"' in script
    assert "docker system prune" not in script
    assert "docker volume prune" not in script


def test_AC8_13_38_remote_cleanup_script_can_skip_optional_prunes() -> None:
    script = cleanup.build_remote_cleanup_script(
        {},
        dry_run=False,
        prune_build_cache=False,
        prune_images=False,
        prune_stopped_containers=False,
        prune_networks=False,
        vacuum_journal=False,
        builder_prune_until="48h",
        image_prune_until="240h",
        docker_log_truncate_size_mib=0,
    )

    assert "PRS=''" in script
    assert "PROJECTS=''" in script
    assert "docker container prune" not in script
    assert "docker builder prune" not in script
    assert "docker image prune" not in script
    assert "docker network prune" not in script
    assert "journalctl" not in script
    assert "docker inspect -f '{{.LogPath}}'" not in script
    assert "docker system df" in script
    assert "docker system prune" not in script
    assert "docker volume prune" not in script


def test_AC8_13_38_cleanup_orchestrates_stale_remote_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    commands: list[tuple[list[str], str | None, bool]] = []

    def run_command_stub(
        cmd: list[str],
        *,
        input_text: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        commands.append((cmd, input_text, check))
        if cmd[:3] == ["gh", "pr", "list"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="498\n", stderr="")
        if "docker ps -a" in cmd[-1]:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=(
                    "finance-report-backend-pr-434\tcompose-old\n"
                    "finance-report-backend-pr-498\tcompose-open\n"
                ),
                stderr="",
            )
        return subprocess.CompletedProcess(
            cmd,
            7,
            stdout="remote stdout\n",
            stderr="remote stderr\n",
        )

    monkeypatch.setattr(cleanup, "run_command", run_command_stub)
    args = argparse.Namespace(
        host="cloud.zitian.party",
        user="root",
        ssh_key="/tmp/key",
        dry_run=True,
        no_prune_build_cache=False,
        no_prune_images=True,
        no_prune_stopped_containers=False,
        no_prune_networks=False,
        no_vacuum_journal=False,
        builder_prune_until="24h",
        image_prune_until="168h",
        container_prune_until="24h",
        network_prune_until="168h",
        journal_vacuum_time="14d",
        journal_vacuum_size="1G",
        docker_log_truncate_size_mib=100,
        disk_warning_percent=85,
        disk_error_percent=95,
    )

    assert cleanup.cleanup(args) == 7

    out = capsys.readouterr()
    assert "Open PRs: [498]" in out.out
    assert "Preview PRs on VPS: [434, 498]" in out.out
    assert "Stale preview PRs: [434]" in out.out
    assert "remote stdout" in out.out
    assert "remote stderr" in out.err
    assert commands[-1][2] is False
    assert "PRS='434'" in str(commands[-1][1])
    assert "docker image prune" not in str(commands[-1][1])


def test_AC8_13_38_main_parses_cleanup_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def cleanup_stub(args: argparse.Namespace) -> int:
        observed["args"] = args
        return 3

    monkeypatch.setattr(cleanup, "cleanup", cleanup_stub)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cleanup_pr_preview_resources.py",
            "--host",
            "cloud.zitian.party",
            "--user",
            "deploy",
            "--ssh-key",
            "/tmp/key",
            "--dry-run",
            "--no-prune-build-cache",
            "--no-prune-images",
            "--no-prune-stopped-containers",
            "--no-prune-networks",
            "--no-vacuum-journal",
            "--builder-prune-until",
            "72h",
            "--image-prune-until",
            "360h",
            "--container-prune-until",
            "96h",
            "--network-prune-until",
            "720h",
            "--journal-vacuum-time",
            "30d",
            "--journal-vacuum-size",
            "512M",
            "--docker-log-truncate-size-mib",
            "32",
            "--disk-warning-percent",
            "70",
            "--disk-error-percent",
            "88",
        ],
    )

    assert cleanup.main() == 3
    args = observed["args"]
    assert isinstance(args, argparse.Namespace)
    assert args.host == "cloud.zitian.party"
    assert args.user == "deploy"
    assert args.ssh_key == "/tmp/key"
    assert args.dry_run is True
    assert args.no_prune_build_cache is True
    assert args.no_prune_images is True
    assert args.no_prune_stopped_containers is True
    assert args.no_prune_networks is True
    assert args.no_vacuum_journal is True
    assert args.builder_prune_until == "72h"
    assert args.image_prune_until == "360h"
    assert args.container_prune_until == "96h"
    assert args.network_prune_until == "720h"
    assert args.journal_vacuum_time == "30d"
    assert args.journal_vacuum_size == "512M"
    assert args.docker_log_truncate_size_mib == 32
    assert args.disk_warning_percent == 70
    assert args.disk_error_percent == 88


def test_AC8_13_38_workflow_runs_on_schedule_and_manual_dispatch() -> None:
    workflow = (ROOT / ".github/workflows/pr-preview-cleanup.yml").read_text()

    assert 'cron: "37 */6 * * *"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "tools/cleanup_pr_preview_resources.py" in workflow
    assert "VPS_SSH_KEY" in workflow
    missing_key_block = workflow.split('if [ -z "$VPS_SSH_KEY" ]; then', 1)[1].split(
        "fi",
        1,
    )[0]
    assert "::error::VPS_SSH_KEY is required" in missing_key_block
    assert "exit 1" in missing_key_block


def test_AC8_13_38_pr_preview_compose_caps_docker_json_logs() -> None:
    compose = (ROOT / "docker-compose.yml").read_text()

    assert "x-json-logging: &json-logging" in compose
    assert "driver: json-file" in compose
    assert 'max-size: "${DOCKER_LOG_MAX_SIZE:-10m}"' in compose
    assert 'max-file: "${DOCKER_LOG_MAX_FILE:-3}"' in compose

    lines = compose.splitlines()
    for service in ["postgres", "minio", "minio-init", "backend", "frontend"]:
        start = lines.index(f"  {service}:")
        block_lines: list[str] = []
        for line in lines[start + 1 :]:
            if line.startswith("  ") and not line.startswith("    "):
                break
            block_lines.append(line)
        service_block = "\n".join(block_lines)
        assert "logging: *json-logging" in service_block
