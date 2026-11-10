"""AC-testing.e2e-path-quality.1: report the quality of the network path to the e2e target (#2911).

The route from a client network to a CDN address can move between edge locations.
A live connection then closes (httpx ReadError), and a new connection can time out.
The application is not involved. One request at session start does not show this.

The session start opens SAMPLE_COUNT new connections to the target health URL.
It reads the edge location from the suffix of the cf-ray response header.
The samples show instability when one connection failed or when the connections
reached more than one edge location. The session prints one line and continues.
Instability is a property of the client network, not of the product.

A clean result is a fact about the samples only. Six samples in a calm minute
say nothing about the next minute. The line for such samples states the counts
and the edge location, and it never uses the word stable.

This module uses only the standard library, like the target handshake.
"""

from __future__ import annotations

import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass

SAMPLE_COUNT = 6
SAMPLE_TIMEOUT_SECONDS = 5.0
# urllib applies the timeout to each socket operation, not to the whole request.
# The budget stops a run of slow samples after SAMPLE_COUNT * SAMPLE_TIMEOUT_SECONDS.
SAMPLE_BUDGET_SECONDS = SAMPLE_COUNT * SAMPLE_TIMEOUT_SECONDS
# The CDN rejects the default urllib user agent. The target handshake uses the same value.
HANDSHAKE_USER_AGENT = "E2E-Handshake/1.0"


@dataclass(frozen=True)
class SampleFailure:
    """One new connection that raised an error."""

    reason: str


# One sample per new connection: an edge location, None (no usable cf-ray header) or a failure.
Sample = str | None | SampleFailure


@dataclass(frozen=True)
class PathVerdict:
    """The result of the samples.

    `stable` is True only when the samples show no instability.
    It says nothing about connections that the session opens later.
    """

    samples: int
    failures: int
    locations: frozenset[str]
    stable: bool


def edge_location(cf_ray: str | None) -> str | None:
    """Return the edge location in a cf-ray header value, or None when there is none.

    A cf-ray value has the form `<16 hex characters>-<location code>`, for example `8a1b2c3d4e5f6a7b-SIN`.
    """
    if not cf_ray:
        return None
    _, separator, location = cf_ray.strip().rpartition("-")
    if not separator or not location:
        return None
    return location.upper()


def assess_path(samples: Iterable[Sample]) -> PathVerdict:
    """Decide whether the samples show instability.

    The samples show instability when one sample failed or when more than one edge location was seen.
    A list with no sample is not a pass: no measurement shows nothing.
    A target without a cf-ray header (no CDN) and without a failure shows no instability.
    """
    taken = list(samples)
    failures = sum(isinstance(sample, SampleFailure) for sample in taken)
    locations = frozenset(sample for sample in taken if isinstance(sample, str))
    stable = bool(taken) and failures == 0 and len(locations) <= 1
    return PathVerdict(
        samples=len(taken), failures=failures, locations=locations, stable=stable
    )


def format_path_quality_line(verdict: PathVerdict) -> str:
    """Return the one line that the session start prints."""
    if verdict.samples == 0:
        return (
            "WARNING e2e path quality: 0 samples were taken, so the path quality is unknown. "
            "A transport error (ReadError, connect timeout) in this run may come from the network path (#2911)."
        )
    if verdict.stable:
        place = (
            f"edge location {', '.join(sorted(verdict.locations))}"
            if verdict.locations
            else "no cf-ray header"
        )
        return (
            f"e2e path quality: {verdict.samples} new connections, "
            f"{verdict.failures} failed, {place}"
        )
    seen = ", ".join(sorted(verdict.locations)) or "none"
    return (
        "WARNING e2e path quality: the path to the target is not stable. "
        f"Edge locations seen: {seen}. "
        f"Failures: {verdict.failures} of {verdict.samples} new connections. "
        "A transport error (ReadError, connect timeout) in this run has this path as its probable cause (#2911)."
    )


def make_cf_ray_fetcher(
    url: str,
    context: ssl.SSLContext,
    timeout: float = SAMPLE_TIMEOUT_SECONDS,
) -> Callable[[], str | None]:
    """Return a function that opens one new connection to the URL and returns its cf-ray header value.

    urllib opens a new connection for each call. An HTTP error status shows that the connection worked,
    so the function returns the header of the error response too.
    """

    def fetch() -> str | None:
        request = urllib.request.Request(
            url, headers={"User-Agent": HANDSHAKE_USER_AGENT}
        )
        try:
            with urllib.request.urlopen(
                request, timeout=timeout, context=context
            ) as response:
                return response.headers.get("cf-ray")
        except urllib.error.HTTPError as error:
            try:
                return error.headers.get("cf-ray")
            finally:
                error.close()

    return fetch


def collect_samples(
    fetch: Callable[[], str | None],
    count: int = SAMPLE_COUNT,
    *,
    budget_seconds: float = SAMPLE_BUDGET_SECONDS,
    clock: Callable[[], float] = time.monotonic,
) -> list[Sample]:
    """Open `count` new connections one after the other. Never raise an Exception.

    An error in one sample becomes a SampleFailure. The function stops early
    when the time budget is used. KeyboardInterrupt and SystemExit pass through.
    """
    samples: list[Sample] = []
    started = clock()
    for _ in range(count):
        if clock() - started >= budget_seconds:
            break
        try:
            samples.append(edge_location(fetch()))
        except Exception as exc:  # noqa: BLE001 - every sample error is a data point
            samples.append(SampleFailure(type(exc).__name__))
    return samples


def report_path_quality(
    url: str,
    context: ssl.SSLContext,
    emit: Callable[[str], None],
    *,
    fetch: Callable[[], str | None] | None = None,
) -> PathVerdict:
    """Sample the path, emit one line and return the verdict. Never end the session."""
    fetch = fetch or make_cf_ray_fetcher(url, context)
    verdict = assess_path(collect_samples(fetch))
    emit(format_path_quality_line(verdict))
    return verdict
