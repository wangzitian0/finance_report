"""AC-testing.e2e-path-quality.1: the e2e session start reports the quality of the network path (#2911).

The route from a client network to a CDN address can move between edge locations. A live connection
then closes, and a new connection can time out. One request at session start does not show that.
The session start opens 6 new connections and prints one line. No test here opens a network connection.
"""

from __future__ import annotations

import email.message
import importlib
import json
import ssl
import sys
import urllib.error
from dataclasses import dataclass, field
from types import ModuleType, SimpleNamespace

import pytest

HEALTH_BASE = "https://staging.example.test"
HEALTH_URL = f"{HEALTH_BASE}/api/health"
SHA = "0123456789abcdef0123456789abcdef01234567"


def _pq() -> ModuleType:
    # Import inside the test body: a missing module fails the test, not the collection.
    return importlib.import_module("tests.e2e.path_quality")


def _ray(location: str) -> str:
    return f"8a1b2c3d4e5f6a7b-{location}"


# ── verdict ─────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("cf_ray", "expected"),
    [
        ("8a1b2c3d4e5f6a7b-SIN", "SIN"),
        ("8a1b2c3d4e5f6a7b-sjc", "SJC"),
        (None, None),
        ("", None),
        ("8a1b2c3d4e5f6a7b", None),
        ("8a1b2c3d4e5f6a7b-", None),
    ],
)
def test_AC_testing_e2e_path_quality_1_the_edge_location_is_the_suffix_of_the_cf_ray_header(
    cf_ray, expected
):
    assert _pq().edge_location(cf_ray) == expected


def test_AC_testing_e2e_path_quality_1_a_second_edge_location_or_one_failure_shows_instability():
    pq = _pq()
    failure = pq.SampleFailure("TimeoutError")

    same = pq.assess_path(["SIN"] * 6)
    two_locations = pq.assess_path(["SIN"] * 5 + ["MRS"])
    one_failure = pq.assess_path(["SIN"] * 5 + [failure])
    only_failures = pq.assess_path([failure, failure])

    assert (same.samples, same.failures, same.locations, same.stable) == (
        6,
        0,
        frozenset({"SIN"}),
        True,
    )
    assert (
        two_locations.samples,
        two_locations.failures,
        two_locations.locations,
        two_locations.stable,
    ) == (6, 0, frozenset({"SIN", "MRS"}), False)
    assert (one_failure.samples, one_failure.failures, one_failure.stable) == (
        6,
        1,
        False,
    )
    assert one_failure.locations == frozenset({"SIN"})
    assert (only_failures.failures, only_failures.stable) == (2, False)


def test_AC_testing_e2e_path_quality_1_a_target_without_a_cf_ray_header_and_without_failure_shows_no_instability():
    verdict = _pq().assess_path([None] * 6)

    assert verdict.stable is True
    assert verdict.locations == frozenset()
    assert verdict.failures == 0


def test_AC_testing_e2e_path_quality_1_a_response_without_a_header_does_not_add_a_location():
    verdict = _pq().assess_path(["SIN", None, "SIN"])

    assert verdict.stable is True
    assert verdict.locations == frozenset({"SIN"})


def test_AC_testing_e2e_path_quality_1_an_empty_sample_list_is_not_a_pass():
    verdict = _pq().assess_path([])

    assert (verdict.samples, verdict.failures, verdict.locations) == (0, 0, frozenset())
    assert verdict.stable is False


# ── printed line ────────────────────────────────────────────────────────────────────────────────


def test_AC_testing_e2e_path_quality_1_seen_instability_prints_a_warning_with_locations_and_failures():
    pq = _pq()
    verdict = pq.assess_path(
        ["SIN", "SIN", "MRS", pq.SampleFailure("TimeoutError"), "SJC", "SIN"]
    )

    line = pq.format_path_quality_line(verdict)

    assert line.startswith("WARNING")
    assert "\n" not in line
    assert "MRS, SIN, SJC" in line
    assert "1 of 6" in line
    assert "ReadError" in line
    assert "connect timeout" in line
    assert "#2911" in line


def test_AC_testing_e2e_path_quality_1_a_pass_prints_one_fact_line_without_a_warning_and_without_the_word_stable():
    pq = _pq()

    line = pq.format_path_quality_line(pq.assess_path(["SIN"] * 6))
    plain = pq.format_path_quality_line(pq.assess_path([None] * 6))

    assert line == "e2e path quality: 6 new connections, 0 failed, edge location SIN"
    assert plain == "e2e path quality: 6 new connections, 0 failed, no cf-ray header"
    # Six samples in a calm minute say nothing about the next minute: a pass line states facts only.
    assert "WARNING" not in line + plain
    assert "stable" not in (line + plain).lower()


def test_AC_testing_e2e_path_quality_1_an_empty_sample_list_prints_a_warning():
    pq = _pq()

    line = pq.format_path_quality_line(pq.assess_path([]))

    assert line.startswith("WARNING")
    assert "0 samples" in line


# ── sampler ─────────────────────────────────────────────────────────────────────────────────────


def test_AC_testing_e2e_path_quality_1_the_sampler_never_raises_and_records_each_error_as_a_failure():
    pq = _pq()
    outcomes = iter(
        [
            _ray("SIN"),
            TimeoutError("timed out"),
            ssl.SSLError("handshake"),
            ValueError("bad url"),
            7,  # a value that edge_location cannot read raises inside the sample
            _ray("SIN"),
        ]
    )

    def fetch():
        outcome = next(outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    samples = pq.collect_samples(fetch)
    verdict = pq.assess_path(samples)

    assert len(samples) == 6
    assert samples[0] == "SIN"
    assert samples[5] == "SIN"
    assert [type(sample).__name__ for sample in samples[1:5]] == ["SampleFailure"] * 4
    assert samples[1] == pq.SampleFailure("TimeoutError")
    assert (verdict.samples, verdict.failures, verdict.stable) == (6, 4, False)


def test_AC_testing_e2e_path_quality_1_the_sampler_does_not_swallow_a_keyboard_interrupt():
    def fetch():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _pq().collect_samples(fetch)


def test_AC_testing_e2e_path_quality_1_the_sampler_stops_when_the_time_budget_is_used():
    pq = _pq()
    now = [0.0]
    calls = []

    def fetch():
        calls.append(now[0])
        now[0] += 5.0
        return _ray("SIN")

    samples = pq.collect_samples(
        fetch, count=6, budget_seconds=12.0, clock=lambda: now[0]
    )

    assert calls == [0.0, 5.0, 10.0]
    assert samples == ["SIN", "SIN", "SIN"]


def test_AC_testing_e2e_path_quality_1_the_sample_count_and_timeout_are_6_and_5_seconds():
    pq = _pq()

    assert pq.SAMPLE_COUNT == 6
    assert pq.SAMPLE_TIMEOUT_SECONDS == 5.0
    assert pq.HANDSHAKE_USER_AGENT == "E2E-Handshake/1.0"


@dataclass
class _FakeResponse:
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b"{}"

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc) -> bool:
        return False

    def read(self) -> bytes:
        return self.body


def _install_urlopen(monkeypatch: pytest.MonkeyPatch, outcomes: list) -> list:
    """Replace urllib's urlopen with a scripted fake. Return the list of recorded calls."""
    calls: list[SimpleNamespace] = []

    def fake_urlopen(request, timeout=None, context=None):
        calls.append(
            SimpleNamespace(
                url=request.full_url,
                timeout=timeout,
                context=context,
                user_agent=request.get_header("User-agent"),
            )
        )
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return calls


def test_AC_testing_e2e_path_quality_1_the_fetcher_opens_a_new_request_with_the_handshake_user_agent(
    monkeypatch,
):
    pq = _pq()
    context = ssl.create_default_context()
    calls = _install_urlopen(
        monkeypatch, [_FakeResponse({"cf-ray": _ray("SIN")}), _FakeResponse()]
    )
    fetch = pq.make_cf_ray_fetcher(HEALTH_URL, context)

    assert fetch() == _ray("SIN")
    assert fetch() is None
    assert [(c.url, c.timeout, c.user_agent) for c in calls] == [
        (HEALTH_URL, 5.0, "E2E-Handshake/1.0")
    ] * 2
    assert all(call.context is context for call in calls)


def test_AC_testing_e2e_path_quality_1_an_http_error_status_still_gives_the_edge_location(
    monkeypatch,
):
    headers = email.message.Message()
    headers["cf-ray"] = _ray("MRS")
    error = urllib.error.HTTPError(HEALTH_URL, 503, "unavailable", headers, None)
    _install_urlopen(monkeypatch, [error])

    fetch = _pq().make_cf_ray_fetcher(HEALTH_URL, ssl.create_default_context())

    assert fetch() == _ray("MRS")


# ── wiring in the session start ─────────────────────────────────────────────────────────────────


class _Reporter:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write_line(self, line: str, **_kwargs) -> None:
        self.lines.append(line)


def _session(reporter: _Reporter | None) -> SimpleNamespace:
    plugins = {"terminalreporter": reporter} if reporter is not None else {}
    return SimpleNamespace(
        config=SimpleNamespace(
            pluginmanager=SimpleNamespace(get_plugin=lambda name: plugins.get(name))
        )
    )


def _load_e2e_conftest(monkeypatch: pytest.MonkeyPatch, *, test_env: str) -> ModuleType:
    playwright_module = ModuleType("playwright")
    async_api_module = ModuleType("playwright.async_api")
    for name in ("Browser", "BrowserContext", "Page"):
        setattr(async_api_module, name, type(name, (), {}))
    setattr(async_api_module, "async_playwright", lambda: None)
    setattr(playwright_module, "async_api", async_api_module)
    monkeypatch.setitem(sys.modules, "playwright", playwright_module)
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api_module)
    monkeypatch.setenv("STRICT_E2E_GATES", "true")
    monkeypatch.delenv("E2E_INSECURE_TLS", raising=False)
    sys.modules.pop("tests.e2e.conftest", None)
    conftest = importlib.import_module("tests.e2e.conftest")
    monkeypatch.setattr(conftest.TestConfig, "TEST_ENV", test_env)
    monkeypatch.setattr(conftest.TestConfig, "EXPECTED_SHA", SHA)
    monkeypatch.setattr(conftest.TestConfig, "APP_URL", HEALTH_BASE)
    return conftest


def _handshake(git_sha: str = SHA) -> _FakeResponse:
    return _FakeResponse(body=json.dumps({"git_sha": git_sha}).encode("utf-8"))


def test_AC_testing_e2e_path_quality_1_session_start_prints_one_fact_line_after_the_handshake(
    monkeypatch,
):
    conftest = _load_e2e_conftest(monkeypatch, test_env="staging")
    calls = _install_urlopen(
        monkeypatch, [_handshake()] + [_FakeResponse({"cf-ray": _ray("SIN")})] * 6
    )
    reporter = _Reporter()

    conftest.pytest_sessionstart(_session(reporter))

    assert reporter.lines == [
        "e2e path quality: 6 new connections, 0 failed, edge location SIN"
    ]
    # One handshake request and exactly 6 sample requests, on the URL and context of the handshake.
    assert len(calls) == 7
    assert {call.url for call in calls} == {HEALTH_URL}
    assert {call.timeout for call in calls[1:]} == {5.0}
    assert all(call.context is calls[0].context for call in calls)


def test_AC_testing_e2e_path_quality_1_session_start_warns_and_continues_when_instability_is_seen(
    monkeypatch,
):
    conftest = _load_e2e_conftest(monkeypatch, test_env="staging")
    samples = [
        _FakeResponse({"cf-ray": _ray("SIN")}),
        TimeoutError("timed out"),
        _FakeResponse({"cf-ray": _ray("MRS")}),
        _FakeResponse({"cf-ray": _ray("SIN")}),
        _FakeResponse({"cf-ray": _ray("SIN")}),
        _FakeResponse({"cf-ray": _ray("SIN")}),
    ]
    _install_urlopen(monkeypatch, [_handshake()] + samples)
    reporter = _Reporter()

    result = conftest.pytest_sessionstart(_session(reporter))  # must not exit or raise

    assert result is None
    assert len(reporter.lines) == 1
    assert reporter.lines[0].startswith("WARNING")
    assert "MRS, SIN" in reporter.lines[0]
    assert "1 of 6" in reporter.lines[0]


def test_AC_testing_e2e_path_quality_1_session_start_prints_to_stderr_without_a_terminal_reporter(
    monkeypatch, capsys
):
    conftest = _load_e2e_conftest(monkeypatch, test_env="staging")
    _install_urlopen(
        monkeypatch, [_handshake()] + [_FakeResponse({"cf-ray": _ray("SIN")})] * 6
    )

    conftest.pytest_sessionstart(_session(None))

    captured = capsys.readouterr()
    assert captured.err.splitlines() == [
        "e2e path quality: 6 new connections, 0 failed, edge location SIN"
    ]


def test_AC_testing_e2e_path_quality_1_a_local_target_takes_no_sample(monkeypatch):
    conftest = _load_e2e_conftest(monkeypatch, test_env="local")
    calls = _install_urlopen(monkeypatch, [])
    reporter = _Reporter()

    conftest.pytest_sessionstart(_session(reporter))

    assert calls == []
    assert reporter.lines == []


def test_AC_testing_e2e_path_quality_1_a_failed_handshake_takes_no_sample(monkeypatch):
    conftest = _load_e2e_conftest(monkeypatch, test_env="staging")
    calls = _install_urlopen(monkeypatch, [_handshake("f" * 40)])
    reporter = _Reporter()

    with pytest.raises(pytest.exit.Exception, match="Stale target environment"):
        conftest.pytest_sessionstart(_session(reporter))

    assert len(calls) == 1
    assert reporter.lines == []
