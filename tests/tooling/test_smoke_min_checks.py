"""Smoke meta-guard: a silently-empty smoke (0 / too-few checks) must not report green.

This is the connectivity-layer guard for CF-C ("smoke runs 0 checks and exits 0") and the
CF-B tail ("checks deleted/commented down to nothing"). Business-correctness belongs to
e2e, not here (see finance_report#1505) — this only ensures the smoke can't *silently
pass while empty*.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SMOKE = ROOT / "tools/_lib/shell/smoke_test.sh"
DEFAULT_MIN_CHECKS = 12  # must match the MIN_CHECKS default in smoke_test.sh


def _real_check_calls() -> int:
    text = SMOKE.read_text(encoding="utf-8")
    return len(re.findall(r'^\s*(?:check_endpoint|wait_for_endpoint)\s+"', text, re.M))


def test_smoke_has_at_least_the_default_minimum_checks() -> None:
    # Guards two things at once: the default MIN_CHECKS can't exceed the real check count
    # (so a healthy smoke never false-positives), and nobody can delete/comment checks down
    # below the floor without this test going red.
    assert _real_check_calls() >= DEFAULT_MIN_CHECKS, (
        f"only {_real_check_calls()} real smoke checks; add checks or lower MIN_CHECKS"
    )


def test_undersized_smoke_refuses_to_report_green() -> None:
    # Behavioral counterfactual: force MIN_CHECKS above the real count -> smoke must exit
    # non-zero with the silently-empty message. The count guard runs before the FAILED
    # check, so this fires even though the URL is unreachable (proves the guard itself works,
    # not just that an unreachable URL fails).
    result = subprocess.run(
        ["bash", str(SMOKE), "http://127.0.0.1:1", "staging"],
        env={**os.environ, "MIN_CHECKS": "999", "SMOKE_READY_ATTEMPTS": "1", "SMOKE_READY_SLEEP_SECONDS": "0"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert "silently-empty" in (result.stdout + result.stderr)
