"""Lock: the e2e browser-invariant net subscribes to REAL BrowserContext events
so it can't silently go vacuous (#1623).

The invariant capture lives in tests/e2e/conftest.py as
``context.on("console", ...)`` / ``context.on("weberror", ...)``. Those ARE
valid BrowserContext events in the pinned Playwright (verified below), but a
future rename to an event BrowserContext does not emit (e.g. "pageerror", which
is a Page event) would make the whole net catch nothing while staying green —
the exact "safety net that silently degrades" failure this issue exists to stop.
This asserts the event names the fixture subscribes to are real context events.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFTEST = ROOT / "tests" / "e2e" / "conftest.py"

REQUIRED_EVENTS = {"console", "weberror"}

# Events Playwright's BrowserContext actually emits (playwright is not on the
# tooling job's path, so this is a static allowlist rather than an import).
# Notably: uncaught page errors surface as context "weberror" (NOT "pageerror",
# which is a Page-only event) and console messages as "console".
VALID_BROWSER_CONTEXT_EVENTS = frozenset(
    {
        "backgroundpage",
        "close",
        "console",
        "dialog",
        "download",
        "page",
        "request",
        "requestfailed",
        "requestfinished",
        "response",
        "serviceworker",
        "weberror",
    }
)


def _context_subscribed_events() -> set[str]:
    src = CONFTEST.read_text(encoding="utf-8")
    return set(re.findall(r'context\.on\(\s*"([a-z_]+)"', src))


def test_conftest_subscribes_to_the_invariant_events() -> None:
    missing = REQUIRED_EVENTS - _context_subscribed_events()
    assert not missing, (
        f"tests/e2e/conftest.py no longer subscribes context.on to {missing} — the "
        "browser correctness invariant would catch nothing while staying green."
    )


def test_subscribed_events_are_real_browser_context_events() -> None:
    for event in _context_subscribed_events():
        assert event in VALID_BROWSER_CONTEXT_EVENTS, (
            f"conftest subscribes context.on({event!r}) but BrowserContext does not "
            "emit it — the invariant is silently vacuous. Console/pageerror are Page "
            "events; use console/weberror on the context."
        )
