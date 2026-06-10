"""Safety tests for the runtime orphan sweep.

This logic decides which containers get `docker rm -f` on prod, so it gets
paired positive (正例) and negative (反例) cases. The negatives are the point:
prod/platform/open-PR containers must NEVER be selected for removal.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def lifecycle():
    return importlib.import_module("tools._lib.dev.pr_preview_lifecycle")


# ---- parse_preview_pr_from_container ----------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("finance-report-backend-pr-780-f17d4bd5ece1", 780),
        ("finance-report-frontend-pr-795-385c34621b0a", 795),
        ("finance-report-minio-init-pr-784-3b5097eb01f8", 784),
        ("finance-report-db-pr-1-abcdef123456", 1),
    ],
)
def test_positive_parses_preview_containers(name, expected) -> None:
    assert lifecycle().parse_preview_pr_from_container(name) == expected


@pytest.mark.parametrize(
    "name",
    [
        "finance_report-backend",  # prod app (underscore, no -pr-)
        "finance_report-frontend-staging",  # staging app
        "platform-prefect-server",  # platform service
        "dokploy-postgres.1.p7sk11xamk4i35ggidcoxknug",  # dokploy infra
        "finance-report-backend-pr-780",  # no commit-hash suffix
        "finance-report-backend-pr-0-abcdef123456",  # PR 0 is not valid
        "finance-report-backend-pr-abc-abcdef123456",  # non-numeric PR
        "",
    ],
)
def test_negative_never_parses_non_preview_or_malformed(name) -> None:
    """Anything not unmistakably a preview container must return None."""
    assert lifecycle().parse_preview_pr_from_container(name) is None


# ---- compute_orphan_containers ----------------------------------------------


def test_positive_closed_pr_containers_are_orphans() -> None:
    running = [
        "finance-report-backend-pr-780-f17d4bd5ece1",
        "finance-report-db-pr-780-f17d4bd5ece1",
    ]
    orphans = lifecycle().compute_orphan_containers(running, open_prs={795, 796})
    assert orphans == running


def test_negative_open_pr_and_prod_containers_are_never_orphans() -> None:
    """The core safety guarantee: open-PR and non-preview never get removed."""
    running = [
        "finance-report-backend-pr-795-385c34621b0a",  # open PR -> keep
        "finance-report-db-pr-796-aaaaaaaaaaaa",  # open PR -> keep
        "finance_report-backend",  # prod -> never matches
        "platform-prefect-server",  # platform -> never matches
        "dokploy-traefik",  # infra -> never matches
        "finance-report-backend-pr-780-f17d4bd5ece1",  # closed PR -> the only orphan
    ]
    orphans = lifecycle().compute_orphan_containers(running, open_prs={795, 796})

    assert orphans == ["finance-report-backend-pr-780-f17d4bd5ece1"]
    assert "finance_report-backend" not in orphans
    assert "platform-prefect-server" not in orphans
    assert all("pr-795" not in o and "pr-796" not in o for o in orphans)


def test_negative_empty_open_prs_still_skips_non_preview() -> None:
    """Even with zero open PRs, non-preview containers are untouched."""
    running = ["platform-prefect-server", "finance_report-backend", "dokploy-redis"]
    assert lifecycle().compute_orphan_containers(running, open_prs=set()) == []


# ---- remove_orphan_containers: dry-run / empty ------------------------------


def test_negative_remove_is_noop_when_no_orphans(capsys) -> None:
    lifecycle().remove_orphan_containers("user@host", [], dry_run=False)
    assert capsys.readouterr().out == ""  # no SSH, nothing printed


def test_positive_dry_run_does_not_execute_removal(capsys) -> None:
    lifecycle().remove_orphan_containers(
        "user@host", ["finance-report-db-pr-780-f17d4bd5ece1"], dry_run=True
    )
    assert "[dry-run] Would remove 1 orphan" in capsys.readouterr().out


# ---- cleanup_action must NOT swallow failures (#2) --------------------------


def test_negative_cleanup_surfaces_dokploy_error(monkeypatch) -> None:
    """A failed delete must return non-zero, not a silent clean exit."""
    mod = lifecycle()

    def boom(*_args, **_kwargs):
        raise mod.DokployRequestError("read timed out")

    monkeypatch.setattr(mod, "find_compose_id_by_name", boom)
    args = SimpleNamespace(
        api_url="x", api_key="y", compose_id="", environment_id="e", compose_name="pr-780"
    )
    assert mod.cleanup_action(args) == 1


def test_positive_cleanup_clean_when_already_gone(monkeypatch) -> None:
    mod = lifecycle()
    monkeypatch.setattr(mod, "find_compose_id_by_name", lambda *a, **k: "")
    args = SimpleNamespace(
        api_url="x", api_key="y", compose_id="", environment_id="e", compose_name="pr-780"
    )
    assert mod.cleanup_action(args) == 0
