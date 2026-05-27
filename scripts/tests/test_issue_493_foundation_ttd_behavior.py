"""Behavior-backed coverage for issue #493 foundation and TTD ACs."""

from __future__ import annotations

import ast
import os
import stat
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path

import pytest
import yaml

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SCRIPTS_ROOT.parent
sys.path.insert(0, str(SCRIPTS_ROOT))

import check_env_keys  # noqa: E402
import generate_ac_registry as gar  # noqa: E402
import validate_schemas  # noqa: E402


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_python(path: Path) -> ast.Module:
    return ast.parse(_read(path), filename=str(path))


def _class_names(path: Path) -> set[str]:
    return {
        node.name for node in _parse_python(path).body if isinstance(node, ast.ClassDef)
    }


def _imported_names_from_module(path: Path, module_name: str) -> set[str]:
    imported: set[str] = set()
    for node in _parse_python(path).body:
        if isinstance(node, ast.ImportFrom) and node.module == module_name:
            imported.update(alias.name for alias in node.names)
    return imported


def test_AC12_19_1_moon_workspace_loads_root_and_app_projects() -> None:
    """AC12.19.1: Moon workspace config discovers apps, infra, and root tasks."""
    workspace = yaml.safe_load(_read(REPO_ROOT / ".moon" / "workspace.yml"))
    root_project = yaml.safe_load(_read(REPO_ROOT / "moon.yml"))

    assert workspace["vcs"]["client"] == "git"
    assert workspace["vcs"]["defaultBranch"] == "main"
    assert workspace["projects"] == ["apps/*", "infra", "."]
    assert root_project["layer"] == "tool"
    expected_tasks = {"setup", "dev", "test", "lint", "build", "clean"}
    assert set(root_project["tasks"]) == expected_tasks
    for task in expected_tasks:
        command = root_project["tasks"][task]["command"]
        assert command.startswith("python3 scripts/cli.py ")


def test_AC12_22_1_stage2_review_schemas_live_outside_statements_router() -> None:
    """AC12.22.1: Stage 2 review request/response schemas are in schemas.review."""
    review_schema_path = (
        REPO_ROOT / "apps" / "backend" / "src" / "schemas" / "review.py"
    )
    statements_router_path = (
        REPO_ROOT / "apps" / "backend" / "src" / "routers" / "statements.py"
    )
    review_router_path = (
        REPO_ROOT / "apps" / "backend" / "src" / "routers" / "review.py"
    )

    moved_schema_names = {
        "ConsistencyCheckResponse",
        "ConsistencyCheckListResponse",
        "ResolveCheckRequest",
        "BatchApproveRequest",
        "BatchRejectRequest",
        "Stage2ReviewQueueResponse",
    }

    assert moved_schema_names <= _class_names(review_schema_path)
    assert moved_schema_names.isdisjoint(_class_names(statements_router_path))
    assert moved_schema_names <= _imported_names_from_module(
        review_router_path,
        "src.schemas.review",
    )


def test_AC12_22_2_background_task_payload_schemas_are_module_owned() -> None:
    """AC12.22.2: Statement background/retry payload schemas stay in schemas.extraction."""
    extraction_schema_path = (
        REPO_ROOT / "apps" / "backend" / "src" / "schemas" / "extraction.py"
    )
    statements_router_path = (
        REPO_ROOT / "apps" / "backend" / "src" / "routers" / "statements.py"
    )
    statement_parsing_path = (
        REPO_ROOT / "apps" / "backend" / "src" / "services" / "statement_parsing.py"
    )

    payload_schema_names = {
        "StatementDecisionRequest",
        "RetryParsingRequest",
        "TransactionUpdateRequest",
        "ParsedStatementPreview",
    }

    assert payload_schema_names <= _class_names(extraction_schema_path)
    assert payload_schema_names.isdisjoint(_class_names(statements_router_path))
    assert payload_schema_names.isdisjoint(_class_names(statement_parsing_path))
    public_schema_imports = _imported_names_from_module(
        statements_router_path, "src.schemas"
    )
    assert {"StatementDecisionRequest", "RetryParsingRequest"} <= public_schema_imports


def test_AC14_1_1_backend_pyproject_enforces_local_coverage_threshold() -> None:
    """AC14.1.1: Backend pytest config enforces coverage above the 90 percent target."""
    pyproject = tomllib.loads(_read(REPO_ROOT / "apps" / "backend" / "pyproject.toml"))
    addopts = pyproject["tool"]["pytest"]["ini_options"]["addopts"]

    assert "--cov=src" in addopts
    assert "--cov-branch" in addopts
    threshold_index = addopts.index("--cov-fail-under=96")
    threshold = int(addopts[threshold_index].split("=", maxsplit=1)[1])
    assert threshold >= 90


def test_AC14_1_2_pre_commit_mypy_hook_blocks_backend_type_errors() -> None:
    """AC14.1.2: Pre-commit runs mypy against backend source files."""
    config = yaml.safe_load(_read(REPO_ROOT / ".pre-commit-config.yaml"))
    hooks = {
        hook["id"]: hook
        for repo in config["repos"]
        if repo["repo"] == "https://github.com/pre-commit/mirrors-mypy"
        for hook in repo["hooks"]
    }

    mypy = hooks["mypy"]
    assert mypy["files"] == "^apps/backend/src/"
    assert "--warn-unused-ignores" in mypy["args"]
    assert "--ignore-missing-imports" in mypy["args"]
    assert "sqlalchemy>=2.0.30" in mypy["additional_dependencies"]


def test_AC14_1_3_validate_schemas_exits_nonzero_for_missing_field_descriptions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """AC14.1.3: validate_schemas.py exits non-zero for Field() without descriptions."""
    root = tmp_path
    config_path = root / "apps" / "backend" / "src" / "config.py"
    schemas_dir = root / "apps" / "backend" / "src" / "schemas"
    config_path.parent.mkdir(parents=True)
    schemas_dir.mkdir(parents=True)
    config_path.write_text(
        "class Settings:\n    debug: bool = False\n", encoding="utf-8"
    )
    (schemas_dir / "bad.py").write_text(
        "from pydantic import BaseModel, Field\n\n"
        "class BadSchema(BaseModel):\n"
        "    name: str = Field()\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(validate_schemas, "get_project_root", lambda: root)
    monkeypatch.setattr(sys, "argv", ["validate_schemas.py"])

    with pytest.raises(SystemExit) as exc_info:
        validate_schemas.main()

    assert exc_info.value.code == 1


def test_AC14_1_4_check_env_keys_exits_nonzero_for_secret_config_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """AC14.1.4: check_env_keys.py detects mismatched secrets/config/env keys."""
    root = tmp_path
    ctmpl_path = (
        root / "repo" / "finance_report" / "finance_report" / "10.app" / "secrets.ctmpl"
    )
    config_path = root / "apps" / "backend" / "src" / "config.py"
    env_path = root / ".env.example"
    ctmpl_path.parent.mkdir(parents=True)
    config_path.parent.mkdir(parents=True)
    ctmpl_path.write_text(
        "DATABASE_URL={{ .Data.data.DATABASE_URL }}\n", encoding="utf-8"
    )
    config_path.write_text(
        'class Settings:\n    redis_url: str = Field(validation_alias="REDIS_URL")\n',
        encoding="utf-8",
    )
    env_path.write_text("REDIS_URL=redis://localhost:6379/0\n", encoding="utf-8")

    monkeypatch.setattr(check_env_keys, "get_project_root", lambda: root)
    monkeypatch.setattr(sys, "argv", ["check_env_keys.py"])

    with pytest.raises(SystemExit) as exc_info:
        check_env_keys.main()

    assert exc_info.value.code == 1


def test_AC14_1_5_smoke_test_succeeds_against_mocked_local_environment(
    tmp_path: Path,
) -> None:
    """AC14.1.5: smoke_test.sh succeeds when health, pages, auth, and CORS pass."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import sys

            args = sys.argv[1:]
            url = next((arg for arg in reversed(args) if arg.startswith("http")), "")

            if "-I" in args:
                print("HTTP/1.1 204 No Content")
                print("Access-Control-Allow-Origin: http://example.test")
                raise SystemExit(0)

            status = "401" if url.endswith("/api/statements") else "200"
            body = '{"status":"healthy","state":"pong"}' if url.endswith("/api/health") or url.endswith("/api/ping") else "OK"

            if "-o" in args and "/dev/null" in args:
                print(status, end="")
            elif "-w" in args:
                print(body)
                print(status)
            else:
                print(body)
            """
        ),
        encoding="utf-8",
    )
    fake_curl.chmod(fake_curl.stat().st_mode | stat.S_IXUSR)

    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "SMOKE_READY_ATTEMPTS": "1",
        "SMOKE_READY_SLEEP_SECONDS": "0",
    }
    result = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "scripts" / "smoke_test.sh"),
            "http://example.test",
            "prod",
        ],
        check=False,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "All smoke tests passed!" in result.stdout
    assert "Protected endpoint is secured" in result.stdout


def test_AC14_1_6_generate_ac_registry_check_rejects_ghosts_and_keeps_no_overlap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """AC14.1.6: Registry generation ignores ghost AC references and splits infra/feature IDs."""
    project_dir = tmp_path / "docs" / "project"
    project_dir.mkdir(parents=True)
    (project_dir / "EPIC-001.phase0-setup.md").write_text(
        "| AC1.1.1 | Feature setup AC |\n"
        "Reference-only prose mentions AC1.99.1 but must not create it.\n",
        encoding="utf-8",
    )
    (project_dir / "EPIC-014.ttd-transformation.md").write_text(
        "| AC14.1.6 | Registry generation keeps zero ghost ACs and zero overlap |\n",
        encoding="utf-8",
    )

    feature_registry = tmp_path / "docs" / "ac_registry.yaml"
    infra_registry = tmp_path / "docs" / "infra_registry.yaml"
    feature_registry.parent.mkdir(parents=True, exist_ok=True)
    gar.write_registry(
        {
            "AC1.1.1": {
                "epic": 1,
                "epic_name": "phase0-setup",
                "description": "Feature setup AC",
            }
        },
        output_path=str(feature_registry),
    )
    gar.write_registry(
        {
            "AC14.1.6": {
                "epic": 14,
                "epic_name": "ttd-transformation",
                "description": "Registry generation keeps zero ghost ACs and zero overlap",
            }
        },
        output_path=str(infra_registry),
    )

    monkeypatch.setattr(gar, "EPIC_DIR", str(project_dir))
    monkeypatch.setattr(gar, "OUTPUT_FEATURE", str(feature_registry))
    monkeypatch.setattr(gar, "OUTPUT_INFRA", str(infra_registry))

    extracted = gar.extract_acs()
    assert "AC1.99.1" not in extracted
    assert gar.main(["--check"]) == 0
    feature_ids = set(gar.load_existing_registry(feature_registry))
    infra_ids = set(gar.load_existing_registry(infra_registry))
    assert feature_ids.isdisjoint(infra_ids)
