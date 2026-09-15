"""AC-runtime.deploy-freshness.1: a deployed environment serving days-old work is red.

Production v0.1.50 reached users on 2026-09-10 through a door no workflow
measured; the last successful release.yml production run before it was v0.1.44
on 2026-07-19. The bound here is AGE rather than commit count on purpose, and
it is per environment: staging 3 days, production 7 days (promotion is
deliberate, so looser).
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta

import pytest

from common.runtime.deploy_freshness import (
    DEFAULT_MAX_AGE_DAYS,
    Staleness,
    check_freshness,
    identity_from_body,
    judge,
    max_age_for,
    measure,
)

URL = "https://report.zitian.party/api/health"
NOW = datetime(2026, 9, 15, 7, 0, tzinfo=UTC)


def _health(git_sha: str):
    def http_get(url: str) -> tuple[int, str]:
        return 200, json.dumps({"status": "healthy", "git_sha": git_sha})

    return http_get


def _git(
    log_lines: list[str],
    *,
    resolves: bool = True,
    newest_release: str = "",
    newest_release_sha: str = "cafe123",
):
    """Fake `git`: `rev-parse` proves a ref exists (the deployed ref resolves to
    `cafe123`, the newest release to `newest_release_sha`), `describe` names
    the newest tag on main, `log` yields `%cI\\x1f%s` lines."""

    def run(argv, capture_output=True, text=True, check=False):  # noqa: ARG001
        if "rev-parse" in argv:
            ref = argv[-1].removesuffix("^{commit}")
            if not resolves:
                return subprocess.CompletedProcess(argv, 128, "", "fatal: bad ref")
            sha = newest_release_sha if ref == newest_release else "cafe123"
            return subprocess.CompletedProcess(argv, 0, f"{sha}\n", "")
        if "describe" in argv:
            if not newest_release:
                return subprocess.CompletedProcess(argv, 128, "", "fatal: no tags")
            return subprocess.CompletedProcess(argv, 0, f"{newest_release}\n", "")
        return subprocess.CompletedProcess(argv, 0, "\n".join(log_lines), "")

    return run


def _ago(**kwargs) -> str:
    return (NOW - timedelta(**kwargs)).isoformat()


def _staleness(age: timedelta | None, count: int, **overrides) -> Staleness:
    fields = {
        "environment": "production",
        "deployed_ref": "v0.1.50",
        "newest_release": "v0.1.50",
        "newest_release_deployed": True,
        "undeployed_commits": count,
        "oldest_undeployed_age": age,
        "oldest_undeployed_subject": "the one that has been invisible",
    }
    fields.update(overrides)
    return Staleness(**fields)


# ── the pure comparison ────────────────────────────────────────────────────


def test_AC_runtime_deploy_freshness_1_age_not_count_is_the_bound() -> None:
    """Ten commits merged this morning are fine; one commit merged last week is not."""
    bound = timedelta(days=7)
    recent = judge(_staleness(timedelta(hours=6), 10), bound)
    assert recent.kind == "fresh"
    assert "10 commit(s)" in recent.summary

    old = judge(_staleness(timedelta(days=9, hours=3), 1), bound)
    assert old.kind == "stale"
    assert "production is stale" in old.summary
    assert "v0.1.50" in old.summary, "the operator must learn WHICH release is deployed"
    assert "9d3h" in old.summary and "limit 7d" in old.summary, "and HOW far behind"
    assert "the one that has been invisible" in old.summary


def test_nothing_undeployed_is_current() -> None:
    verdict = judge(_staleness(None, 0), timedelta(days=3))
    assert verdict.kind == "fresh"
    assert "is current" in verdict.summary


def test_the_bound_is_inclusive_at_exactly_the_limit() -> None:
    assert judge(_staleness(timedelta(days=3), 1), timedelta(days=3)).kind == "fresh"
    assert (
        judge(_staleness(timedelta(days=3, seconds=1), 1), timedelta(days=3)).kind
        == "stale"
    )


def test_per_environment_bounds_are_explicit_and_differ() -> None:
    """Five-day-old work is stale on staging (3d) and still fresh on production (7d)."""
    assert DEFAULT_MAX_AGE_DAYS == {"staging": 3, "production": 7}
    assert max_age_for("staging") == timedelta(days=3)
    assert max_age_for("production") == timedelta(days=7)
    assert max_age_for("production", 1) == timedelta(days=1), "an override wins"
    five_days = timedelta(days=5)
    staging = judge(
        _staleness(five_days, 4, environment="staging"), max_age_for("staging")
    )
    production = judge(_staleness(five_days, 4), max_age_for("production"))
    assert staging.kind == "stale"
    assert production.kind == "fresh"


def test_the_verdict_names_which_door_the_work_waits_behind() -> None:
    old = timedelta(days=10)
    idle_lane = judge(_staleness(old, 3), timedelta(days=7))
    assert "release lane is idle" in idle_lane.summary

    unpromoted = judge(
        _staleness(old, 3, newest_release="v0.1.52", newest_release_deployed=False),
        timedelta(days=7),
    )
    assert (
        "v0.1.52 is cut from main but not promoted to production" in unpromoted.summary
    )

    no_tags = judge(_staleness(old, 3, newest_release=""), timedelta(days=7))
    assert "No vX.Y.Z release tag" in no_tags.summary


# ── the release identity ────────────────────────────────────────────────────


def test_identity_prefers_git_sha_then_version_and_rejects_the_unjudgeable() -> None:
    assert identity_from_body('{"git_sha": "v0.1.50", "version": "x"}') == "v0.1.50"
    assert identity_from_body('{"version": "v0.1.50"}') == "v0.1.50"
    for body in ("{}", '{"git_sha": "unknown"}', "[]", "not json"):
        with pytest.raises(Exception, match="release identity|not an object|JSON"):
            identity_from_body(body)


# ── the whole check, with the environment and git faked ────────────────────


def test_current_environment_passes(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = check_freshness(
        URL,
        environment="production",
        http_get=_health("v0.1.50"),
        now=NOW,
        run=_git([], newest_release="v0.1.50"),
        github_output=lambda _: None,
    )
    assert exit_code == 0
    assert "is current" in capsys.readouterr().out


def test_the_real_gap_would_have_fired(capsys: pytest.CaptureFixture[str]) -> None:
    """v0.1.44 served 53 days while main moved on -- the condition nothing measured."""
    outputs: dict[str, str] = {}
    exit_code = check_freshness(
        URL,
        environment="production",
        http_get=_health("v0.1.44"),
        now=NOW,
        run=_git(
            [f"{_ago(days=53)}\x1fthe first invisible merge"]
            + [f"{_ago(hours=2)}\x1flater" for _ in range(17)],
            newest_release="v0.1.50",
            newest_release_sha="beef456",
        ),
        github_output=outputs.update,
    )
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "production is stale" in err
    assert "18 commit(s)" in err
    assert "v0.1.50 is cut from main but not promoted to production" in err
    assert outputs["verdict"] == "stale"
    assert outputs["summary"].startswith("production is stale")


def test_a_dispatch_override_replaces_the_environment_default(
    capsys: pytest.CaptureFixture[str],
) -> None:
    run = _git([f"{_ago(days=5)}\x1fa merge"], newest_release="v0.1.50")
    common = dict(
        http_get=_health("v0.1.50"), now=NOW, run=run, github_output=lambda _: None
    )
    assert check_freshness(URL, environment="production", **common) == 0
    assert check_freshness(URL, environment="production", max_age_days=2, **common) == 1
    assert "limit 2d" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("http_get", "expected"),
    [
        (_health("unknown"), "does not report a release identity"),
        (lambda _url: (503, "down"), "HTTP 503"),
        (lambda _url: (0, "connection refused"), "HTTP 0"),
    ],
)
def test_an_unjudgeable_environment_is_unmeasurable_not_stale(
    http_get, expected: str, capsys: pytest.CaptureFixture[str]
) -> None:
    outputs: dict[str, str] = {}
    exit_code = check_freshness(
        URL,
        environment="staging",
        http_get=http_get,
        now=NOW,
        run=_git([]),
        github_output=outputs.update,
    )
    assert exit_code == 1
    assert expected in capsys.readouterr().err
    assert outputs["verdict"] == "unmeasurable", (
        "the issue title must not claim staleness"
    )


def test_a_ref_this_checkout_cannot_resolve_is_unmeasurable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = check_freshness(
        URL,
        environment="production",
        http_get=_health("v9.9.9"),
        now=NOW,
        run=_git([], resolves=False),
        github_output=lambda _: None,
    )
    assert exit_code == 1
    assert "not a commit here" in capsys.readouterr().err


def test_a_ref_git_could_read_as_an_option_never_reaches_git(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The reported release arrives over HTTP; git must not be handed an option."""
    reached_git = False

    def run(argv, capture_output=True, text=True, check=False):  # noqa: ARG001
        nonlocal reached_git
        reached_git = True
        return subprocess.CompletedProcess(argv, 0, "", "")

    for hostile in ("--upload-pack=touch /tmp/x", "-n", "v1 --all", "a" * 300):
        exit_code = check_freshness(
            URL,
            environment="production",
            http_get=_health(hostile),
            now=NOW,
            run=run,
            github_output=lambda _: None,
        )
        assert exit_code == 1, f"{hostile!r} must be refused"
        assert "not a usable release identifier" in capsys.readouterr().err
    assert not reached_git


def test_measure_reads_newest_tag_and_undeployed_log_from_git() -> None:
    staleness = measure(
        "staging",
        "v0.1.50",
        now=NOW,
        run=_git(
            [f"{_ago(days=4)}\x1ffirst", f"{_ago(hours=1)}\x1fsecond"],
            newest_release="v0.1.51",
            newest_release_sha="beef456",
        ),
    )
    assert staleness.undeployed_commits == 2
    assert staleness.oldest_undeployed_age == timedelta(days=4)
    assert staleness.oldest_undeployed_subject == "first"
    assert staleness.newest_release == "v0.1.51"
    assert staleness.newest_release_deployed is False
