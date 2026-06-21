"""EPIC-007 AC7.19.1: GHCR SHA image retention (#1277)."""

from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path
from typing import Sequence

import yaml

from common.ci.ghcr_retention import (
    load_versions,
    prune_ghcr_sha_images,
    select_retention_decisions,
)

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ghcr-sha-retention.yml"


def _version(
    version_id: str,
    *,
    tags: list[str],
    created_at: str = "2026-05-01T00:00:00Z",
) -> dict:
    return {
        "id": version_id,
        "created_at": created_at,
        "metadata": {"container": {"tags": tags}},
    }


def _run_text(workflow: dict, step_name: str) -> str:
    job = workflow["jobs"]["prune-sha-images"]
    for step in job["steps"]:
        if step.get("name") == step_name:
            return str(step.get("run", ""))
    raise AssertionError(f"step not found: {step_name}")


def test_AC7_19_1_retention_selects_only_stale_sha_tags() -> None:
    now = dt.datetime(2026, 6, 21, tzinfo=dt.UTC)
    decisions = select_retention_decisions(
        [
            _version("old-sha", tags=["abc1234"]),
            _version("fresh-sha", tags=["def5678"], created_at="2026-06-10T00:00:00Z"),
            _version("release", tags=["9876543", "v1.2.3"]),
            _version("live", tags=["facefeed"]),
            _version("pr-tag", tags=["pr-123-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]),
        ],
        retention_days=28,
        live_shas=["facefeedcafebeefcafebeefcafebeefcafebeef"],
        now=now,
    )

    by_id = {decision.version_id: decision for decision in decisions}
    assert by_id["old-sha"].action == "delete"
    assert by_id["old-sha"].reason == "stale-sha"
    assert by_id["fresh-sha"].reason == "retention-window"
    assert by_id["release"].reason == "release-tag"
    assert by_id["live"].reason == "live-deploy-sha"
    assert by_id["pr-tag"].reason == "no-sha-tag"


def test_AC7_19_1_live_sha_exemption_matches_full_and_short_tags() -> None:
    now = dt.datetime(2026, 6, 21, tzinfo=dt.UTC)
    full_sha = "0123456789abcdef0123456789abcdef01234567"
    decisions = select_retention_decisions(
        [
            _version("short-live", tags=["0123456"]),
            _version("full-live", tags=[full_sha]),
        ],
        retention_days=28,
        live_shas=[full_sha],
        now=now,
    )

    assert {decision.reason for decision in decisions} == {"live-deploy-sha"}


def test_AC7_19_1_pruner_requires_live_sha_exemptions() -> None:
    try:
        prune_ghcr_sha_images(
            package_scope_path="/users/wangzitian0",
            image_names=["finance_report-backend"],
            retention_days=28,
            live_shas=[],
            dry_run=True,
        )
    except ValueError as exc:
        assert "live deploy SHA exemption" in str(exc)
    else:
        raise AssertionError("pruner must fail closed without live SHA exemptions")


def test_AC7_19_1_pruner_deletes_selected_versions_only() -> None:
    calls: list[list[str]] = []
    versions = [
        _version("delete-me", tags=["aaaaaaa"]),
        _version("keep-release", tags=["bbbbbbb", "v1.2.3"]),
        _version("keep-live", tags=["ccccccc"]),
    ]

    def fake_gh(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        calls.append(list(args))
        if "DELETE" in args:
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 0, str(load_versions.__module__), "")

    def fake_list(_: str) -> list[dict]:
        return versions

    # Keep this test focused on the delete contract; the JSON shape is covered by
    # load_versions and the workflow contract covers the GHCR list endpoint.
    import common.ci.ghcr_retention as retention

    original_list = retention._list_versions
    try:
        retention._list_versions = lambda **_kwargs: fake_list("")  # type: ignore[assignment]
        selected = prune_ghcr_sha_images(
            package_scope_path="/users/wangzitian0",
            image_names=["finance_report-backend"],
            retention_days=28,
            live_shas=["ccccccc"],
            dry_run=False,
            gh=fake_gh,
        )
    finally:
        retention._list_versions = original_list  # type: ignore[assignment]

    assert selected == 1
    delete_calls = [call for call in calls if "DELETE" in call]
    assert len(delete_calls) == 1
    assert delete_calls[0][-1].endswith("/finance_report-backend/versions/delete-me")


def test_AC7_19_1_load_versions_accepts_gh_paginated_slurp() -> None:
    raw = """
    [
      [{"id": 1, "metadata": {"container": {"tags": ["aaaaaaa"]}}}],
      [{"id": 2, "metadata": {"container": {"tags": ["bbbbbbb"]}}}]
    ]
    """
    assert [version["id"] for version in load_versions(raw)] == [1, 2]


def test_AC7_19_1_workflow_schedules_28_day_sha_retention_with_live_exemption() -> None:
    workflow_text = WORKFLOW.read_text(encoding="utf-8")
    workflow = yaml.safe_load(workflow_text)

    assert workflow["name"] == "GHCR SHA Retention"
    triggers = workflow.get("on") or workflow.get(True)
    assert "schedule" in triggers
    assert triggers["schedule"][0]["cron"] == "17 3 * * *"
    assert "workflow_dispatch" in triggers
    assert workflow["env"]["GHCR_SHA_RETENTION_DAYS"] == "28"
    assert workflow["permissions"]["packages"] == "write"

    collect = _run_text(workflow, "Collect live deploy SHA exemptions")
    assert "https://report-staging.zitian.party/api/health" in workflow_text
    assert "https://report.zitian.party/api/health" in workflow_text
    assert 'git rev-parse --verify --quiet "$candidate^{commit}"' in collect
    assert "No live deploy SHA exemptions discovered" in collect

    prune = _run_text(workflow, "Prune GHCR SHA images older than 28 days")
    assert "tools/ghcr_retention.py" in prune
    assert "--retention-days \"${GHCR_SHA_RETENTION_DAYS}\"" in prune
    assert "--live-shas-file live-shas.txt" in prune
    assert "--image-name finance_report-backend" in prune
    assert "--image-name finance_report-frontend" in prune
    assert "ghcr-sha-retention-context" in workflow_text
