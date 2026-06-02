"""AC8.13.73 AC8.13.74: VPS host hygiene is local and credential-free."""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def hygiene_module():
    return importlib.import_module("tools._lib.dev.vps_host_hygiene")


def test_AC8_13_73_hygiene_script_prunes_generic_host_garbage() -> None:
    hygiene = hygiene_module()

    script = hygiene.build_hygiene_script(
        dry_run=True,
        container_prune_until="24h",
        builder_prune_until="24h",
        image_prune_until="168h",
        network_prune_until="168h",
        journal_vacuum_time="14d",
        journal_vacuum_size="1G",
        docker_log_truncate_size_mib=100,
        disk_warning_percent=85,
        disk_error_percent=95,
    )

    assert "[dry-run] docker container prune -f --filter until=24h" in script
    assert "[dry-run] docker builder prune -af --filter until=24h" in script
    assert "[dry-run] docker image prune -af --filter until=168h" in script
    assert "[dry-run] docker network prune -f --filter until=168h" in script
    assert "[dry-run] journalctl --vacuum-time=14d --vacuum-size=1G" in script
    assert "DOCKER_LOG_TRUNCATE_SIZE_MIB='100'" in script
    assert "DISK_WARNING_PERCENT='85'" in script
    assert "DISK_ERROR_PERCENT='95'" in script
    assert "DOKPLOY" not in script
    assert "GITHUB" not in script
    assert "VPS_SSH_KEY" not in script


def test_AC8_13_73_hygiene_script_runs_real_prune_commands_without_credentials() -> None:
    hygiene = hygiene_module()

    script = hygiene.build_hygiene_script(
        dry_run=False,
        container_prune_until="48h",
        builder_prune_until="72h",
        image_prune_until="240h",
        network_prune_until="240h",
        journal_vacuum_time="30d",
        journal_vacuum_size="512M",
        docker_log_truncate_size_mib=50,
        disk_warning_percent=80,
        disk_error_percent=90,
    )

    assert 'docker container prune -f --filter "until=48h"' in script
    assert 'docker builder prune -af --filter "until=72h"' in script
    assert 'docker image prune -af --filter "until=240h"' in script
    assert 'docker network prune -f --filter "until=240h"' in script
    assert 'journalctl --vacuum-time="30d" --vacuum-size="512M"' in script
    assert ': > "$log_path"' in script
    assert "[dry-run]" not in script
    assert "DOKPLOY" not in script
    assert "GITHUB" not in script


def test_AC8_13_73_hygiene_main_streams_output_and_returns_command_status(
    monkeypatch,
    capsys,
) -> None:
    hygiene = hygiene_module()
    captured_scripts: list[str | None] = []

    def fake_run_command(cmd, *, input_text=None, check=True):
        captured_scripts.append(input_text)
        return subprocess.CompletedProcess(cmd, 7, stdout="out\n", stderr="err\n")

    monkeypatch.setattr(hygiene, "run_command", fake_run_command)

    assert hygiene.main(["--dry-run", "--disk-error-percent", "99"]) == 7

    captured = capsys.readouterr()
    assert "out\n" in captured.out
    assert "err\n" in captured.err
    assert captured_scripts and "DISK_ERROR_PERCENT='99'" in captured_scripts[0]


def test_AC8_13_73_systemd_timer_installs_local_hygiene_only() -> None:
    service = (ROOT / "deploy/systemd/finance-report-vps-hygiene.service").read_text()
    timer = (ROOT / "deploy/systemd/finance-report-vps-hygiene.timer").read_text()

    assert "ExecStart=/usr/local/bin/finance-report-vps-hygiene" in service
    assert "OnCalendar=*-*-* 03,09,15,21:17:00" in timer
    assert "WantedBy=timers.target" in timer
    assert "DOKPLOY" not in service
    assert "GITHUB" not in service
    assert "VPS_SSH_KEY" not in service


def test_AC8_13_74_pr_preview_cleanup_workflow_has_no_host_hygiene() -> None:
    workflow = (ROOT / ".github/workflows/pr-preview-cleanup.yml").read_text()

    assert "docker container prune" not in workflow
    assert "docker builder prune" not in workflow
    assert "docker image prune" not in workflow
    assert "journal-vacuum" not in workflow
    assert "finance-report-vps-hygiene" not in workflow
