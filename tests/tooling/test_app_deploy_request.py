"""Contract tests for the versioned Finance Report -> infra2 deploy request."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest
from tools import app_deploy_request as renderer

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools/app_deploy_request.py"
SDK_URL = (
    "https://github.com/wangzitian0/infra2-sdk/releases/download/v0.1.0/"
    "infra2_sdk-0.1.0-py3-none-any.whl"
)
SDK_HASH = "sha256:94bfdc8b13c5bdcef9ee9150eda0ec794d3b3a0b4b11d529c29d6a2a1ba32a55"

VALID_REQUEST = {
    "contract_version": 1,
    "request_id": "finance-report-run-12345678",
    "operation": "deploy",
    "service": "finance_report/app",
    "deploy_type": "staging",
    "version_ref": "v2.3.4",
    "source_repository": "wangzitian0/finance_report",
    "source_sha": "1234567890abcdef1234567890abcdef12345678",
    "evidence": {
        "source_run_url": "https://github.com/wangzitian0/finance_report/actions/runs/12345678",
        "source_run_id": "12345678",
        "staging_run_url": "",
        "reviewed_change_url": "",
    },
}


def test_AC_runtime_deploy_request_1_sdk_and_wire_contract_are_exactly_pinned() -> None:
    """AC-runtime.deploy-request.1: the SDK release and canonical v1 wire shape are immutable."""
    pyproject = tomllib.loads((ROOT / "apps/backend/pyproject.toml").read_text(encoding="utf-8"))
    assert f"infra2-sdk @ {SDK_URL}" in pyproject["dependency-groups"]["dev"]

    lock = tomllib.loads((ROOT / "apps/backend/uv.lock").read_text(encoding="utf-8"))
    package = next(item for item in lock["package"] if item["name"] == "infra2-sdk")
    assert package["version"] == "0.1.0"
    assert package["source"] == {"url": SDK_URL}
    assert package["wheels"] == [{"url": SDK_URL, "hash": SDK_HASH}]

    ci_workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert f'--with "infra2-sdk @ {SDK_URL}" pytest tests/tooling/' in ci_workflow

    request = renderer.request_from_mapping(VALID_REQUEST)
    assert request.to_dict() == VALID_REQUEST
    assert renderer.canonical_json(request) == (
        json.dumps(VALID_REQUEST, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    )


def test_AC_runtime_deploy_request_2_sender_authority_is_fail_closed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-runtime.deploy-request.2: app authority is staging-only and side-effect-free."""
    invalid_cases = [
        ({"contract_version": True}, "contract_version must be 1"),
        ({"operation": "rollback"}, "operation must be deploy"),
        ({"deploy_type": "prod"}, "production requests are disabled"),
        ({"deploy_type": "preview/tag"}, "deploy_type must be staging"),
        ({"service": "truealpha/app"}, "service must be finance_report/app"),
        (
            {"source_repository": "wangzitian0/infra2"},
            "source_repository must be wangzitian0/finance_report",
        ),
        ({"version_ref": "main"}, "version_ref must be a release tag"),
        ({"version_ref": None}, "version_ref must be a release tag"),
        ({"source_sha": "A" * 40}, "source_sha must be a lowercase 40-hex commit sha"),
        ({"source_sha": None}, "source_sha must be a lowercase 40-hex commit sha"),
        ({"evidence": None}, "evidence must be an object"),
        (
            {
                "evidence": {
                    **VALID_REQUEST["evidence"],
                    "staging_run_url": "https://github.com/example/staging/runs/1",
                }
            },
            "evidence.staging_run_url must be empty",
        ),
        (
            {
                "evidence": {
                    **VALID_REQUEST["evidence"],
                    "reviewed_change_url": "https://github.com/example/pull/1",
                }
            },
            "evidence.reviewed_change_url must be empty",
        ),
        (
            {"evidence": {**VALID_REQUEST["evidence"], "unexpected": "authority"}},
            "evidence fields must exactly match DeployEvidence v1",
        ),
        (
            {
                "evidence": {
                    **VALID_REQUEST["evidence"],
                    "source_run_url": "https://example.com/actions/runs/12345678",
                }
            },
            "source_run_url must point to the Finance Report GitHub Actions run",
        ),
        (
            {
                "evidence": {
                    **VALID_REQUEST["evidence"],
                    "source_run_url": "https://github.com/wangzitian0/finance_report/actions/runs/12345678?x=1",
                }
            },
            "source_run_url must point to the Finance Report GitHub Actions run",
        ),
        (
            {"evidence": {**VALID_REQUEST["evidence"], "source_run_url": ""}},
            "source_run_url is required",
        ),
        (
            {"evidence": {**VALID_REQUEST["evidence"], "source_run_id": ""}},
            "source_run_id is required",
        ),
        (
            {"evidence": {**VALID_REQUEST["evidence"], "source_run_id": "87654321"}},
            "source_run_id must match source_run_url",
        ),
    ]
    for override, error in invalid_cases:
        raw = {**VALID_REQUEST, **override}
        with pytest.raises(ValueError, match=re.escape(error)):
            renderer.request_from_mapping(raw)

    with pytest.raises(
        ValueError, match="request fields must exactly match DeployRequest v1"
    ):
        renderer.request_from_mapping({**VALID_REQUEST, "unexpected": "authority"})

    assert renderer._SOURCE_RUN_PATH_RE.pattern == (
        rf"\A/{re.escape(renderer.SOURCE_REPOSITORY)}/actions/runs/([1-9][0-9]*)\Z"
    )

    rendered = renderer.render_request(
        request_id=VALID_REQUEST["request_id"],
        version_ref=VALID_REQUEST["version_ref"],
        source_sha=VALID_REQUEST["source_sha"],
        source_run_url=VALID_REQUEST["evidence"]["source_run_url"],
        source_run_id=VALID_REQUEST["evidence"]["source_run_id"],
    )
    assert rendered.to_dict() == VALID_REQUEST

    cli_args = [
        "--request-id",
        VALID_REQUEST["request_id"],
        "--version-ref",
        VALID_REQUEST["version_ref"],
        "--source-sha",
        VALID_REQUEST["source_sha"],
        "--source-run-url",
        VALID_REQUEST["evidence"]["source_run_url"],
        "--source-run-id",
        VALID_REQUEST["evidence"]["source_run_id"],
    ]
    assert renderer.main(cli_args) == 0
    assert json.loads(capsys.readouterr().out) == VALID_REQUEST

    invalid_cli_args = cli_args.copy()
    invalid_cli_args[3] = "main"
    with pytest.raises(SystemExit, match="2"):
        renderer.main(invalid_cli_args)
    assert "version_ref must be a release tag" in capsys.readouterr().err

    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "repository_dispatch" not in source
    assert "subprocess" not in source
    assert "urllib.request" not in source
