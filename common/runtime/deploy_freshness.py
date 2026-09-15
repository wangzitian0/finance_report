"""Fail when a deployed Finance Report environment serves work that finished days ago.

Production ``v0.1.50`` reached users on 2026-09-10 through a door no workflow
measured; the last successful ``release.yml`` production run before it was
``v0.1.44`` on 2026-07-19. Nothing in this repository was red in between,
because no check was ever about how old what a user sees is. This is that
check, modelled on truealpha's ``tools/deploy_freshness.py`` (truealpha#560).

The bound is AGE, not commit count, deliberately: a count measures how busy the
repository has been, age measures how long finished work has been invisible.
Ten commits merged this morning are not a problem; one commit merged last week
is. The bound is per environment: staging should follow ``main`` within days,
while production is promoted deliberately by the owner through ``release.yml``,
so its bound is looser -- but it is a bound, not an exemption.

Two facts are measured against ``origin/main`` for the release the environment
reports on ``/api/health``: how many commits on ``main`` are not deployed there
and how old the oldest of them is, and whether the newest ``vX.Y.Z`` tag cut
from ``main`` is the deployed one (release lane idle) or is cut but not promoted
(promotion pending). The outcome is a structured :class:`Verdict`; its one-line
``summary`` is rendered from those fields so the operator knows which door to
open without opening a shell.

Usage:
  python tools/deploy_freshness.py <health_url> --environment {production,staging}
      [--max-age-days N] [--repo PATH]

Exit codes:
  0 - fresh: nothing undeployed, or everything undeployed is younger than the bound
  1 - stale, or unmeasurable (unreachable, no release identity, unknown ref)

When ``GITHUB_OUTPUT`` is set, ``verdict`` (``fresh`` / ``stale`` / ``unmeasurable``)
and the one-line ``summary`` are written so the workflow's escalation step can
title the tracking issue by what actually happened.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from infra2_sdk.deploy_health import HttpGet, default_http_get

from common.runtime.github_api import write_github_output

#: Per-environment bounds. Staging is the integration surface and should follow
#: main within days; production is promoted deliberately by the owner, so its
#: bound is looser. Both are explicit so neither is "whatever the other is".
DEFAULT_MAX_AGE_DAYS: dict[str, int] = {"staging": 3, "production": 7}
#: Bound for an environment name this module has no opinion about.
FALLBACK_MAX_AGE_DAYS = 3

#: Health payload keys that may carry the release identity, in preference order.
VERSION_KEYS = ("git_sha", "version")
_RELEASE_TAG = re.compile(r"^v\d+\.\d+\.\d+$")
# The identity arrives over HTTP and is handed to git, where a leading "-" is
# read as an option and whitespace makes the failure non-deterministic.
_SAFE_REF = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._/-]{0,199}$")
_NEWEST_RELEASE_MATCH = "v[0-9]*.[0-9]*.[0-9]*"

Runner = Callable[..., subprocess.CompletedProcess[str]]

#: Verdict kinds. The workflow titles its tracking issue by this.
FRESH = "fresh"
STALE = "stale"
UNMEASURABLE = "unmeasurable"

#: Why a measurement was impossible (``Verdict.reason`` when ``UNMEASURABLE``).
REASON_HTTP = "http"
REASON_NOT_JSON = "not_json"
REASON_NOT_OBJECT = "not_object"
REASON_NO_IDENTITY = "no_identity"
REASON_UNSAFE_REF = "unsafe_ref"
REASON_UNKNOWN_REF = "unknown_ref"
REASON_GIT = "git"

#: Which door the undeployed work is waiting behind (``Verdict.lane``).
LANE_IDLE = "idle"  # the newest tag IS deployed: nothing has been cut since
LANE_UNPROMOTED = "unpromoted"  # a newer tag exists; this environment lacks it
LANE_UNTAGGED = "untagged"  # no vX.Y.Z tag is reachable from main at all


class FreshnessError(RuntimeError):
    """Freshness could not be measured; no verdict about staleness is possible."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Staleness:
    """How far behind ``origin/main`` one environment's deployed release is."""

    environment: str
    deployed_ref: str
    #: Newest ``vX.Y.Z`` tag reachable from ``origin/main`` ("" when none).
    newest_release: str
    #: Whether the deployed commit IS the newest release's commit.
    newest_release_deployed: bool
    undeployed_commits: int
    oldest_undeployed_age: timedelta | None
    oldest_undeployed_subject: str


@dataclass(frozen=True)
class Verdict:
    """The check's structured outcome; ``summary`` is rendered from it, never hand-built."""

    kind: str
    environment: str
    deployed_ref: str = ""
    newest_release: str = ""
    lane: str = ""
    undeployed_commits: int = 0
    oldest_undeployed_age: timedelta | None = None
    oldest_undeployed_subject: str = ""
    max_age: timedelta | None = None
    reason: str = ""
    detail: str = ""

    @property
    def summary(self) -> str:
        return render(self)


def max_age_for(environment: str, max_age_days: int | None = None) -> timedelta:
    """The bound for ``environment``: explicit override, else its default."""
    if max_age_days is None:
        max_age_days = DEFAULT_MAX_AGE_DAYS.get(environment, FALLBACK_MAX_AGE_DAYS)
    if max_age_days < 0:
        raise ValueError(f"max_age_days must be >= 0, got {max_age_days}")
    return timedelta(days=max_age_days)


def identity_from_body(body: str, *, url: str = "") -> str:
    """The release identity in a health payload, or raise ``FreshnessError``."""
    where = url or "the health endpoint"
    try:
        payload = json.loads(body)
    except (TypeError, ValueError) as exc:
        raise FreshnessError(
            REASON_NOT_JSON, f"{where} did not answer JSON: {body[:120]!r}"
        ) from exc
    if not isinstance(payload, dict):
        raise FreshnessError(
            REASON_NOT_OBJECT,
            f"{where} answered JSON that is not an object: {body[:120]!r}",
        )
    for key in VERSION_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value and value != "unknown":
            break
    else:
        raise FreshnessError(
            REASON_NO_IDENTITY,
            f"{where} does not report a release identity (body {body[:120]!r}); "
            "nothing about the deployed release can be judged",
        )
    if not _SAFE_REF.match(value):
        raise FreshnessError(
            REASON_UNSAFE_REF,
            f"{where} reports {value!r}, which is not a usable release identifier "
            "-- a leading '-' would be read by git as an option and whitespace makes "
            "the failure non-deterministic. This value is not used",
        )
    return value


def read_deployed_release(url: str, http_get: HttpGet) -> str:
    """Fetch ``url`` and return the release identity it reports, or raise."""
    status_code, body = http_get(url)
    if status_code != 200:
        raise FreshnessError(
            REASON_HTTP, f"{url} answered HTTP {status_code}; its release is unknown"
        )
    return identity_from_body(body, url=url)


def _git(
    args: Sequence[str], repo: str, run: Runner
) -> subprocess.CompletedProcess[str]:
    return run(["git", "-C", repo, *args], capture_output=True, text=True, check=False)


def _resolve_commit(ref: str, repo: str, run: Runner) -> str:
    result = _git(["rev-parse", "--verify", f"{ref}^{{commit}}"], repo, run)
    return result.stdout.strip() if result.returncode == 0 else ""


def measure(
    environment: str,
    deployed_ref: str,
    *,
    repo: str = ".",
    now: datetime | None = None,
    run: Runner = subprocess.run,
) -> Staleness:
    """Measure the deployed release against ``origin/main`` and its release tags."""
    deployed_commit = _resolve_commit(deployed_ref, repo, run)
    if not deployed_commit:
        raise FreshnessError(
            REASON_UNKNOWN_REF,
            f"{environment} reports {deployed_ref!r}, which is not a commit here -- "
            "fetch tags, or check that the environment reports a ref this repository knows",
        )

    described = _git(
        [
            "describe",
            "--tags",
            "--abbrev=0",
            "--match",
            _NEWEST_RELEASE_MATCH,
            "origin/main",
        ],
        repo,
        run,
    )
    newest_release = described.stdout.strip() if described.returncode == 0 else ""
    if newest_release and not _RELEASE_TAG.match(newest_release):
        newest_release = ""
    newest_release_deployed = bool(newest_release) and (
        _resolve_commit(newest_release, repo, run) == deployed_commit
    )

    log = _git(
        ["log", "--reverse", "--format=%cI%x1f%s", f"{deployed_ref}..origin/main"],
        repo,
        run,
    )
    if log.returncode != 0:
        raise FreshnessError(
            REASON_GIT,
            f"git log {deployed_ref}..origin/main failed: {log.stderr.strip()}",
        )
    lines = [line for line in log.stdout.splitlines() if line]
    if not lines:
        return Staleness(
            environment,
            deployed_ref,
            newest_release,
            newest_release_deployed,
            0,
            None,
            "",
        )
    oldest_iso, _, subject = lines[0].partition("\x1f")
    oldest = datetime.fromisoformat(oldest_iso)
    reference = now or datetime.now(UTC)
    return Staleness(
        environment,
        deployed_ref,
        newest_release,
        newest_release_deployed,
        len(lines),
        reference - oldest,
        subject,
    )


def judge(staleness: Staleness, max_age: timedelta) -> Verdict:
    """The pure comparison: age of the oldest undeployed commit against the bound."""
    if not staleness.newest_release:
        lane = LANE_UNTAGGED
    elif staleness.newest_release_deployed:
        lane = LANE_IDLE
    else:
        lane = LANE_UNPROMOTED
    age = staleness.oldest_undeployed_age
    stale = staleness.undeployed_commits > 0 and age is not None and age > max_age
    return Verdict(
        kind=STALE if stale else FRESH,
        environment=staleness.environment,
        deployed_ref=staleness.deployed_ref,
        newest_release=staleness.newest_release,
        lane=lane,
        undeployed_commits=staleness.undeployed_commits,
        oldest_undeployed_age=age,
        oldest_undeployed_subject=staleness.oldest_undeployed_subject,
        max_age=max_age,
    )


def _lane_sentence(verdict: Verdict) -> str:
    if verdict.lane == LANE_UNTAGGED:
        return "No vX.Y.Z release tag is reachable from main."
    if verdict.lane == LANE_IDLE:
        return (
            f"{verdict.newest_release} is the newest release cut from main, so the "
            "undeployed commits have no release yet (the release lane is idle)."
        )
    return (
        f"{verdict.newest_release} is cut from main but not promoted to "
        f"{verdict.environment}."
    )


def render(verdict: Verdict) -> str:
    """One line an operator can act on without opening a shell."""
    env, ref = verdict.environment, verdict.deployed_ref
    if verdict.kind == UNMEASURABLE:
        return f"{env} freshness is unmeasurable ({verdict.reason}): {verdict.detail}"
    if verdict.undeployed_commits == 0:
        return f"{env} is current: serving {ref}, nothing newer on main"
    age, limit = verdict.oldest_undeployed_age, verdict.max_age
    assert age is not None and limit is not None
    count, lane = verdict.undeployed_commits, _lane_sentence(verdict)
    if verdict.kind == STALE:
        return (
            f"{env} is stale: it serves {ref} while {count} commit(s) on main are not "
            f"deployed there, the oldest merged {age.days}d{age.seconds // 3600}h ago "
            f"(limit {limit.days}d) -- {verdict.oldest_undeployed_subject[:80]!r}. "
            f"{lane} Finished work is invisible to every user of {env} until a "
            "release carries it."
        )
    return (
        f"{env} is fresh enough: serving {ref}, {count} commit(s) not yet deployed, "
        f"oldest {age.days}d (limit {limit.days}d). {lane}"
    )


def evaluate(
    url: str,
    *,
    environment: str,
    max_age_days: int | None = None,
    repo: str = ".",
    http_get: HttpGet | None = None,
    now: datetime | None = None,
    run: Runner = subprocess.run,
) -> Verdict:
    """Read the environment, measure it, judge it; never raises for a measurable reason."""
    http_get = http_get or default_http_get()
    max_age = max_age_for(environment, max_age_days)
    try:
        deployed_ref = read_deployed_release(url, http_get)
        staleness = measure(environment, deployed_ref, repo=repo, now=now, run=run)
    except FreshnessError as exc:
        return Verdict(
            kind=UNMEASURABLE,
            environment=environment,
            max_age=max_age,
            reason=exc.reason,
            detail=str(exc),
        )
    return judge(staleness, max_age)


def check_freshness(
    url: str,
    *,
    environment: str,
    max_age_days: int | None = None,
    repo: str = ".",
    http_get: HttpGet | None = None,
    now: datetime | None = None,
    run: Runner = subprocess.run,
    github_output: Callable[[dict[str, str]], None] = write_github_output,
) -> int:
    """Evaluate and report; the shell exit code is the verdict."""
    verdict = evaluate(
        url,
        environment=environment,
        max_age_days=max_age_days,
        repo=repo,
        http_get=http_get,
        now=now,
        run=run,
    )
    github_output({"verdict": verdict.kind, "summary": verdict.summary})
    if verdict.kind == FRESH:
        print(verdict.summary)
        return 0
    print(f"freshness check failed: {verdict.summary}", file=sys.stderr)
    return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail when a deployed environment serves work that finished days ago."
    )
    parser.add_argument("url", help="the environment's /api/health URL")
    parser.add_argument(
        "--environment",
        required=True,
        help="human name used in messages and to pick the default bound "
        f"({', '.join(f'{k}={v}d' for k, v in DEFAULT_MAX_AGE_DAYS.items())})",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=None,
        help="fail when the oldest undeployed commit is older than this "
        "(default: the environment's bound)",
    )
    parser.add_argument(
        "--repo", default=".", help="checkout with tags and origin/main"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return check_freshness(
        args.url,
        environment=args.environment,
        max_age_days=args.max_age_days,
        repo=args.repo,
    )
