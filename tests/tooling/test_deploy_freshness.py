"""AC-runtime.deploy-freshness.1: a deployed environment serving days-old work is red.

Production v0.1.50 reached users on 2026-09-10 through a door no workflow
measured; the last successful release.yml production run before it was v0.1.44
on 2026-07-19. The bound here is AGE rather than commit count on purpose, and
it is per environment: staging 3 days, production 7 days (promotion is
deliberate, so looser). The verdict is structured; these tests assert its
fields and one exact rendering, never fragments of prose.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta

import pytest

from common.runtime.deploy_freshness import (
    DEFAULT_MAX_AGE_DAYS,
    FRESH,
    LANE_IDLE,
    LANE_UNPROMOTED,
    LANE_UNTAGGED,
    REASON_HTTP,
    REASON_NO_IDENTITY,
    REASON_NOT_JSON,
    REASON_NOT_OBJECT,
    REASON_UNKNOWN_REF,
    REASON_UNSAFE_REF,
    STALE,
    UNMEASURABLE,
    FreshnessError,
    Staleness,
    check_freshness,
    evaluate,
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
    assert (recent.kind, recent.undeployed_commits) == (FRESH, 10)

    old = judge(_staleness(timedelta(days=9, hours=3), 1), bound)
    assert (old.kind, old.deployed_ref, old.max_age) == (STALE, "v0.1.50", bound)
    assert old.oldest_undeployed_age == timedelta(days=9, hours=3)
    assert old.oldest_undeployed_subject == "the one that has been invisible"


def test_the_stale_verdict_renders_everything_an_operator_needs() -> None:
    """Which release, how far behind, which commit, which door -- one exact line."""
    old = judge(_staleness(timedelta(days=9, hours=3), 1), timedelta(days=7))
    assert old.summary == (
        "production is stale: it serves v0.1.50 while 1 commit(s) on main are not "
        "deployed there, the oldest merged 9d3h ago (limit 7d) -- "
        "'the one that has been invisible'. v0.1.50 is the newest release cut from "
        "main, so the undeployed commits have no release yet (the release lane is "
        "idle). Finished work is invisible to every user of production until a "
        "release carries it."
    )


def test_nothing_undeployed_is_current() -> None:
    verdict = judge(_staleness(None, 0), timedelta(days=3))
    assert (verdict.kind, verdict.undeployed_commits) == (FRESH, 0)
    assert verdict.summary == (
        "production is current: serving v0.1.50, nothing newer on main"
    )


def test_the_bound_is_inclusive_at_exactly_the_limit() -> None:
    limit = timedelta(days=3)
    assert judge(_staleness(limit, 1), limit).kind == FRESH
    assert judge(_staleness(limit + timedelta(seconds=1), 1), limit).kind == STALE


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
    assert (staging.kind, production.kind) == (STALE, FRESH)


def test_the_verdict_names_which_door_the_work_waits_behind() -> None:
    old, limit = timedelta(days=10), timedelta(days=7)
    assert judge(_staleness(old, 3), limit).lane == LANE_IDLE

    unpromoted = judge(
        _staleness(old, 3, newest_release="v0.1.52", newest_release_deployed=False),
        limit,
    )
    assert (unpromoted.lane, unpromoted.newest_release) == (LANE_UNPROMOTED, "v0.1.52")

    assert judge(_staleness(old, 3, newest_release=""), limit).lane == LANE_UNTAGGED


# ── the release identity ────────────────────────────────────────────────────


def test_identity_prefers_git_sha_then_version() -> None:
    assert identity_from_body('{"git_sha": "v0.1.50", "version": "x"}') == "v0.1.50"
    assert identity_from_body('{"version": "v0.1.50"}') == "v0.1.50"


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ("{}", REASON_NO_IDENTITY),
        ('{"git_sha": "unknown"}', REASON_NO_IDENTITY),
        ('{"git_sha": ""}', REASON_NO_IDENTITY),
        ("[]", REASON_NOT_OBJECT),
        ("not json", REASON_NOT_JSON),
    ],
)
def test_identity_rejects_the_unjudgeable(body: str, reason: str) -> None:
    with pytest.raises(FreshnessError) as excinfo:
        identity_from_body(body)
    assert excinfo.value.reason == reason


# ── the whole check, with the environment and git faked ────────────────────


def test_current_environment_is_fresh() -> None:
    verdict = evaluate(
        URL,
        environment="production",
        http_get=_health("v0.1.50"),
        now=NOW,
        run=_git([], newest_release="v0.1.50"),
    )
    assert (verdict.kind, verdict.deployed_ref, verdict.undeployed_commits) == (
        FRESH,
        "v0.1.50",
        0,
    )


def test_the_real_gap_would_have_fired() -> None:
    """v0.1.44 served 53 days while main moved on -- the condition nothing measured."""
    verdict = evaluate(
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
    )
    assert (verdict.kind, verdict.undeployed_commits, verdict.lane) == (
        STALE,
        18,
        LANE_UNPROMOTED,
    )
    assert verdict.oldest_undeployed_age == timedelta(days=53)
    assert verdict.oldest_undeployed_subject == "the first invisible merge"
    assert (verdict.deployed_ref, verdict.newest_release) == ("v0.1.44", "v0.1.50")


def test_a_dispatch_override_replaces_the_environment_default() -> None:
    run = _git([f"{_ago(days=5)}\x1fa merge"], newest_release="v0.1.50")
    common = dict(http_get=_health("v0.1.50"), now=NOW, run=run)
    assert evaluate(URL, environment="production", **common).kind == FRESH
    overridden = evaluate(URL, environment="production", max_age_days=2, **common)
    assert (overridden.kind, overridden.max_age) == (STALE, timedelta(days=2))


@pytest.mark.parametrize(
    ("http_get", "reason"),
    [
        (_health("unknown"), REASON_NO_IDENTITY),
        (lambda _url: (503, "down"), REASON_HTTP),
        (lambda _url: (0, "connection refused"), REASON_HTTP),
    ],
)
def test_an_unjudgeable_environment_is_unmeasurable_not_stale(
    http_get, reason: str
) -> None:
    """The issue title must not claim staleness when nothing was measured."""
    verdict = evaluate(
        URL, environment="staging", http_get=http_get, now=NOW, run=_git([])
    )
    assert (verdict.kind, verdict.reason) == (UNMEASURABLE, reason)


def test_a_ref_this_checkout_cannot_resolve_is_unmeasurable() -> None:
    verdict = evaluate(
        URL,
        environment="production",
        http_get=_health("v9.9.9"),
        now=NOW,
        run=_git([], resolves=False),
    )
    assert (verdict.kind, verdict.reason) == (UNMEASURABLE, REASON_UNKNOWN_REF)


def test_a_ref_git_could_read_as_an_option_never_reaches_git() -> None:
    """The reported release arrives over HTTP; git must not be handed an option."""
    reached_git = False

    def run(argv, capture_output=True, text=True, check=False):  # noqa: ARG001
        nonlocal reached_git
        reached_git = True
        return subprocess.CompletedProcess(argv, 0, "", "")

    for hostile in ("--upload-pack=touch /tmp/x", "-n", "v1 --all", "a" * 300):
        verdict = evaluate(
            URL, environment="production", http_get=_health(hostile), now=NOW, run=run
        )
        assert (verdict.kind, verdict.reason) == (UNMEASURABLE, REASON_UNSAFE_REF), (
            f"{hostile!r} must be refused"
        )
    assert not reached_git


def test_check_freshness_exit_code_channel_and_outputs_follow_the_verdict(
    capsys: pytest.CaptureFixture[str],
) -> None:
    outputs: dict[str, str] = {}
    run = _git([f"{_ago(days=5)}\x1fa merge"], newest_release="v0.1.50")
    common = dict(http_get=_health("v0.1.50"), now=NOW, run=run)

    assert (
        check_freshness(
            URL, environment="production", github_output=outputs.update, **common
        )
        == 0
    )
    fresh = capsys.readouterr()
    expected = evaluate(URL, environment="production", **common)
    assert (outputs["verdict"], outputs["summary"]) == (FRESH, expected.summary)
    assert (fresh.out.strip(), fresh.err) == (expected.summary, "")

    assert (
        check_freshness(
            URL,
            environment="production",
            max_age_days=2,
            github_output=outputs.update,
            **common,
        )
        == 1
    )
    stale = capsys.readouterr()
    expected = evaluate(URL, environment="production", max_age_days=2, **common)
    assert (outputs["verdict"], outputs["summary"]) == (STALE, expected.summary)
    assert (stale.out, stale.err.strip()) == (
        "",
        f"freshness check failed: {expected.summary}",
    )


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
    assert (staleness.undeployed_commits, staleness.oldest_undeployed_subject) == (
        2,
        "first",
    )
    assert staleness.oldest_undeployed_age == timedelta(days=4)
    assert (staleness.newest_release, staleness.newest_release_deployed) == (
        "v0.1.51",
        False,
    )
