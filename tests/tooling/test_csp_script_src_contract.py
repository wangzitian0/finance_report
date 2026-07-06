"""Contract: the deployed CSP script-src must allow every external script host
the frontend actually loads (issue #1623).

A too-strict CSP silently kills a script the app depends on — e.g. the OpenPanel
analytics SDK (op1.js) was blocked because its host was missing from script-src,
so browser telemetry died with a console CSP violation that no test noticed. The
oracle here is the host the *code* references; adding a new external script host
without widening the CSP fails this contract.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NEXT_CONFIG = ROOT / "apps" / "frontend" / "next.config.mjs"
ANALYTICS = ROOT / "apps" / "frontend" / "src" / "components" / "Analytics.tsx"


def _script_src_hosts() -> str:
    text = NEXT_CONFIG.read_text(encoding="utf-8")
    m = re.search(r'"script-src ([^"]+)"', text)
    assert m, "no script-src directive found in next.config.mjs CSP"
    return m.group(1)


def _required_external_script_hosts() -> set[str]:
    """External hosts the frontend loads <script> from, derived from code."""
    hosts: set[str] = set()
    # OpenPanel SDK loads op1.js from the configured API host.
    m = re.search(
        r'DEFAULT_OPENPANEL_API_URL\s*=\s*"https://([^/"]+)',
        ANALYTICS.read_text(encoding="utf-8"),
    )
    if m:
        hosts.add(m.group(1))
    return hosts


def test_csp_script_src_allows_every_external_script_host() -> None:
    directive = _script_src_hosts()
    required = _required_external_script_hosts()
    assert required, "expected to derive at least the OpenPanel script host from code"
    for host in required:
        allowed = (
            f"https://{host}" in directive
            or f"https://*.{host.split('.', 1)[1]}" in directive  # wildcard parent
        )
        assert allowed, (
            f"CSP script-src does not allow script host {host!r} that the frontend "
            f"loads.\n  script-src: {directive}\n  Add https://{host} (or the "
            "wildcard parent) to next.config.mjs, or the browser will block the script."
        )
