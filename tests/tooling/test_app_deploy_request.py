"""Contract tests for the versioned Finance Report -> infra2 deploy request."""

from __future__ import annotations

import ast
import importlib
import json
import re
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from common.runtime.sdk_pin import read_sdk_pin
from tools import app_deploy_request as renderer

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools/app_deploy_request.py"

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

VALID_PRODUCTION_REQUEST = {
    **VALID_REQUEST,
    "deploy_type": "prod",
    "evidence": {
        **VALID_REQUEST["evidence"],
        "staging_run_url": "https://github.com/wangzitian0/finance_report/actions/runs/12345679",
        "reviewed_change_url": "https://github.com/wangzitian0/finance_report/pull/1878",
    },
}


def test_AC_runtime_deploy_request_1_sdk_and_wire_contract_are_exactly_pinned() -> None:
    """AC-runtime.deploy-request.1: the SDK release and canonical v1 wire shape are immutable."""
    from infra2_sdk import deploy as sdk_deploy

    sdk_url, sdk_hash_hex, _ = read_sdk_pin(ROOT)
    pyproject = tomllib.loads(
        (ROOT / "apps/backend/pyproject.toml").read_text(encoding="utf-8")
    )
    sdk_dependencies = [
        dep
        for dep in pyproject["project"]["dependencies"]
        if dep.partition(" @ ")[0] == "infra2-sdk"
    ]
    assert sdk_dependencies == [f"infra2-sdk @ {sdk_url}"]

    lock = tomllib.loads((ROOT / "apps/backend/uv.lock").read_text(encoding="utf-8"))
    package = next(item for item in lock["package"] if item["name"] == "infra2-sdk")
    assert tuple(map(int, package["version"].split("."))) >= (1, 2, 0)
    assert package["source"] == {"url": sdk_url}
    assert package["wheels"] == [{"url": sdk_url, "hash": f"sha256:{sdk_hash_hex}"}]

    request = renderer.request_from_mapping(VALID_REQUEST)
    assert request.to_dict() == VALID_REQUEST
    assert renderer.canonical_json is sdk_deploy.canonical_json
    assert renderer.canonical_json(request) == (
        json.dumps(
            VALID_REQUEST, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        + "\n"
    )


def test_AC_runtime_deploy_request_2_sender_authority_is_fail_closed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-runtime.deploy-request.2: fixed-env authority is evidence-bound and side-effect-free."""
    invalid_cases = [
        ({"contract_version": True}, "contract_version must be 1"),
        ({"operation": "rollback"}, "operation must be deploy"),
        ({"deploy_type": "preview/tag"}, "deploy_type must be staging or prod"),
        ({"service": "truealpha/app"}, "service must be finance_report/app"),
        (
            {"source_repository": "wangzitian0/infra2"},
            "source_repository must be wangzitian0/finance_report",
        ),
        ({"version_ref": "main"}, "version_ref must be a release tag"),
        ({"source_sha": "A" * 40}, "source_sha must be a lowercase 40-hex commit sha"),
        ({"evidence": None}, "evidence must be an object"),
        (
            {
                "evidence": {
                    **VALID_REQUEST["evidence"],
                    "staging_run_url": "https://github.com/example/staging/runs/1",
                }
            },
            "evidence.staging_run_url must be empty for staging",
        ),
        (
            {
                "evidence": {
                    **VALID_REQUEST["evidence"],
                    "reviewed_change_url": "https://github.com/example/pull/1",
                }
            },
            "evidence.reviewed_change_url must be empty for staging",
        ),
        (
            {"evidence": {**VALID_REQUEST["evidence"], "source_run_id": "87654321"}},
            "source_run_id must match source_run_url",
        ),
    ]
    for override, error in invalid_cases:
        with pytest.raises(ValueError, match=re.escape(error)):
            renderer.request_from_mapping({**VALID_REQUEST, **override})

    production = renderer.render_request(
        request_id=VALID_PRODUCTION_REQUEST["request_id"],
        deploy_type="prod",
        version_ref=VALID_PRODUCTION_REQUEST["version_ref"],
        source_sha=VALID_PRODUCTION_REQUEST["source_sha"],
        source_run_url=VALID_PRODUCTION_REQUEST["evidence"]["source_run_url"],
        source_run_id=VALID_PRODUCTION_REQUEST["evidence"]["source_run_id"],
        staging_run_url=VALID_PRODUCTION_REQUEST["evidence"]["staging_run_url"],
        reviewed_change_url=VALID_PRODUCTION_REQUEST["evidence"]["reviewed_change_url"],
    )
    assert production.to_dict() == VALID_PRODUCTION_REQUEST

    for field in ("staging_run_url", "reviewed_change_url"):
        evidence = {**VALID_PRODUCTION_REQUEST["evidence"], field: ""}
        with pytest.raises(ValueError, match=field):
            renderer.request_from_mapping(
                {**VALID_PRODUCTION_REQUEST, "evidence": evidence}
            )

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

    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert imported_modules.isdisjoint(
        {"httpx", "requests", "subprocess", "urllib.request", "urllib3"}
    )


def test_AC_runtime_deploy_request_3_transport_correlates_the_receiver_run() -> None:
    """AC-runtime.deploy-request.3: dispatch success means this exact receiver run succeeded."""
    transport = importlib.import_module("tools.app_deploy_transport")
    source = (ROOT / "tools/app_deploy_transport.py").read_text(encoding="utf-8")
    sdk_imports = {
        alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module == "infra2_sdk.deploy"
        for alias in node.names
    }
    assert "dispatch_and_wait" in sdk_imports

    calls: list[tuple[str, str, object]] = []
    title = "Deploy finance_report/app staging main abc [finance-report-run-12345678]"
    run_lists = iter(
        [
            {"workflow_runs": [{"id": 100}]},
            {
                "workflow_runs": [
                    {
                        "id": 101,
                        "display_title": title,
                        "status": "completed",
                        "conclusion": "success",
                        "html_url": "https://github.com/wangzitian0/infra2/actions/runs/101",
                    },
                    {"id": 100},
                ]
            },
        ]
    )

    def api(method: str, path: str, body: object = None) -> object:
        calls.append((method, path, body))
        return next(run_lists) if method == "GET" else None

    result = transport.dispatch_and_wait(
        VALID_REQUEST,
        api=api,
        fetch_logs=lambda run_id: b'plan {"request_id": "finance-report-run-12345678"}',
        sleep=lambda _: None,
        max_attempts=2,
        clock=lambda: datetime(2026, 10, 14, 10, 55, 50, tzinfo=UTC),
    )
    assert result.run_id == 101
    dispatch = next(call for call in calls if call[0] == "POST")
    assert dispatch[2] == {
        "event_type": "app-deploy-request",
        "client_payload": {
            **VALID_REQUEST,
            "sender_deadline": "2026-10-14T10:56:00Z",
        },
    }

    ambiguous = iter(
        [
            {"workflow_runs": [{"id": 100}]},
            {
                "workflow_runs": [
                    {"id": 103, "status": "queued", "display_title": title},
                    {"id": 102, "status": "queued", "display_title": title},
                ]
            },
        ]
    )
    with pytest.raises(RuntimeError, match="ambiguous"):
        transport.dispatch_and_wait(
            VALID_REQUEST,
            api=lambda m, p, b=None: next(ambiguous) if m == "GET" else None,
            fetch_logs=lambda run_id: b"",
            sleep=lambda _: None,
            max_attempts=1,
        )


def test_AC_runtime_deploy_request_4_repository_has_no_infra2_source_edge() -> None:
    """AC-runtime.deploy-request.4 AC-meta.infra-boundary.1 AC-meta.infra-boundary.2: App consumes SDK/URLs, never an infra2 checkout."""
    assert not (ROOT / ".gitmodules").exists()
    gitlinks = subprocess.check_output(
        ["git", "ls-files", "--stage"], cwd=ROOT, text=True
    )
    assert not any(line.startswith("160000 ") for line in gitlinks.splitlines())

    workflows = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / ".github/workflows").glob("*.yml"))
    )
    for forbidden in (
        "submodules: recursive",
        "working-directory: repo",
        "python -m tools.deploy_v2",
        "DOKPLOY_API_KEY",
    ):
        assert forbidden not in workflows


def test_AC_runtime_deploy_request_5_transport_announces_the_approval_wait() -> None:
    """AC-runtime.deploy-request.5: a waiting Production request names its approval link and approval deadline."""
    transport = importlib.import_module("tools.app_deploy_transport")
    request_id = str(VALID_PRODUCTION_REQUEST["request_id"])
    run_title = f"Deploy finance_report/app prod v2.3.4 abc [{request_id}]"

    def make_pages(statuses: list[str], *, title: str = run_title) -> iter:
        pages: list[dict[str, object]] = [{"workflow_runs": [{"id": 200}]}]
        for st in statuses:
            pages.append(
                {
                    "workflow_runs": [
                        {
                            "id": 201,
                            "display_title": title,
                            "status": st,
                            "conclusion": "success" if st == "completed" else None,
                            "html_url": "https://github.com/wangzitian0/infra2/actions/runs/201",
                            "created_at": "2026-10-14T10:55:50Z",
                        },
                        {"id": 200},
                    ]
                }
            )
        return iter(pages)

    notices: list[str] = []
    pages = make_pages(["waiting", "waiting", "in_progress", "completed"])
    result = transport.dispatch_and_wait(
        VALID_PRODUCTION_REQUEST,
        api=lambda m, p, b=None: next(pages) if m == "GET" else None,
        fetch_logs=lambda run_id: request_id.encode(),
        sleep=lambda _: None,
        max_attempts=360,
        announce=notices.append,
        clock=lambda: datetime(2026, 10, 14, 10, 55, 50, tzinfo=UTC),
    )
    assert result.run_id == 201
    assert len(notices) == 1
    assert "https://github.com/wangzitian0/infra2/actions/runs/201" in notices[0]
    assert "Approve before 2026-10-14 11:18:50Z" in notices[0]

    staging_notices: list[str] = []
    staging_pages = make_pages(
        ["waiting", "completed"],
        title=f"Deploy finance_report/app staging v2.3.4 abc [{request_id}]",
    )
    transport.dispatch_and_wait(
        VALID_REQUEST,
        api=lambda m, p, b=None: next(staging_pages) if m == "GET" else None,
        fetch_logs=lambda run_id: request_id.encode(),
        sleep=lambda _: None,
        max_attempts=2,
        announce=staging_notices.append,
        clock=lambda: datetime(2026, 10, 14, 10, 55, 50, tzinfo=UTC),
    )
    assert staging_notices == []
