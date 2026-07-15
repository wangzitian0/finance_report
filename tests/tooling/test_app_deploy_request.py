"""Contract tests for the versioned Finance Report -> infra2 deploy request."""

from __future__ import annotations

import ast
import importlib
import io
import json
import re
import shlex
import subprocess
import tomllib
import zipfile
from pathlib import Path

import httpx
import pytest
import yaml
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
    pyproject = tomllib.loads(
        (ROOT / "apps/backend/pyproject.toml").read_text(encoding="utf-8")
    )
    sdk_dependencies = [
        dependency
        for dependency in pyproject["dependency-groups"]["dev"]
        if dependency.partition(" @ ")[0] == "infra2-sdk"
    ]
    expected_sdk_dependency = f"infra2-sdk @ {SDK_URL}"
    assert sdk_dependencies == [expected_sdk_dependency]

    lock = tomllib.loads((ROOT / "apps/backend/uv.lock").read_text(encoding="utf-8"))
    package = next(item for item in lock["package"] if item["name"] == "infra2-sdk")
    assert package["version"] == "0.1.0"
    assert package["source"] == {"url": SDK_URL}
    assert package["wheels"] == [{"url": SDK_URL, "hash": SDK_HASH}]

    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    tooling_step = next(
        step
        for step in workflow["jobs"]["tooling-coverage"]["steps"]
        if step.get("name") == "Run tooling tests with coverage"
    )
    command_line = next(
        line.strip().removesuffix("\\").strip()
        for line in tooling_step["run"].splitlines()
        if line.strip().startswith("uv run ")
    )
    command_tokens = shlex.split(command_line)
    with_dependencies = [
        command_tokens[index + 1]
        for index, token in enumerate(command_tokens[:-1])
        if token == "--with"
    ]
    assert with_dependencies.count(expected_sdk_dependency) == 1
    pytest_index = max(
        index for index, token in enumerate(command_tokens) if token == "pytest"
    )
    assert command_tokens[pytest_index + 1] == "tests/tooling/"

    request = renderer.request_from_mapping(VALID_REQUEST)
    assert request.to_dict() == VALID_REQUEST
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

    for invalid_url in (
        "https://example.com/wangzitian0/finance_report/pull/1878",
        "https://github.com/wangzitian0/finance_report/pull/1878?authority=forged",
    ):
        evidence = {
            **VALID_PRODUCTION_REQUEST["evidence"],
            "reviewed_change_url": invalid_url,
        }
        with pytest.raises(ValueError, match="must be a canonical Finance Report"):
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

    invalid_cli_args = cli_args.copy()
    invalid_cli_args[3] = "main"
    with pytest.raises(SystemExit, match="2"):
        renderer.main(invalid_cli_args)
    assert (
        capsys.readouterr()
        .err.rstrip()
        .endswith("error: version_ref must be a release tag like vX.Y.Z")
    )

    source = MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module)
    string_literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    forbidden_imports = {"httpx", "requests", "subprocess", "urllib.request", "urllib3"}
    forbidden_transport_literals = {"repository_dispatch"}
    assert imported_modules.isdisjoint(forbidden_imports)
    assert string_literals.isdisjoint(forbidden_transport_literals)


def test_AC_runtime_deploy_request_3_transport_correlates_the_receiver_run() -> None:
    """AC-runtime.deploy-request.3: dispatch success means this exact receiver run succeeded."""
    transport = importlib.import_module("tools.app_deploy_transport")
    source = (ROOT / "tools/app_deploy_transport.py").read_text(encoding="utf-8")

    assert "repository_dispatch" in source
    assert "app-deploy-request.yml" in source
    assert "request_id" in source
    assert "watermark" in source
    assert "logs" in source
    assert hasattr(transport, "dispatch_and_wait")

    staging_workflow = (ROOT / ".github/workflows/deploy.yml").read_text(
        encoding="utf-8"
    )
    production_workflow = (ROOT / ".github/workflows/release.yml").read_text(
        encoding="utf-8"
    )
    assert "python -m tools.app_deploy_transport" in staging_workflow
    assert "--deploy-type staging" in staging_workflow
    assert "steps.release_images_run.outputs.run_id" in staging_workflow
    assert production_workflow.count("python -m tools.app_deploy_transport") == 2
    assert production_workflow.count("--deploy-type prod") == 2
    assert "steps.reviewed_change.outputs.reviewed_change_url" in production_workflow
    assert "steps.staging.outputs.run_id" in production_workflow
    assert (
        "steps.rollback_reviewed_change.outputs.reviewed_change_url"
        in production_workflow
    )

    calls: list[tuple[str, str, object]] = []
    run_lists = iter(
        [
            {"workflow_runs": [{"id": 100}]},
            {
                "workflow_runs": [
                    {
                        "id": 101,
                        "status": "in_progress",
                        "conclusion": None,
                        "html_url": "https://github.com/wangzitian0/infra2/actions/runs/101",
                    },
                    {"id": 100},
                ]
            },
            {
                "workflow_runs": [
                    {
                        "id": 101,
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
        if method == "GET":
            return next(run_lists)
        return None

    result = transport.dispatch_and_wait(
        VALID_REQUEST,
        api=api,
        fetch_logs=lambda run_id: b'plan {"request_id": "finance-report-run-12345678"}',
        sleep=lambda _: None,
        max_attempts=3,
    )
    assert result.run_id == 101
    assert result.url.endswith("/101")
    dispatch = next(call for call in calls if call[0] == "POST")
    assert dispatch[2] == {
        "event_type": "app-deploy-request",
        "client_payload": VALID_REQUEST,
    }

    ambiguous_runs = {
        "workflow_runs": [
            {"id": 103, "status": "queued"},
            {"id": 102, "status": "queued"},
            {"id": 100, "status": "completed"},
        ]
    }
    responses = iter([{"workflow_runs": [{"id": 100}]}, ambiguous_runs])
    with pytest.raises(RuntimeError, match="ambiguous"):
        transport.dispatch_and_wait(
            VALID_REQUEST,
            api=lambda method, path, body=None: (
                next(responses) if method == "GET" else None
            ),
            fetch_logs=lambda run_id: b"",
            sleep=lambda _: None,
            max_attempts=1,
        )

    responses = iter(
        [
            {"workflow_runs": [{"id": 100}]},
            {
                "workflow_runs": [
                    {
                        "id": 101,
                        "status": "completed",
                        "conclusion": "success",
                        "html_url": "https://github.com/wangzitian0/infra2/actions/runs/101",
                    }
                ]
            },
        ]
    )
    with pytest.raises(RuntimeError, match="request_id"):
        transport.dispatch_and_wait(
            VALID_REQUEST,
            api=lambda method, path, body=None: (
                next(responses) if method == "GET" else None
            ),
            fetch_logs=lambda run_id: b"another request",
            sleep=lambda _: None,
            max_attempts=1,
        )


def test_AC_runtime_deploy_request_3_transport_fail_closed_edges() -> None:
    """AC-runtime.deploy-request.3: polling and GitHub response edges cannot pass."""
    transport = importlib.import_module("tools.app_deploy_transport")

    responses = iter(
        [
            {"workflow_runs": [{"id": 100}]},
            {"workflow_runs": [{"id": 100}]},
            {"workflow_runs": [{"id": 100}]},
        ]
    )
    sleeps: list[float] = []
    with pytest.raises(RuntimeError, match="timed out"):
        transport.dispatch_and_wait(
            VALID_REQUEST,
            api=lambda method, path, body=None: (
                next(responses) if method == "GET" else None
            ),
            fetch_logs=lambda run_id: b"",
            sleep=sleeps.append,
            poll_interval=0.25,
            max_attempts=2,
        )
    assert sleeps == [0.25]

    def run_failure(conclusion: str, url: object) -> object:
        responses = iter(
            [
                {"workflow_runs": [{"id": 100}]},
                {
                    "workflow_runs": [
                        {
                            "id": 101,
                            "status": "completed",
                            "conclusion": conclusion,
                            "html_url": url,
                        }
                    ]
                },
            ]
        )
        return transport.dispatch_and_wait(
            VALID_REQUEST,
            api=lambda method, path, body=None: (
                next(responses) if method == "GET" else None
            ),
            fetch_logs=lambda run_id: VALID_REQUEST["request_id"].encode(),
            sleep=lambda _: None,
            max_attempts=1,
        )

    with pytest.raises(RuntimeError, match="concluded 'failure'"):
        run_failure("failure", "https://github.com/wangzitian0/infra2/actions/runs/101")
    with pytest.raises(RuntimeError, match="has no canonical URL"):
        run_failure("success", "https://example.com/actions/runs/101")

    for payload in ([], {}, {"workflow_runs": ["not-a-run"]}):
        with pytest.raises(RuntimeError, match="workflow-runs response"):
            transport._workflow_runs(payload)
    for run_id in (True, 0, "101"):
        with pytest.raises(RuntimeError, match="positive integer"):
            transport._run_id({"id": run_id})


def test_AC_runtime_deploy_request_3_github_transport_adapters_fail_closed() -> None:
    """AC-runtime.deploy-request.3: GitHub API and log adapters validate responses."""
    transport = importlib.import_module("tools.app_deploy_transport")

    def client_for(response: httpx.Response) -> httpx.Client:
        return httpx.Client(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(lambda _request: response),
        )

    with client_for(httpx.Response(200, json={"workflow_runs": []})) as client:
        assert transport._github_api(client, "GET", "/runs", None) == {
            "workflow_runs": []
        }
    with client_for(httpx.Response(204)) as client:
        assert transport._github_api(client, "POST", "/dispatches", {}) is None
    with client_for(httpx.Response(403, text="secret response body")) as client:
        with pytest.raises(RuntimeError, match="HTTP 403") as exc_info:
            transport._github_api(client, "GET", "/runs?token=hidden", None)
        assert "secret response body" not in str(exc_info.value)
        assert "token=hidden" not in str(exc_info.value)
    with client_for(httpx.Response(200)) as client:
        with pytest.raises(RuntimeError, match="expected HTTP 204"):
            transport._github_api(client, "POST", "/dispatches", {})
    with client_for(httpx.Response(200, text="{")) as client:
        with pytest.raises(RuntimeError, match="not valid JSON"):
            transport._github_api(client, "GET", "/runs", None)

    archive_bytes = io.BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("receiver/1.txt", b"first")
        archive.writestr("receiver/2.txt", b"second")
    with client_for(httpx.Response(200, content=archive_bytes.getvalue())) as client:
        assert transport._github_logs(client, 101) == b"first\nsecond"
    with client_for(httpx.Response(404, text="private logs")) as client:
        with pytest.raises(RuntimeError, match="HTTP 404") as exc_info:
            transport._github_logs(client, 101)
        assert "private logs" not in str(exc_info.value)
    with client_for(httpx.Response(200, content=b"not-a-zip")) as client:
        with pytest.raises(RuntimeError, match="not a zip archive"):
            transport._github_logs(client, 101)


def test_AC_runtime_deploy_request_3_transport_cli_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC-runtime.deploy-request.3: the CLI uses env auth and writes run evidence."""
    transport = importlib.import_module("tools.app_deploy_transport")

    monkeypatch.delenv("INFRA2_PAT", raising=False)
    assert transport.main([]) == 1
    assert "INFRA2_PAT is required" in capsys.readouterr().err

    monkeypatch.setenv("INFRA2_PAT", "test-token")
    assert transport.main(["--timeout", "0"]) == 1
    assert "must be positive" in capsys.readouterr().err

    monkeypatch.setattr(transport.sys, "stdin", io.StringIO("[]"))
    assert transport.main(["--timeout", "5", "--poll-interval", "5"]) == 1
    assert "must be a JSON object" in capsys.readouterr().err

    class DummyClient:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

        def __enter__(self) -> DummyClient:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    output_path = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    monkeypatch.setattr(transport.httpx, "Client", DummyClient)
    monkeypatch.setattr(
        transport,
        "dispatch_and_wait",
        lambda *args, **kwargs: transport.ReceiverRun(
            run_id=101,
            url="https://github.com/wangzitian0/infra2/actions/runs/101",
        ),
    )
    monkeypatch.setattr(transport.sys, "stdin", io.StringIO(json.dumps(VALID_REQUEST)))
    assert transport.main(["--timeout", "5", "--poll-interval", "5"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "receiver_run_id": 101,
        "receiver_run_url": "https://github.com/wangzitian0/infra2/actions/runs/101",
    }
    assert output_path.read_text(encoding="utf-8") == (
        "receiver_run_id=101\n"
        "receiver_run_url=https://github.com/wangzitian0/infra2/actions/runs/101\n"
    )

    monkeypatch.setattr(
        transport,
        "dispatch_and_wait",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("receiver failed")),
    )
    monkeypatch.setattr(transport.sys, "stdin", io.StringIO(json.dumps(VALID_REQUEST)))
    assert transport.main(["--timeout", "5", "--poll-interval", "5"]) == 1
    assert "receiver failed" in capsys.readouterr().err


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
    assert "submodules: recursive" not in workflows
    assert "working-directory: repo" not in workflows
    assert "python -m tools.deploy_v2" not in workflows
    assert "DOKPLOY_API_KEY" not in (ROOT / ".github/workflows/deploy.yml").read_text(
        encoding="utf-8"
    )
    assert "DOKPLOY_API_KEY" not in (ROOT / ".github/workflows/release.yml").read_text(
        encoding="utf-8"
    )

    retired_source_readers = (
        "tests/tooling/_infra2_source.py",
        "tests/tooling/test_deploy_compose_contract.py",
        "tests/tooling/test_infra2_pin_is_release_tag.py",
    )
    assert all(not (ROOT / path).exists() for path in retired_source_readers)
