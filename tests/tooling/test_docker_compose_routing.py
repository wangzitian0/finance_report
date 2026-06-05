"""Deployment routing contracts for docker-compose.yml."""

from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def _label_priority(label: str) -> int:
    match = re.search(r"priority=(\d+)$", label)
    assert match is not None
    return int(match.group(1))


def test_AC8_13_89_pr_preview_api_route_has_higher_priority_than_web_route() -> None:
    """AC8.13.89 AC7.9.5: PR preview /api health routes to backend before web."""
    with open(ROOT / "docker-compose.yml") as f:
        config = yaml.safe_load(f)

    backend_labels = config["services"]["backend"]["labels"]
    frontend_labels = config["services"]["frontend"]["labels"]

    assert any("PathPrefix(`/api`)" in label for label in backend_labels)

    api_priority = next(
        label
        for label in backend_labels
        if ".finance-report-api" in label and ".priority=" in label
    )
    web_priority = next(
        label
        for label in frontend_labels
        if ".finance-report-web" in label and ".priority=" in label
    )

    assert _label_priority(api_priority) > _label_priority(web_priority)
