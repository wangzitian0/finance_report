"""AC8.13.73 AC8.13.74: VPS host hygiene is a Dokploy scheduled job."""

from __future__ import annotations

import importlib
import json
import os
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
        network_prune_until="all",
        journal_vacuum_time="3d",
        journal_vacuum_size="1G",
        docker_log_truncate_size_mib=100,
        disk_warning_percent=85,
        disk_error_percent=95,
        pr_preview_max_age_days=3,
        pr_preview_keep_recent=3,
        github_repository="wangzitian0/finance_report",
    )

    assert "PR_PREVIEW_MAX_AGE_DAYS='3'" in script
    assert "PR_PREVIEW_KEEP_RECENT='3'" in script
    assert "GITHUB_REPOSITORY=wangzitian0/finance_report" in script
    assert "docker_usage_summary() {" in script
    assert "if command -v timeout >/dev/null 2>&1; then" in script
    assert "docker_usage_summary" in script
    assert "fetch_open_prs() {" in script
    assert "if ! command -v python3 >/dev/null 2>&1; then" in script
    assert (
        "https://api.github.com/repos/${GITHUB_REPOSITORY}/pulls?state=open&per_page=100&page=${page}"
        in script
    )
    assert 'curl -fsSL --connect-timeout 5 --max-time 15 "$api_url"' in script
    assert 'while [ "$page" -le 10 ]; do' in script
    assert 'page="$((page + 1))"' in script
    assert 'sed -n \'s/.*"number"' not in script
    assert 'if open_prs_raw="$(fetch_open_prs)"; then' in script
    assert "GitHub open-PR discovery failed on page ${page}" in script
    assert "python3 unavailable; falling back to retention" in script
    assert 'OPEN_PR_NUMBERS_SOURCE="github"' in script
    assert 'OPEN_PR_NUMBERS_SOURCE="fallback-retention"' in script
    assert 'if [ "$OPEN_PR_NUMBERS_SOURCE" = "github" ]; then' in script
    assert "return 0" in script
    assert (
        "PR_PREVIEW_CONTAINER_PATTERN='^finance-report-(backend|frontend|db|minio)-pr-[0-9]+(-[a-z0-9]+)?$'"
        in script
    )
    assert "CONTAINER_PRUNE_UNTIL='72h'" in script
    assert 'date -u -d "${PR_PREVIEW_MAX_AGE_DAYS} days ago" +%s' in script
    assert "timeout 20 docker system df -v" in script
    assert 'tail -n "$PR_PREVIEW_KEEP_RECENT"' in script
    assert "finance-report-(backend|frontend|db|minio)-pr-[0-9]+(-[a-z0-9]+)?" in script
    assert "should_delete_pr_container() {" in script
    assert (
        'case "$status" in restarting|exited|dead|created) return 0 ;; esac' in script
    )
    assert 'if [ "$health" = "unhealthy" ]; then' in script
    assert "finance_report_pr_[0-9]+_" in script
    assert "[dry-run] docker rm -f ${container_name}" in script
    assert "[dry-run] docker volume rm ${volume_name}" in script
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
        github_repository="wangzitian0/finance_report",
    )

    assert "CONTAINER_PRUNE_UNTIL='48h'" in script
    assert 'docker builder prune -af --filter "until=72h"' in script
    assert 'docker image prune -af --filter "until=240h"' in script
    assert 'docker network prune -f --filter "until=240h"' in script
    assert 'journalctl --vacuum-time="30d" --vacuum-size="512M"' in script
    assert "timeout 20 docker system df" in script
    assert "if command -v timeout >/dev/null 2>&1; then" in script
    assert ': > "$log_path"' in script
    assert 'docker rm -f "$container_name" || true' in script
    assert 'docker rm -f "$non_preview_container" || true' in script
    assert 'docker volume rm "$volume_name" || true' in script
    assert "relative_cutoff_epoch() {" in script
    assert (
        'container_cutoff_epoch="$(relative_cutoff_epoch "$CONTAINER_PRUNE_UNTIL")"'
        in script
    )
    assert 'date -u -d "${CONTAINER_PRUNE_UNTIL} ago" +%s' not in script
    assert 'date -u -d "$created_at" +%s 2>/dev/null || echo 0' not in script
    assert 'parse_utc_epoch "$created_at" || true' in script
    assert "Skipping deletion because timestamp is missing or unparseable" in script
    assert "docker container prune" not in script
    assert "[dry-run]" not in script
    assert "GITHUB_REPOSITORY=wangzitian0/finance_report" in script


def test_AC8_13_73_hygiene_script_shell_quotes_github_repository() -> None:
    hygiene = hygiene_module()

    script = hygiene.build_hygiene_script(
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
        pr_preview_max_age_days=3,
        pr_preview_keep_recent=3,
        github_repository="owner/repo'; echo injected #",
    )

    assert "GITHUB_REPOSITORY='owner/repo'\"'\"'; echo injected #'" in script
    result = subprocess.run(
        ["sh", "-n"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_AC8_13_73_hygiene_script_treats_zero_open_prs_as_github_success(
    tmp_path: Path,
) -> None:
    hygiene = hygiene_module()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "system" ]; then echo "docker usage"; exit 0; fi\n'
        'if [ "$1" = "ps" ]; then exit 0; fi\n'
        'if [ "$1" = "volume" ]; then exit 0; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    curl = bin_dir / "curl"
    curl.write_text("#!/bin/sh\nprintf '[]\\n'\n", encoding="utf-8")
    curl.chmod(0o755)
    date = bin_dir / "date"
    date.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        '  *"+%s"*) echo 1700000000 ;;\n'
        '  *) /bin/date "$@" ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    date.chmod(0o755)

    script = hygiene.build_hygiene_script(
        dry_run=True,
        container_prune_until="72h",
        builder_prune_until="72h",
        image_prune_until="72h",
        network_prune_until="all",
        journal_vacuum_time="3d",
        journal_vacuum_size="1G",
        docker_log_truncate_size_mib=0,
        disk_warning_percent=99,
        disk_error_percent=100,
        pr_preview_max_age_days=3,
        pr_preview_keep_recent=3,
        github_repository="wangzitian0/finance_report",
    )

    result = subprocess.run(
        ["sh"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )

    assert result.returncode == 0, result.stderr
    assert "Open PR source: github" in result.stdout
    assert "Open PR source: fallback-retention" not in result.stdout


def test_AC8_13_73_hygiene_script_can_filter_unused_network_prune_window() -> None:
    hygiene = hygiene_module()

    script = hygiene.build_hygiene_script(
        dry_run=True,
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
        github_repository="wangzitian0/finance_report",
    )

    assert "[dry-run] docker network prune -f --filter until=240h" in script


def test_AC8_13_73_hygiene_script_skips_unparseable_resource_timestamps() -> None:
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
        github_repository="wangzitian0/finance_report",
    )

    assert "parse_utc_epoch() {" in script
    assert 'created_epoch="$(parse_utc_epoch "$created_at" || true)"' in script
    assert 'if [ -z "$created_epoch" ]; then' in script
    assert "return 1" in script
    assert "continue" in script


def test_AC8_13_73_hygiene_script_is_shell_parseable() -> None:
    hygiene = hygiene_module()

    script = hygiene.build_hygiene_script(
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
        pr_preview_max_age_days=3,
        pr_preview_keep_recent=3,
        github_repository="wangzitian0/finance_report",
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
        github_repository="wangzitian0/finance_report",
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
    assert "GITHUB_REPOSITORY=wangzitian0/finance_report" in str(payload["command"])
    assert "within 3 days" in str(payload["description"])
    assert "most recent 3 PRs" in str(payload["description"])
    assert (
        "closed PR previews are removed by comparing against open PRs from wangzitian0/finance_report"
        in str(payload["description"])
    )
    assert "VPS_SSH_KEY" not in json.dumps(payload)


def test_AC8_13_73_dokploy_schedule_payload_describes_overridden_retention() -> None:
    hygiene = hygiene_module()

    payload = hygiene.build_schedule_payload(
        server_id="srv-1",
        script="echo clean",
        pr_preview_max_age_days=7,
        pr_preview_keep_recent=5,
        github_repository="owner/repo",
    )

    assert "within 7 days" in str(payload["description"])
    assert "most recent 5 PRs" in str(payload["description"])
    assert "open PRs from owner/repo" in str(payload["description"])
    assert "within 3 days" not in str(payload["description"])
    assert "most recent 3 PRs" not in str(payload["description"])


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


def test_AC8_13_73_dokploy_schedule_payload_normalizes_null_and_empty_server_ids(
    monkeypatch,
) -> None:
    hygiene = hygiene_module()

    # 1. Test build_schedule_payload
    for sid in ("null", "undefined", "", None):
        payload = hygiene.build_schedule_payload(
            server_id=sid,
            script="echo clean",
        )
        assert payload["serverId"] is None

    # 2. Test find_schedule_id_by_name uses "null" in GET query parameters
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


def test_AC8_13_74_pr_preview_cleanup_workflow_has_no_host_hygiene() -> None:
    workflow = (ROOT / ".github/workflows/pr-preview-cleanup.yml").read_text()

    assert "docker container prune" not in workflow
    assert "docker builder prune" not in workflow
    assert "docker image prune" not in workflow
    assert "journal-vacuum" not in workflow
    assert "finance-report-vps-hygiene" not in workflow
    assert "VPS_SSH_KEY" not in workflow
    assert "ssh-keyscan" not in workflow
