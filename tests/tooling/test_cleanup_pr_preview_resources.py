"""AC8.13.38: Scheduled PR preview cleanup coverage."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools._lib.dev import cleanup_pr_preview_resources as cleanup  # noqa: E402


def test_AC8_13_38_run_command_uses_checked_text_subprocess(
    monkeypatch,
) -> None:
    calls = []

    def fake_run(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(stdout="ok\n", stderr="", returncode=0)

    monkeypatch.setattr(cleanup.subprocess, "run", lambda *args, **kwargs: fake_run(**kwargs))

    result = cleanup.run_command(["gh", "pr", "list"], input_text="payload", check=False)

    assert result.stdout == "ok\n"
    assert calls == [
        {
            "input": "payload",
            "capture_output": True,
            "text": True,
            "check": False,
        }
    ]


def test_AC8_13_38_ssh_command_includes_optional_identity_file() -> None:
    assert cleanup.ssh_command("vps.example", "deployer", "/tmp/key", "uptime") == [
        "ssh",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-i",
        "/tmp/key",
        "deployer@vps.example",
        "uptime",
    ]


def test_AC8_13_38_parse_and_list_open_pr_numbers(monkeypatch) -> None:
    assert cleanup.parse_open_pr_numbers("\n434\n\n 498 \n") == {434, 498}

    monkeypatch.setattr(
        cleanup,
        "run_command",
        lambda cmd: SimpleNamespace(stdout="434\n498\n"),
    )

    assert cleanup.list_open_pr_numbers() == {434, 498}


def test_AC8_13_38_parse_preview_resources_groups_by_pr() -> None:
    output = "\n".join(
        [
            "finance-report-backend-pr-434\tcompose-old",
            "finance-report-frontend-pr-434\tcompose-old",
            "finance-report-db-pr-498\tcompose-open",
            "unrelated\tcompose-other",
        ]
    )

    resources = cleanup.parse_preview_resources(output)

    assert sorted(resources) == [434, 498]
    assert resources[434].containers == {
        "finance-report-backend-pr-434",
        "finance-report-frontend-pr-434",
    }
    assert resources[434].compose_projects == {"compose-old"}


def test_AC8_13_38_list_remote_preview_resources_uses_safe_ssh_command(monkeypatch) -> None:
    calls = []

    def fake_run_command(cmd):
        calls.append(cmd)
        return SimpleNamespace(stdout="finance-report-minio-pr-434\t<no value>\n")

    monkeypatch.setattr(cleanup, "run_command", fake_run_command)

    resources = cleanup.list_remote_preview_resources("vps.example", "root", None)

    assert sorted(resources) == [434]
    assert resources[434].containers == {"finance-report-minio-pr-434"}
    assert resources[434].compose_projects == set()
    assert calls == [
        [
            "ssh",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "root@vps.example",
            "docker ps -a --format '{{.Names}}\\t{{.Label \"com.docker.compose.project\"}}'",
        ]
    ]


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
    assert "compose-open" not in script
    assert "[dry-run] docker builder prune -af --filter until=24h" in script
    assert "[dry-run] docker image prune -af --filter until=168h" in script


def test_AC8_13_38_remote_cleanup_script_prunes_without_dry_run() -> None:
    resources = cleanup.parse_preview_resources(
        "finance-report-backend-pr-434\tcompose-old\n"
        "finance-report-frontend-pr-435\tcompose;unsafe\n"
    )

    script = cleanup.build_remote_cleanup_script(
        resources,
        dry_run=False,
        prune_build_cache=True,
        prune_images=True,
        builder_prune_until="12h",
        image_prune_until="72h",
    )

    assert "PROJECTS='compose-old'" in script
    assert "compose;unsafe" not in script
    assert 'docker builder prune -af --filter "until=12h"' in script
    assert 'docker image prune -af --filter "until=72h"' in script
    assert "echo [dry-run]" not in script


def test_AC8_13_38_cleanup_executes_remote_script_and_returns_status(
    monkeypatch,
    capsys,
) -> None:
    run_calls = []
    resources = cleanup.parse_preview_resources("finance-report-backend-pr-434\tcompose-old\n")

    monkeypatch.setattr(cleanup, "list_open_pr_numbers", lambda: {498})
    monkeypatch.setattr(cleanup, "list_remote_preview_resources", lambda *_args: resources)

    def fake_run_command(cmd, *, input_text=None, check=True):
        run_calls.append((cmd, input_text, check))
        return SimpleNamespace(stdout="cleaned\n", stderr="warn\n", returncode=7)

    monkeypatch.setattr(cleanup, "run_command", fake_run_command)

    args = SimpleNamespace(
        host="vps.example",
        user="root",
        ssh_key="/tmp/key",
        dry_run=True,
        no_prune_build_cache=False,
        no_prune_images=True,
        builder_prune_until="24h",
        image_prune_until="168h",
    )

    assert cleanup.cleanup(args) == 7

    out = capsys.readouterr()
    assert "Open PRs: [498]" in out.out
    assert "Stale preview PRs: [434]" in out.out
    assert "cleaned" in out.out
    assert "warn" in out.err
    assert run_calls[0][0] == [
        "ssh",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-i",
        "/tmp/key",
        "root@vps.example",
        "sh -s",
    ]
    assert "PRS='434'" in run_calls[0][1]
    assert run_calls[0][2] is False


def test_AC8_13_38_main_parses_cli_flags(monkeypatch) -> None:
    captured = []

    def fake_cleanup(args):
        captured.append(args)
        return 3

    monkeypatch.setattr(cleanup, "cleanup", fake_cleanup)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cleanup_pr_preview_resources.py",
            "--host",
            "vps.example",
            "--user",
            "deployer",
            "--ssh-key",
            "/tmp/key",
            "--dry-run",
            "--no-prune-build-cache",
            "--no-prune-images",
            "--builder-prune-until",
            "12h",
            "--image-prune-until",
            "72h",
        ],
    )

    assert cleanup.main() == 3
    assert captured[0].host == "vps.example"
    assert captured[0].user == "deployer"
    assert captured[0].ssh_key == "/tmp/key"
    assert captured[0].dry_run is True
    assert captured[0].no_prune_build_cache is True
    assert captured[0].no_prune_images is True
    assert captured[0].builder_prune_until == "12h"
    assert captured[0].image_prune_until == "72h"


def test_AC8_13_38_workflow_runs_on_schedule_and_manual_dispatch() -> None:
    workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/pr-preview-cleanup.yml").read_text()

    assert 'cron: "37 */6 * * *"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "tools/cleanup_pr_preview_resources.py" in workflow
    assert "VPS_SSH_KEY" in workflow
