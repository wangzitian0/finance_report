'AC-testing.e2e-path-quality.1'; from __future__ import annotations; import ssl; import time; import urllib.error; import urllib.request; from collections.abc import Callable, Iterable; from dataclasses import dataclass; SAMPLE_COUNT = 6; SAMPLE_TIMEOUT_SECONDS = 5.0; SAMPLE_BUDGET_SECONDS = SAMPLE_COUNT * SAMPLE_TIMEOUT_SECONDS; HANDSHAKE_USER_AGENT = 'E2E-Handshake/1.0'
@dataclass(frozen=True)
class SampleFailure: reason: str
Sample = str | None | SampleFailure
@dataclass(frozen=True)
class PathVerdict: samples: int; failures: int; locations: frozenset[str]; stable: bool
def edge_location(cf_ray: str | None) -> str | None:
    if not cf_ray: return None
    _, separator, location = cf_ray.strip().rpartition('-')
    if not separator or not location: return None
    return location.upper()
def assess_path(samples: Iterable[Sample]) -> PathVerdict: taken = list(samples); failures = sum((isinstance(sample, SampleFailure) for sample in taken)); locations = frozenset((sample for sample in taken if isinstance(sample, str))); stable = bool(taken) and failures == 0 and (len(locations) <= 1); return PathVerdict(samples=len(taken), failures=failures, locations=locations, stable=stable)
def format_path_quality_line(verdict: PathVerdict) -> str:
    if verdict.samples == 0: return 'WARNING e2e path quality: 0 samples were taken, so the path quality is unknown. A transport error (ReadError, connect timeout) in this run may come from the network path (#2911).'
    if verdict.stable: place = f"edge location {', '.join(sorted(verdict.locations))}" if verdict.locations else 'no cf-ray header'; return f'e2e path quality: {verdict.samples} new connections, {verdict.failures} failed, {place}'
    seen = ', '.join(sorted(verdict.locations)) or 'none'; return f'WARNING e2e path quality: the path to the target is not stable. Edge locations seen: {seen}. Failures: {verdict.failures} of {verdict.samples} new connections. A transport error (ReadError, connect timeout) in this run has this path as its probable cause (#2911).'
def make_cf_ray_fetcher(url: str, context: ssl.SSLContext, timeout: float=SAMPLE_TIMEOUT_SECONDS) -> Callable[[], str | None]:
    def fetch() -> str | None:
        request = urllib.request.Request(url, headers={'User-Agent': HANDSHAKE_USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=context) as response: return response.headers.get('cf-ray')
        except urllib.error.HTTPError as error:
            try: return error.headers.get('cf-ray')
            finally: error.close()
    return fetch
def collect_samples(fetch: Callable[[], str | None], count: int=SAMPLE_COUNT, *, budget_seconds: float=SAMPLE_BUDGET_SECONDS, clock: Callable[[], float]=time.monotonic) -> list[Sample]:
    samples: list[Sample] = []; started = clock()
    for _ in range(count):
        if clock() - started >= budget_seconds: break
        try: samples.append(edge_location(fetch()))
        except Exception as exc: samples.append(SampleFailure(type(exc).__name__))
    return samples
def report_path_quality(url: str, context: ssl.SSLContext, emit: Callable[[str], None], *, fetch: Callable[[], str | None] | None=None) -> PathVerdict: fetch = fetch or make_cf_ray_fetcher(url, context); verdict = assess_path(collect_samples(fetch)); emit(format_path_quality_line(verdict)); return verdict
