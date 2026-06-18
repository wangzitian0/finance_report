"""Tests for the Tier 2 deployed HTTP E2E command."""

from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree

from tools import tier2_http_e2e

ROOT = Path(__file__).resolve().parents[2]


def test_AC8_18_1_tier2_http_command_fails_closed_without_deployed_inputs(capsys) -> None:
    """AC8.18.1: Tier 2 HTTP E2E requires deployed URL and expected version inputs."""
    status = tier2_http_e2e.main([], environ={})

    assert status == 2
    assert "base_url" in capsys.readouterr().err


def test_AC8_18_2_tier2_http_report_is_proof_tiered_and_skip_ineligible(tmp_path: Path) -> None:
    """AC8.18.2: Advisory/env-gated reports are explicit non-proof, not green proof."""
    report_path = tmp_path / "tier2.json"
    junit_path = tmp_path / "tier2.xml"

    status = tier2_http_e2e.main(
        [
            "--advisory-if-missing",
            "--json-report",
            str(report_path),
            "--junit-xml",
            str(junit_path),
        ],
        environ={},
    )

    assert status == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["proof_tier"] == "tier2_http"
    assert report["status"] == "not_run"
    assert report["proof_eligible"] is False
    assert report["env_gated"] is True

    suite = ElementTree.parse(junit_path).getroot()
    properties_node = suite.find("properties")
    assert properties_node is not None
    properties = {prop.attrib["name"]: prop.attrib["value"] for prop in properties_node}
    assert properties["proof_tier"] == "tier2_http"
    assert properties["proof_eligible"] == "False"
    assert suite.attrib["skipped"] == "1"


def test_AC8_18_2_tier2_http_success_report_requires_real_http_checks() -> None:
    """AC8.18.2: Passing reports come from concrete HTTP checks with no skipped tests."""

    def requester(url: str, _timeout_seconds: float) -> tier2_http_e2e.HttpResponse:
        if url.endswith("/api/health"):
            return tier2_http_e2e.HttpResponse(200, '{"status":"healthy","git_sha":"abc123"}')
        if url.endswith("/api/ping"):
            return tier2_http_e2e.HttpResponse(200, '{"ok":true}')
        if url.endswith("/api/statements"):
            return tier2_http_e2e.HttpResponse(401, '{"detail":"Not authenticated"}')
        return tier2_http_e2e.HttpResponse(200, "<html></html>")

    report = tier2_http_e2e.run_tier2_http_e2e(
        tier2_http_e2e.Tier2Config(
            base_url="https://report-staging.example.com",
            expected_sha="abc123",
        ),
        requester=requester,
    )

    assert report["proof_tier"] == "tier2_http"
    assert report["status"] == "passed"
    assert report["proof_eligible"] is True
    assert [check["name"] for check in report["checks"]] == [
        "api_health_http_200",
        "deployed_version_matches_expected",
        "api_ping_http_200",
        "frontend_http_success",
        "protected_api_requires_auth",
    ]


def test_AC8_18_2_tier2_http_handles_non_object_health_json() -> None:
    """AC8.18.2: Non-object health JSON fails the version check without crashing."""

    def requester(url: str, _timeout_seconds: float) -> tier2_http_e2e.HttpResponse:
        if url.endswith("/api/health"):
            return tier2_http_e2e.HttpResponse(200, "[]")
        if url.endswith("/api/ping"):
            return tier2_http_e2e.HttpResponse(200, '{"ok":true}')
        if url.endswith("/api/statements"):
            return tier2_http_e2e.HttpResponse(401, '{"detail":"Not authenticated"}')
        return tier2_http_e2e.HttpResponse(200, "<html></html>")

    report = tier2_http_e2e.run_tier2_http_e2e(
        tier2_http_e2e.Tier2Config(
            base_url="https://report-staging.example.com",
            expected_sha="abc123",
        ),
        requester=requester,
    )

    version_check = next(check for check in report["checks"] if check["name"] == "deployed_version_matches_expected")
    assert report["status"] == "failed"
    assert version_check["passed"] is False


def test_AC8_18_2_tier2_http_accepts_short_and_full_sha_match() -> None:
    """AC8.18.2: Deployed version checks allow either side to be an abbreviated SHA."""

    def requester(url: str, _timeout_seconds: float) -> tier2_http_e2e.HttpResponse:
        if url.endswith("/api/health"):
            return tier2_http_e2e.HttpResponse(200, '{"status":"healthy","git_sha":"abc123456789"}')
        if url.endswith("/api/ping"):
            return tier2_http_e2e.HttpResponse(200, '{"ok":true}')
        if url.endswith("/api/statements"):
            return tier2_http_e2e.HttpResponse(401, '{"detail":"Not authenticated"}')
        return tier2_http_e2e.HttpResponse(200, "<html></html>")

    report = tier2_http_e2e.run_tier2_http_e2e(
        tier2_http_e2e.Tier2Config(
            base_url="https://report-staging.example.com",
            expected_sha="abc123",
        ),
        requester=requester,
    )

    assert report["status"] == "passed"


def test_AC8_18_3_staging_workflow_runs_tier2_http_before_tier3_browser_e2e() -> None:
    """AC8.18.3: Staging runs Tier 2 HTTP proof before broader deployed E2E."""
    workflow = (ROOT / ".github/workflows/staging-deploy.yml").read_text(encoding="utf-8")
    e2e_step = workflow.split("id: staging_e2e_tests", 1)[1].split("- name: Classify staging", 1)[0]

    tier2_index = e2e_step.index("tools/tier2_http_e2e.py")
    tier3_index = e2e_step.index("pytest tests/e2e")
    assert tier2_index < tier3_index
    assert '--base-url "$APP_URL"' in e2e_step
    assert '--expected-sha "$EXPECTED_SHA"' in e2e_step
    assert "test-results/staging-tier2-http.xml" in e2e_step


def test_AC8_18_3_test_execution_matrix_names_tier2_http_stage() -> None:
    """AC8.18.3: The matrix distinguishes Tier 2 from Tier 1 and Tier 3 proof."""
    matrix = (ROOT / "docs/ssot/test-execution-matrix.yaml").read_text(encoding="utf-8")

    assert "path: tools/tier2_http_e2e.py" in matrix
    assert "stage: deployment_tier2_http_e2e" in matrix
