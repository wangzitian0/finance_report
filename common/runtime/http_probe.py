"""Shared HTTP primitives for deployed runtime probes."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree


@dataclass(frozen=True)
class HttpResponse:
    """Transport-neutral response used by runtime verification commands."""

    status_code: int
    body: str
    error: str | None = None

    @property
    def status(self) -> int:
        """Compatibility spelling for the production smoke call sites."""
        return self.status_code


Opener = Callable[..., object]


def request_http(
    url: str,
    timeout_seconds: float,
    *,
    user_agent: str = "finance-report-runtime-probe/1.0",
    opener: Opener = urllib.request.urlopen,
) -> HttpResponse:
    """Fetch one URL while preserving HTTP and transport failures as data."""
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with opener(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace")
            return HttpResponse(status_code=response.status, body=body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return HttpResponse(status_code=exc.code, body=body, error=str(exc))
    except urllib.error.URLError as exc:
        return HttpResponse(status_code=0, body="", error=str(exc.reason))


def _sha_matches(actual: str, expected: str) -> bool:
    """Match full or abbreviated SHAs, but never accept missing values."""
    return bool(actual and expected) and (
        actual == expected or actual.startswith(expected) or expected.startswith(actual)
    )


sha_matches = _sha_matches


def write_json_report(report: Mapping[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def write_junit_report(
    report: Mapping[str, object],
    path: Path,
    *,
    proof_tier: str = "tier2_http",
    suite_name: str = "tier2-http-e2e",
) -> None:
    """Render a runtime-probe result using the shared JUnit artifact shape."""
    checks = report.get("checks", [])
    if not isinstance(checks, list):
        checks = []
    failures = sum(
        1 for check in checks if isinstance(check, dict) and not check.get("passed")
    )
    skipped = 1 if report.get("status") == "not_run" else 0
    tests = len(checks) if checks else skipped

    suite = ElementTree.Element(
        "testsuite",
        {
            "name": suite_name,
            "tests": str(tests),
            "failures": str(failures),
            "skipped": str(skipped),
        },
    )
    properties = ElementTree.SubElement(suite, "properties")
    for key in ("proof_tier", "mode", "status", "proof_eligible", "env_gated"):
        ElementTree.SubElement(
            properties, "property", {"name": key, "value": str(report.get(key))}
        )

    if report.get("status") == "not_run":
        case = ElementTree.SubElement(
            suite, "testcase", {"classname": proof_tier, "name": "not_run"}
        )
        ElementTree.SubElement(
            case,
            "skipped",
            {"message": ",".join(report.get("missing_inputs", []))},
        )
    else:
        for check in checks:
            if not isinstance(check, dict):
                continue
            case = ElementTree.SubElement(
                suite,
                "testcase",
                {"classname": proof_tier, "name": str(check.get("name"))},
            )
            if not check.get("passed"):
                ElementTree.SubElement(
                    case, "failure", {"message": str(check.get("detail"))}
                )

    path.parent.mkdir(parents=True, exist_ok=True)
    ElementTree.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)
