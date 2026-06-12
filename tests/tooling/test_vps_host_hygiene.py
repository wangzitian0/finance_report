"""AC8.13.73 AC8.13.74: VPS host hygiene is a Dokploy scheduled job.

Host hygiene is generic-only: PR preview environments are reaped natively by
Dokploy ``compose.delete`` (reliable since v0.29.x), so this job no longer
fetches open PRs or removes preview containers/volumes. It prunes aged stopped
containers, builder/image/network caches, vacuums the journal, truncates
oversized Docker json logs, and alerts on disk usage. The schedule runs as a
``dokploy-server`` job (the legacy ``server`` type with a null serverId is
accepted by the API but never executes — that silent no-op let orphans pile up).
"""

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


def _build(hygiene, **overrides):
    params = dict(
        dry_run=True,
        container_prune_until="72h",
        builder_prune_until="72h",
        image_prune_until="72h",
        network_prune_until="all",
        journal_vacuum_time="3d",
        journal_vacuum_size="1G",
        docker_log_truncate_size_mib=100,
        disk_warning_percent=85,
        disk_error_percent=95,
    )
    params.update(overrides)
    return hygiene.build_hygiene_script(**params)


def test_AC8_13_73_hygiene_script_prunes_generic_host_garbage() -> None:
    hygiene = hygiene_module()
    script = _build(hygiene)

    # Generic hygiene is present.
    assert "docker_usage_summary() {" in script
    assert "if command -v timeout >/dev/null 2>&1; then" in script
    assert "Cleaning old non-preview stopped containers" in script
    assert "CONTAINER_PRUNE_UNTIL='72h'" in script
    assert "timeout 20 docker system df -v" in script
    assert "[dry-run] docker rm -f ${non_preview_container}" in script
    assert "docker container prune" not in script
    assert "[dry-run] docker builder prune -af --filter until=72h" in script
    assert "[dry-run] docker image prune -af --filter until=72h" in script
    assert "[dry-run] docker network prune -f" in script
    assert "[dry-run] docker network prune -f --filter" not in script
    assert "[dry-run] journalctl --vacuum-time=3d --vacuum-size=1G" in script
    assert "DOCKER_LOG_TRUNCATE_SIZE_MIB='100'" in script
    assert "DISK_WARNING_PERCENT='85'" in script
    assert "DISK_ERROR_PERCENT='95'" in script
    # The exclusion pattern stays so generic cleanup never touches Dokploy-owned
    # preview containers, but the GitHub open-PR reaper is gone.
    assert (
        "PR_PREVIEW_CONTAINER_PATTERN='^finance-report-(backend|frontend|db|minio)-pr-[0-9]+(-[a-z0-9]+)?$'"
        in script
    )
    assert "fetch_open_prs" not in script
    assert "should_delete_pr_container" not in script
    assert "should_delete_pr_resource" not in script
    assert "PR_PREVIEW_MAX_AGE_DAYS" not in script
    assert "PR_PREVIEW_KEEP_RECENT" not in script
    assert "GITHUB_REPOSITORY" not in script
    assert "api.github.com" not in script
    assert "docker volume rm" not in script
    assert "VPS_SSH_KEY" not in script


def test_AC8_13_73_hygiene_script_runs_real_prune_commands_without_credentials() -> (
    None
):
    hygiene = hygiene_module()
    script = _build(
        hygiene,
        dry_run=False,
        container_prune_until="48h",
        image_prune_until="240h",
        network_prune_until="240h",
        journal_vacuum_time="30d",
        journal_vacuum_size="512M",
        docker_log_truncate_size_mib=50,
        disk_warning_percent=80,
        disk_error_percent=90,
    )

    assert "CONTAINER_PRUNE_UNTIL='48h'" in script
    assert 'docker builder prune -af --filter "until=72h"' in script
    assert 'docker image prune -af --filter "until=240h"' in script
    assert 'docker network prune -f --filter "until=240h"' in script
    assert 'journalctl --vacuum-time="30d" --vacuum-size="512M"' in script
    assert "timeout 20 docker system df" in script
    assert ': > "$log_path"' in script
    assert 'docker rm -f "$non_preview_container" || true' in script
    # Shared time helpers used by the generic stopped-container cleanup.
    assert "parse_utc_epoch() {" in script
    assert "relative_cutoff_epoch() {" in script
    assert (
        'container_cutoff_epoch="$(relative_cutoff_epoch "$CONTAINER_PRUNE_UNTIL")"'
        in script
    )
    assert 'parse_utc_epoch "$created_at" || true' in script
    assert "Skipping deletion because timestamp is missing or unparseable" in script
    assert "[dry-run]" not in script
    # No preview reaper.
    assert "fetch_open_prs" not in script
    assert "docker volume rm" not in script


def test_AC8_13_73_hygiene_script_can_filter_unused_network_prune_window() -> None:
    hygiene = hygiene_module()
    script = _build(hygiene, network_prune_until="240h")
    assert "[dry-run] docker network prune -f --filter until=240h" in script


def test_AC8_13_73_hygiene_script_skips_unparseable_resource_timestamps() -> None:
    hygiene = hygiene_module()
    script = _build(hygiene, dry_run=False)

    assert "parse_utc_epoch() {" in script
    assert 'created_epoch="$(parse_utc_epoch "$created_at" || true)"' in script
    assert 'if [ -z "$created_epoch" ]; then' in script
    assert "continue" in script


def test_AC8_13_73_hygiene_script_is_shell_parseable() -> None:
    hygiene = hygiene_module()
    script = _build(hygiene)

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


def test_AC8_13_73_emit_script_prints_without_running_locally(
    monkeypatch, capsys
) -> None:
    """AC8.13.73: --emit-script prints the hygiene script and does NOT execute it
    locally."""
    hygiene = hygiene_module()
    ran = []
    monkeypatch.setattr(hygiene, "run_command", lambda *a, **k: ran.append(a) or None)

    assert hygiene.main(["--emit-script"]) == 0

    out = capsys.readouterr().out
    assert "Cleaning old non-preview stopped containers" in out
    assert "should_delete_pr_container" not in out
    assert ran == []  # emit must not run the script locally


def test_AC8_13_73_dokploy_schedule_payload_is_dokploy_server_generic_job() -> None:
    hygiene = hygiene_module()
    script = _build(hygiene, dry_run=False, network_prune_until="72h")
    payload = hygiene.build_schedule_payload(server_id="null", script=script)

    assert payload["name"] == "finance-report-vps-host-hygiene"
    assert payload["cronExpression"] == "17 3,9,15,21 * * *"
    # Host-level schedules MUST be dokploy-server to actually execute on v0.29.x.
    assert payload["scheduleType"] == "dokploy-server"
    assert payload["shellType"] == "bash"
    assert payload["serverId"] is None
    assert payload["enabled"] is True
    assert payload["timezone"] == "Asia/Singapore"
    assert payload["command"] == script
    assert payload["script"] == script
    # Description describes generic hygiene, not preview retention.
    assert "PR preview environments are reaped by Dokploy compose.delete" in str(
        payload["description"]
    )
    assert "within 3 days" not in str(payload["description"])
    assert "most recent" not in str(payload["description"])
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
        server_id="null",
        script="echo clean",
        name="finance-report-vps-host-hygiene",
        cron_expression="17 3,9,15,21 * * *",
        timezone="Asia/Singapore",
        enabled=True,
    )

    assert result == "sch-1"
    assert calls[0][0] == "schedule.list?id=null&scheduleType=dokploy-server"
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
        server_id="null",
        script="echo clean",
        name="finance-report-vps-host-hygiene",
        cron_expression="17 3,9,15,21 * * *",
        timezone="Asia/Singapore",
        enabled=True,
    )

    assert result == "sch-new"
    assert calls == [
        "schedule.list?id=null&scheduleType=dokploy-server",
        "schedule.create",
    ]


def test_AC8_13_73_dokploy_schedule_payload_normalizes_null_and_empty_server_ids(
    monkeypatch,
) -> None:
    hygiene = hygiene_module()

    for sid in ("null", "undefined", "", None):
        payload = hygiene.build_schedule_payload(server_id=sid, script="echo clean")
        assert payload["serverId"] is None

    calls: list[str] = []

    def fake_api_call(config, method, endpoint, *, payload=None, expected_status=200):
        calls.append(endpoint)
        return json.dumps({"schedules": []})

    monkeypatch.setattr(hygiene, "dokploy_api_call", fake_api_call)

    for sid in ("null", "undefined", "", None):
        hygiene.find_schedule_id_by_name(
            hygiene.DokployConfig("https://cloud.example/api", "secret"),
            server_id=sid,
            name="test-schedule",
        )

    assert len(calls) == 4
    for call in calls:
        assert "id=null&" in call
        assert "scheduleType=dokploy-server" in call


def test_AC8_13_74_pr_preview_cleanup_workflow_has_no_host_hygiene() -> None:
    workflow = (ROOT / ".github/workflows/pr-preview-cleanup.yml").read_text()

    assert "docker container prune" not in workflow
    assert "docker builder prune" not in workflow
    assert "docker image prune" not in workflow
    assert "journal-vacuum" not in workflow
    assert "vps_host_hygiene" not in workflow
    assert "VPS_SSH_KEY" not in workflow
    assert "ssh-keyscan" not in workflow


def test_AC8_13_73_ssh_reaper_workflow_is_removed() -> None:
    """The post-merge SSH orphan-reaper workflow was a workaround for Dokploy's
    broken compose.delete. With v0.29.x reaping previews natively and host
    hygiene running as a verified dokploy-server schedule, the SSH reaper is
    gone."""
    assert not (ROOT / ".github/workflows/pr-preview-host-hygiene.yml").exists()
