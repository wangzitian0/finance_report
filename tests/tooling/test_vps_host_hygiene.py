"""AC8.13.73 AC8.13.74: VPS host hygiene is a Dokploy scheduled job."""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def hygiene_module():
    return importlib.import_module("tools._lib.dev.vps_host_hygiene")


def test_AC8_13_73_hygiene_script_prunes_generic_host_garbage_and_old_previews() -> (
    None
):
    hygiene = hygiene_module()

    script = hygiene.build_hygiene_script(
        dry_run=True,
        container_prune_until="72h",
        builder_prune_until="72h",
        image_prune_until="72h",
        network_prune_until="72h",
        journal_vacuum_time="3d",
        journal_vacuum_size="1G",
        docker_log_truncate_size_mib=100,
        disk_warning_percent=85,
        disk_error_percent=95,
        pr_preview_max_age_days=3,
        pr_preview_keep_recent=3,
    )

    assert "PR_PREVIEW_MAX_AGE_DAYS='3'" in script
    assert "PR_PREVIEW_KEEP_RECENT='3'" in script
    assert "CONTAINER_PRUNE_UNTIL='72h'" in script
    assert 'date -u -d "${PR_PREVIEW_MAX_AGE_DAYS} days ago" +%s' in script
    assert 'tail -n "$PR_PREVIEW_KEEP_RECENT"' in script
    assert "finance-report-(backend|frontend|db|minio)-pr-[0-9]+" in script
    assert "finance_report_pr_[0-9]+_" in script
    assert "[dry-run] docker rm -f ${container_name}" in script
    assert "[dry-run] docker volume rm ${volume_name}" in script
    assert "[dry-run] docker rm -f ${non_preview_container}" in script
    assert "docker container prune" not in script
    assert "[dry-run] docker builder prune -af --filter until=72h" in script
    assert "[dry-run] docker image prune -af --filter until=72h" in script
    assert "[dry-run] docker network prune -f --filter until=72h" in script
    assert "[dry-run] journalctl --vacuum-time=3d --vacuum-size=1G" in script
    assert "DOCKER_LOG_TRUNCATE_SIZE_MIB='100'" in script
    assert "DISK_WARNING_PERCENT='85'" in script
    assert "DISK_ERROR_PERCENT='95'" in script
    assert "GITHUB" not in script
    assert "VPS_SSH_KEY" not in script


def test_AC8_13_73_hygiene_script_runs_real_prune_commands_without_credentials() -> (
    None
):
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
        pr_preview_max_age_days=3,
        pr_preview_keep_recent=3,
    )

    assert "CONTAINER_PRUNE_UNTIL='48h'" in script
    assert 'date -u -d "${CONTAINER_PRUNE_UNTIL} ago" +%s' in script
    assert 'docker builder prune -af --filter "until=72h"' in script
    assert 'docker image prune -af --filter "until=240h"' in script
    assert 'docker network prune -f --filter "until=240h"' in script
    assert 'journalctl --vacuum-time="30d" --vacuum-size="512M"' in script
    assert ': > "$log_path"' in script
    assert 'docker rm -f "$container_name"' in script
    assert 'docker rm -f "$non_preview_container" || true' in script
    assert 'docker volume rm "$volume_name" || true' in script
    assert "docker container prune" not in script
    assert "[dry-run]" not in script
    assert "GITHUB" not in script


def test_AC8_13_73_hygiene_script_is_shell_parseable() -> None:
    hygiene = hygiene_module()

    script = hygiene.build_hygiene_script(
        dry_run=True,
        container_prune_until="72h",
        builder_prune_until="72h",
        image_prune_until="72h",
        network_prune_until="72h",
        journal_vacuum_time="3d",
        journal_vacuum_size="1G",
        docker_log_truncate_size_mib=100,
        disk_warning_percent=85,
        disk_error_percent=95,
        pr_preview_max_age_days=3,
        pr_preview_keep_recent=3,
    )

    result = subprocess.run(
        ["sh", "-n"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


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


def test_AC8_13_73_dokploy_schedule_payload_is_server_job_with_retention() -> None:
    hygiene = hygiene_module()

    script = hygiene.build_hygiene_script(
        dry_run=False,
        container_prune_until="72h",
        builder_prune_until="72h",
        image_prune_until="72h",
        network_prune_until="72h",
        journal_vacuum_time="3d",
        journal_vacuum_size="1G",
        docker_log_truncate_size_mib=100,
        disk_warning_percent=85,
        disk_error_percent=95,
        pr_preview_max_age_days=3,
        pr_preview_keep_recent=3,
    )
    payload = hygiene.build_schedule_payload(server_id="srv-1", script=script)

    assert payload["name"] == "finance-report-vps-host-hygiene"
    assert payload["cronExpression"] == "17 3,9,15,21 * * *"
    assert payload["scheduleType"] == "server"
    assert payload["shellType"] == "bash"
    assert payload["serverId"] == "srv-1"
    assert payload["enabled"] is True
    assert payload["timezone"] == "Asia/Singapore"
    assert payload["command"] == script
    assert payload["script"] == script
    assert "PR_PREVIEW_MAX_AGE_DAYS='3'" in str(payload["command"])
    assert "PR_PREVIEW_KEEP_RECENT='3'" in str(payload["command"])
    assert "VPS_SSH_KEY" not in json.dumps(payload)


def test_AC8_13_73_ensure_schedule_updates_existing_named_job(monkeypatch) -> None:
    hygiene = hygiene_module()
    calls: list[tuple[str, dict[str, object] | None]] = []

    def fake_api_call(config, method, endpoint, *, payload=None, expected_status=200):
        calls.append((endpoint, payload))
        if endpoint.startswith("schedule.list"):
            return json.dumps(
                {
                    "schedules": [
                        {
                            "name": "finance-report-vps-host-hygiene",
                            "scheduleId": "sch-1",
                        }
                    ]
                }
            )
        assert endpoint == "schedule.update"
        assert payload and payload["scheduleId"] == "sch-1"
        return json.dumps({"scheduleId": "sch-1"})

    monkeypatch.setattr(hygiene, "dokploy_api_call", fake_api_call)

    result = hygiene.ensure_dokploy_schedule(
        hygiene.DokployConfig("https://cloud.example/api", "secret"),
        server_id="srv-1",
        script="echo clean",
        name="finance-report-vps-host-hygiene",
        cron_expression="17 3,9,15,21 * * *",
        timezone="Asia/Singapore",
        enabled=True,
    )

    assert result == "sch-1"
    assert calls[0][0] == "schedule.list?id=srv-1&scheduleType=server"
    assert calls[1][0] == "schedule.update"


def test_AC8_13_73_ensure_schedule_creates_missing_named_job(monkeypatch) -> None:
    hygiene = hygiene_module()
    calls: list[str] = []

    def fake_api_call(config, method, endpoint, *, payload=None, expected_status=200):
        calls.append(endpoint)
        if endpoint.startswith("schedule.list"):
            return json.dumps({"schedules": []})
        assert endpoint == "schedule.create"
        assert payload and "scheduleId" not in payload
        return json.dumps({"scheduleId": "sch-new"})

    monkeypatch.setattr(hygiene, "dokploy_api_call", fake_api_call)

    result = hygiene.ensure_dokploy_schedule(
        hygiene.DokployConfig("https://cloud.example/api", "secret"),
        server_id="srv-1",
        script="echo clean",
        name="finance-report-vps-host-hygiene",
        cron_expression="17 3,9,15,21 * * *",
        timezone="Asia/Singapore",
        enabled=True,
    )

    assert result == "sch-new"
    assert calls == ["schedule.list?id=srv-1&scheduleType=server", "schedule.create"]


def test_AC8_13_74_pr_preview_cleanup_workflow_has_no_host_hygiene() -> None:
    workflow = (ROOT / ".github/workflows/pr-preview-cleanup.yml").read_text()

    assert "docker container prune" not in workflow
    assert "docker builder prune" not in workflow
    assert "docker image prune" not in workflow
    assert "journal-vacuum" not in workflow
    assert "finance-report-vps-hygiene" not in workflow
    assert "VPS_SSH_KEY" not in workflow
    assert "ssh-keyscan" not in workflow
