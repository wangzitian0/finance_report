"""AC-testing.benchmarks.5: the legacy `--cassette` CLI flag selects the runner replay mode.

This file names the flag, so no AC anchors a test here (the testing package is CODE-ONLY).
"""

from __future__ import annotations


def test_benchmark_cli_cassette_option_parsing() -> None:
    """Benchmark CLI supports --cassette=replay and propagates to runner."""
    from tools._lib.benchmarks.run_financial_scenario_benchmark import (
        ScenarioBenchmarkRunner,
        _parse_args,
    )

    parsed = _parse_args(["--cassette", "replay", "--app-url", "http://localhost:8000"])
    assert parsed.cassette == "replay"

    runner = ScenarioBenchmarkRunner(
        base_url="http://localhost:8000", replay_mode=parsed.cassette
    )
    assert runner.replay_mode == "replay"
    # One name per fact: the retired alias must not return.
    assert not hasattr(runner, "cassette_mode")
