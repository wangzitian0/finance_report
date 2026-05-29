"""AC8.13.38: Scheduled PR preview cleanup coverage."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools._lib.dev import cleanup_pr_preview_resources as cleanup  # noqa: E402


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


def test_AC8_13_38_workflow_runs_on_schedule_and_manual_dispatch() -> None:
    workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/pr-preview-cleanup.yml").read_text()

    assert 'cron: "37 */6 * * *"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "tools/cleanup_pr_preview_resources.py" in workflow
    assert "VPS_SSH_KEY" in workflow
