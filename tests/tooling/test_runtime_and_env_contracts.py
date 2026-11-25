"""Runtime environment manifests, toolchain contract, lockfiles, SDK pin, jobs, and CSP."""

from __future__ import annotations

import ast
import json
import os
import re
import runpy
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml
from infra2_sdk.manifests import CELL_POLICIES

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "apps" / "backend"
for _path in (ROOT, BACKEND_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from common.runtime import check_toolchain_contract as toolchain_contract  # noqa: E402
from common.runtime import env_manifests as gen  # noqa: E402
from common.runtime.sdk_pin import read_sdk_pin  # noqa: E402
from common.testing import lockfile_registry, preflight  # noqa: E402
from tools import sdk_pin  # noqa: E402

HOOKS_PATH = gen.ROOT_DIR / "runtime-hooks.manifest.json"
NEXT_CONFIG = ROOT / "apps" / "frontend" / "next.config.mjs"
ANALYTICS = ROOT / "apps" / "frontend" / "src" / "components" / "RootClients.tsx"

_TOOLCHAIN_INPUTS = (
    "toolchain.toml",
    ".python-version",
    ".node-version",
    ".nvmrc",
    ".tool-versions",
    ".npmrc",
    ".moon/toolchain.yml",
    "apps/frontend/package.json",
    ".github/workflows/ci.yml",
    ".github/workflows/docs.yml",
    ".github/actions/setup-minio/action.yml",
    "apps/backend/Dockerfile",
    "apps/frontend/Dockerfile",
    "docker-compose.yml",
)


def _committed_manifest() -> dict:
    return json.loads((gen.ROOT_DIR / gen.BACKEND_MANIFEST).read_text(encoding="utf-8"))


def _by_env() -> dict:
    return {field.env: field for field in gen.specs()[0].build().fields}


def _hooks_payload() -> dict:
    return json.loads(HOOKS_PATH.read_text(encoding="utf-8"))


def _write_hooks(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "runtime-hooks.manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _copy_contract_inputs(target_root: Path) -> None:
    for relative_path in _TOOLCHAIN_INPUTS:
        source = ROOT / relative_path
        target = target_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def _write_lockfile(path: Path, packages: dict[str, dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": "test-fixture",
        "lockfileVersion": 3,
        "requires": True,
        "packages": packages,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def test_AC_runtime_guard_proofs_11_env_manifest_check_passes_and_catches_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-runtime.guard-proofs.11"""
    assert gen.main(["--check"]) == 0, capsys.readouterr().out
    assert "env manifests: ok" in capsys.readouterr().out

    frontend = json.loads(
        (gen.ROOT_DIR / gen.FRONTEND_MANIFEST).read_text(encoding="utf-8")
    )
    assert {f["env"] for f in frontend["fields"]} == {
        "NEXT_PUBLIC_API_URL",
        "NEXT_PUBLIC_DEPLOYMENT_ENVIRONMENT",
        "NEXT_PUBLIC_GIT_SHA",
        "NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT",
        "OPENPANEL_SCRIPT_URL",
    }
    frontend["fields"][0]["aliases"] = ["ENV"]
    bad = tmp_path / "required-env.manifest.json"
    bad.write_text(json.dumps(frontend), encoding="utf-8")
    with monkeypatch.context() as mp:
        mp.setattr(gen, "HAND_WRITTEN", (str(bad),))
        assert gen.main(["--check"]) == 1
        assert "ENV is deprecated: use ENVIRONMENT" in capsys.readouterr().out

    stale = tmp_path / ".env.example"
    stale.write_text(
        gen.ENV_EXAMPLE_PATH.read_text(encoding="utf-8").replace(
            "DEBUG=true", "DEBUG=false"
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(gen, "ENV_EXAMPLE_PATH", stale)
    assert gen.main(["--check"]) == 1
    assert "+DEBUG=true" in capsys.readouterr().out


def test_AC_runtime_guard_proofs_12_to_14_vault_producers_aliases_and_sensitivity() -> (
    None
):
    """AC-runtime.guard-proofs.12 AC-runtime.guard-proofs.13 AC-runtime.guard-proofs.14 AC-runtime.env-empty-values.1"""
    fields = gen.collect_backend_fields()
    by_env_manifest = {entry["env"]: entry for entry in _committed_manifest()["fields"]}
    env_example_keys = gen.env_example_documented_keys(
        gen.ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
    )
    vault_fields = [f for f in fields if f["vault"]]
    assert vault_fields, "no vault-tagged fields found — the gate would be vacuous"
    for field in vault_fields:
        assert by_env_manifest[field["key"]]["injected"] is True, field["key"]
        assert field["key"] in env_example_keys, (
            f"vault-tagged {field['key']} missing from .env.example"
        )
    assert _committed_manifest()["source"] == gen.MANIFEST_SOURCE

    by_env = _by_env()
    assert (
        by_env["DATABASE_URL"].provided_by
        == "finance_report/postgres:POSTGRES_PASSWORD"
    )
    api_key = by_env["LLM_API_KEY"]
    assert (api_key.source, api_key.empty_ok, api_key.store_key, api_key.aliases) == (
        "human",
        True,
        "LLM_API_KEY",
        (),
    )
    for env_name in ("GIT_COMMIT_SHA", "CONFIGURATION_SHA256"):
        assert by_env[env_name].source == "release" and by_env[env_name].injected, (
            env_name
        )
    for env_name in (
        "ENVIRONMENT",
        "CORS_ORIGINS",
        "S3_ENDPOINT",
        "PREFECT_API_URL",
        "API_RATE_LIMIT_REQUESTS",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OPENPANEL_CLIENT_ID",
    ):
        assert by_env[env_name].source == "decision", env_name
        assert by_env[env_name].injected and not by_env[env_name].store_backed, env_name
    assert (
        by_env["OPENPANEL_CLIENT_ID"].empty_ok and by_env["S3_PUBLIC_BUCKET"].empty_ok
    )
    for model_env in (
        "LLM_LARGE_MODEL",
        "LLM_SMALL_MODEL",
        "LLM_MULTIMODAL_MODEL",
        "PREFECT_WORKER_QUERY_SECONDS",
    ):
        assert by_env[model_env].source == "code", model_env
    assert by_env["ENVIRONMENT"].aliases == ()
    declared = {name for f in by_env.values() for name in (f.env, *f.aliases)}
    for retired in (
        "ENV",
        "INFRA_ENVIRONMENT",
        "LARGE_MODEL",
        "SMALL_MODEL",
        "MULTIMODAL_MODEL",
        "PRIMARY_MODEL",
    ):
        assert retired not in declared, retired

    chains = {f.env: f.aliases for f in by_env.values() if f.aliases}
    assert chains == {}, (
        f"an alias chain is back; add an empty-value scan for it first: {chains}"
    )
    assert by_env["DATABASE_URL"].sensitive is True
    assert by_env["REDIS_URL"].sensitive is True

    real = gen.settings_module()
    cfg = real.Settings(
        _env_file=None,
        LLM_PROVIDER="zai",
        LLM_API_KEY="tok-canonical",
        LLM_BASE_URL="https://api.example.com/v1",
        LLM_SMALL_MODEL="custom-small",
    )
    llm = cfg.to_llm_settings()
    assert (llm.api_key, llm.base_url, llm.small_model) == (
        "tok-canonical",
        "https://api.example.com/v1",
        "custom-small",
    )
    legacy = real.Settings(
        _env_file=None,
        AI_API_KEY="tok-legacy",
        SMALL_MODEL="legacy-small",
        ENV="staging",
    )
    assert legacy.to_llm_settings().api_key == ""
    assert legacy.small_model != "legacy-small"
    assert legacy.environment == "development"


def test_runtime_hooks_manifest_validation_and_cells(tmp_path: Path) -> None:
    assert gen.runtime_hooks_gate_errors() == []

    for old_version in (1, 2):
        payload = _hooks_payload()
        payload["schema_version"] = old_version
        errors = gen.runtime_hooks_gate_errors(_write_hooks(tmp_path, payload))
        assert len(errors) == 1 and "schema_version" in errors[0], errors

    payload = _hooks_payload()
    removed = {"staging_core_e2e", "ai_provider_connectivity", "staging_ai_ocr"}
    payload["checks"] = [c for c in payload["checks"] if c["id"] not in removed]
    assert gen.runtime_hooks_gate_errors(_write_hooks(tmp_path, payload)) == [
        "runtime-hooks.manifest.json: no check runs in cell 'staging.post'"
    ]

    payload = _hooks_payload()
    payload["checks"][0].pop("cells")
    assert gen.runtime_hooks_gate_errors(_write_hooks(tmp_path, payload)) == [
        "runtime-hooks.manifest.json: no check runs in cell 'prod.post'"
    ]

    payload = _hooks_payload()
    payload["checks"][1]["optional_env"] = [
        *payload["checks"][1].get("optional_env", []),
        "NOT_A_REAL_KEY",
    ]
    assert any(
        "'NOT_A_REAL_KEY'" in err
        for err in gen.runtime_hooks_gate_errors(_write_hooks(tmp_path, payload))
    )

    hooks = gen.load_hooks_manifest(HOOKS_PATH)
    check_ids = [c.id for c in hooks.checks]
    assert "touched_files" not in check_ids
    assert [c.id for c in hooks.checks_for_cell("preview.post")] == [
        "preview_minimum_e2e"
    ]
    assert [c.id for c in hooks.checks_for_cell("staging.post")] == [
        "staging_core_e2e",
        "ai_provider_connectivity",
        "staging_ai_ocr",
    ]
    assert [c.id for c in hooks.checks_for_cell("prod.post")] == ["smoke"]
    assert [c.id for c in hooks.checks_for_cell("scheduled_audit")] == [
        "audit_replay",
        "core_journey",
        "pdf_corpus_oracle",
        "financial_scenario_benchmark",
    ]
    by_id = {c.id: c for c in hooks.checks}
    for non_llm in ("preview_minimum_e2e", "staging_core_e2e", "core_journey"):
        assert "real_llm" not in by_id[non_llm].needs, non_llm
    assert "real_provider" not in by_id["core_journey"].needs

    audit_checks = hooks.checks_for_cell("scheduled_audit")
    assert (
        sum(c.timeout_seconds for c in audit_checks)
        <= CELL_POLICIES["scheduled_audit"].budget_seconds
    )
    for oracle_id in ("pdf_corpus_oracle", "financial_scenario_benchmark"):
        cmd = " ".join(by_id[oracle_id].argv)
        assert "--json-report" in cmd
        assert "--output-summary" in cmd
        assert "HOOK_ARTIFACTS_DIR" in cmd


def test_smoke_script_refuses_deployed_env_without_version_ref() -> None:
    script = gen.ROOT_DIR / "common" / "runtime" / "shell" / "smoke_test.sh"
    base = {k: v for k, v in os.environ.items() if k != "APP_VERSION_REF"}
    for env_name in ("preview", "staging", "production"):
        env = {**base, "ENVIRONMENT": env_name, "EXPECTED_SHA": "abc1234"}
        res = subprocess.run(
            ["bash", str(script), "http://127.0.0.1:9"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert res.returncode == 2 and "APP_VERSION_REF" in res.stdout, (
            env_name,
            res.stdout,
        )


def test_AC8_13_39_toolchain_contract_consistency_and_drift_detection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC8.13.39 AC-testing.toolchain.1"""
    assert toolchain_contract.run_contract(ROOT) == 0

    drift_cases = [
        (".node-version", lambda s: "25.9.0\n"),
        (
            "apps/backend/Dockerfile",
            lambda s: s.replace(
                "ARG PYTHON_IMAGE=python:3.12.12-slim",
                "ARG PYTHON_IMAGE=python:3.12-slim",
            ),
        ),
        (
            "apps/frontend/package.json",
            lambda s: s.replace('"node": "20.19.0"', '"node": ">=20"'),
        ),
        (
            ".moon/toolchain.yml",
            lambda s: s.replace("version: '20.19.0'", "version: '25.9.0'"),
        ),
    ]
    for idx, (rel_path, mutator) in enumerate(drift_cases):
        case_dir = tmp_path / f"tc_{idx}"
        _copy_contract_inputs(case_dir)
        target = case_dir / rel_path
        target.write_text(mutator(target.read_text(encoding="utf-8")), encoding="utf-8")
        assert toolchain_contract.run_contract(case_dir) == 1, rel_path

    missing_dir = tmp_path / "missing_tc"
    missing_dir.mkdir()
    with pytest.raises(FileNotFoundError):
        toolchain_contract.load_toolchain(missing_dir)

    minio_dir = tmp_path / "minio_bad"
    _copy_contract_inputs(minio_dir)
    minio_yml = minio_dir / ".github/actions/setup-minio/action.yml"
    minio_img = toolchain_contract.load_toolchain(minio_dir)["images"]["minio"]
    minio_yml.write_text(
        minio_yml.read_text(encoding="utf-8")
        .replace("name: Start MinIO", "name: Start object storage", 1)
        .replace(minio_img, "invalid.example/minio:drift", 1),
        encoding="utf-8",
    )
    assert toolchain_contract.run_contract(minio_dir) == 1
    minio_yml.unlink()
    assert toolchain_contract.run_contract(minio_dir) == 1

    monkeypatch.setattr(
        sys, "argv", ["check_toolchain_contract.py", "--repo-root", str(ROOT)]
    )
    assert toolchain_contract.main() == 0
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(
            Path(toolchain_contract.__file__).as_posix(), run_name="__main__"
        )
    assert exc_info.value.code == 0


@pytest.mark.parametrize(
    ("path", "image_key"),
    [
        (path, image)
        for path in (".github/actions/setup-minio/action.yml", "docker-compose.yml")
        for image in ("minio", "minio_client")
    ],
)
def test_minio_image_drift_fails_in_each_environment(
    tmp_path: Path, path: str, image_key: str
) -> None:
    """AC-testing.toolchain.1"""
    _copy_contract_inputs(tmp_path)
    image = toolchain_contract.load_toolchain(tmp_path)["images"][image_key]
    target = tmp_path / path
    parts = target.read_text(encoding="utf-8").split(image)
    assert len(parts) > 1
    target.write_text(
        parts[0] + "invalid.example/minio:drift" + image.join(parts[1:]),
        encoding="utf-8",
    )
    assert toolchain_contract.run_contract(tmp_path) == 1


@pytest.mark.parametrize("quote", ["", "'", '"'])
def test_minio_image_formatting_variants_are_accepted(
    tmp_path: Path, quote: str
) -> None:
    """AC-testing.toolchain.1"""
    _copy_contract_inputs(tmp_path)
    image = toolchain_contract.load_toolchain(tmp_path)["images"]["minio"]
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(
        compose.read_text(encoding="utf-8").replace(
            f"image: {image}", f"image:  {quote}{image}{quote}  # same immutable image"
        ),
        encoding="utf-8",
    )
    assert toolchain_contract.run_contract(tmp_path) == 0

    action_dir = tmp_path / f"act_{len(quote)}"
    _copy_contract_inputs(action_dir)
    action = action_dir / ".github/actions/setup-minio/action.yml"
    action.write_text(
        action.read_text(encoding="utf-8").replace(image, f"{quote}{image}{quote}"),
        encoding="utf-8",
    )
    assert toolchain_contract.run_contract(action_dir) == 0


def test_AC_testing_preflight_1_lockfile_registry_and_preflight_wiring(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-testing.preflight.1"""
    discovered = lockfile_registry.discover_lockfiles(ROOT)
    rel_paths = {p.relative_to(ROOT).as_posix() for p in discovered}
    assert "apps/frontend/package-lock.json" in rel_paths
    assert lockfile_registry.violations(ROOT) == []
    assert lockfile_registry.main(["--repo-root", str(ROOT)]) == 0

    for path in (
        "package-lock.json",
        "apps/frontend/package-lock.json",
        ".opencode/package-lock.json",
        "tools/check_lockfile_registry.py",
        "common/testing/lockfile_registry.py",
    ):
        names = {c.name for c in preflight.select_checks([path], tier="static")}
        assert "lockfile-registry" in names, f"{path} did not select lockfile-registry"

    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    lint_commands = "\n".join(
        str(s.get("run", "")) for s in workflow["jobs"]["lint"]["steps"]
    )
    assert "tools/check_lockfile_registry.py" in lint_commands

    clean_root = tmp_path / "clean"
    lockfile = _write_lockfile(
        clean_root / "apps/frontend/package-lock.json",
        {
            "": {"name": "frontend", "version": "0.1.0"},
            "node_modules/next": {
                "version": "15.0.0",
                "resolved": "https://registry.npmjs.org/next/-/next-15.0.0.tgz",
            },
        },
    )
    assert lockfile_registry.scan_lockfile(lockfile, repo_root=clean_root) == []
    assert lockfile_registry.main(["--repo-root", str(clean_root)]) == 0

    bad_root = tmp_path / "bad"
    bad_root.mkdir()
    assert lockfile_registry.main(["--repo-root", str(bad_root)]) == 1
    bad_lock = bad_root / "package-lock.json"
    for invalid_payload in ("{not-valid-json", "{}\n", '{"packages": {}}\n'):
        bad_lock.write_text(invalid_payload, encoding="utf-8")
        assert lockfile_registry.main(["--repo-root", str(bad_root)]) == 1
    _write_lockfile(bad_lock, {"": {"name": "frontend", "version": "0.1.0"}})
    assert lockfile_registry.main(["--repo-root", str(bad_root)]) == 1

    mirror_root = tmp_path / "mirror"
    _write_lockfile(
        mirror_root / "apps/frontend/package-lock.json",
        {
            "": {"name": "frontend", "version": "0.1.0"},
            "node_modules/clean-pkg": {
                "version": "1.0.0",
                "resolved": "https://registry.npmjs.org/clean-pkg/-/clean-pkg-1.0.0.tgz",
            },
            "node_modules/@private/mirror-pkg": {
                "version": "2.1.0",
                "resolved": "https://npm.shopee.io/@private/mirror-pkg/-/mirror-pkg-2.1.0.tgz",
            },
            "node_modules/corp-pkg": {
                "version": "3.0.0",
                "resolved": "https://registry-NonPublic.internal.example/corp-pkg/-/corp-pkg-3.0.0.tgz",
            },
        },
    )
    assert lockfile_registry.main(["--repo-root", str(mirror_root)]) == 1
    err = capsys.readouterr().err
    assert "apps/frontend/package-lock.json" in err
    assert "node_modules/@private/mirror-pkg" in err
    assert "node_modules/corp-pkg" in err


def test_AC_runtime_sdk_pin_1_agreement_stdlib_cli_and_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC-runtime.sdk-pin.1"""
    backend = tmp_path / "apps/backend"
    backend.mkdir(parents=True)
    version = "1.9.2"
    filename = f"infra2_sdk-{version}-py3-none-any.whl"
    url = f"https://github.com/wangzitian0/infra2-sdk/releases/download/v{version}/{filename}"
    project = "[project]\ndependencies = [" + json.dumps(f"infra2-sdk @ {url}") + "]\n"
    lock = (
        '[[package]]\nname = "infra2-sdk"\nversion = "1.9.2"\n'
        f'source = {{ url = "{url}" }}\n'
        f'wheels = [{{ url = "{url}", hash = "sha256:{"a" * 64}" }}]\n'
    )
    (backend / "pyproject.toml").write_text(project, encoding="utf-8")
    (backend / "uv.lock").write_text(lock, encoding="utf-8")
    assert read_sdk_pin(tmp_path) == (url, "a" * 64, filename)

    for corrupted in (
        lock.replace('version = "1.9.2"', 'version = "1.9.1"'),
        lock.replace('version = "1.9.2"', 'version = "latest"'),
        lock.replace("a" * 64, "not-a-digest"),
        lock.replace(url, url.replace("1.9.2", "1.9.3")),
        lock.replace(lock.splitlines()[-1], 'wheels = "invalid"'),
        lock.replace("wheels = [", "wheels = [42, "),
        lock.replace(f'"sha256:{"a" * 64}"', "42"),
        lock + lock,
    ):
        (backend / "uv.lock").write_text(corrupted, encoding="utf-8")
        with pytest.raises(ValueError, match="infra2-sdk"):
            read_sdk_pin(tmp_path)

    (backend / "uv.lock").write_text(lock, encoding="utf-8")
    (backend / "pyproject.toml").write_text(
        project.replace("1.9.2", "1.9.3"), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="infra2-sdk"):
        read_sdk_pin(tmp_path)

    monkeypatch.setattr(sys, "argv", ["tools/sdk_pin.py"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(ROOT / "tools/sdk_pin.py"), run_name="__main__")
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip().split() == list(read_sdk_pin(ROOT))

    stdlib_proc = subprocess.run(
        [sys.executable, "-S", str(ROOT / "tools/sdk_pin.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert stdlib_proc.stdout.strip().split() == list(read_sdk_pin(ROOT))

    cli_root = tmp_path / "cli_root"
    cli_backend = cli_root / "apps/backend"
    cli_backend.mkdir(parents=True)
    for fn in ("pyproject.toml", "uv.lock"):
        (cli_backend / fn).write_bytes((ROOT / "apps/backend" / fn).read_bytes())
    monkeypatch.setattr(sdk_pin, "ROOT_DIR", cli_root)
    expected = read_sdk_pin(cli_root)
    assert sdk_pin.main([]) == 0
    assert capsys.readouterr().out == " ".join(expected) + "\n"
    with pytest.raises(SystemExit) as err_exc:
        sdk_pin.main(["--unexpected"])
    assert err_exc.value.code == 2
    (cli_backend / "uv.lock").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="uv.lock.*package"):
        sdk_pin.main([])


@pytest.mark.parametrize(
    ("filename", "content", "field"),
    [
        ("pyproject.toml", "", "project"),
        ("pyproject.toml", '[project]\ndependencies = "invalid"\n', "dependencies"),
        ("pyproject.toml", "[project]\ndependencies = [42]\n", "dependencies"),
        ("uv.lock", "", "package"),
        ("uv.lock", 'package = "invalid"\n', "package"),
        ("uv.lock", "package = [42]\n", "package"),
        ("uv.lock", '[[package]]\nversion = "1.5.1"\n', "package"),
    ],
)
def test_sdk_pin_reports_malformed_field(
    tmp_path: Path, filename: str, content: str, field: str
) -> None:
    """AC-runtime.sdk-pin.1"""
    backend = tmp_path / "apps/backend"
    backend.mkdir(parents=True)
    for name in ("pyproject.toml", "uv.lock"):
        (backend / name).write_text(
            (ROOT / "apps/backend" / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    (backend / filename).write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=f"{filename}.*{field}"):
        read_sdk_pin(tmp_path)


def test_background_jobs_dependencies_and_cli() -> None:
    import src.main as main_module
    from src.observability import telemetry_metrics
    from src.runtime import BACKGROUND_JOBS, DEPENDENCY_MANIFEST

    job_names = [job.name for job in BACKGROUND_JOBS]
    cli_names = [job.cli_name for job in BACKGROUND_JOBS]
    assert len(job_names) == len(set(job_names)) >= 4
    assert len(cli_names) == len(set(cli_names))
    assert set(main_module.BACKGROUND_JOB_LOOPS) == set(job_names)
    assert set(main_module.BACKGROUND_JOB_ONCE) == set(job_names)

    registered_metrics = {
        *(name for _k, name, _d in telemetry_metrics._COUNTER_SPECS),
        *(name for _k, name, _d in telemetry_metrics._HISTOGRAM_SPECS),
    }
    for job in BACKGROUND_JOBS:
        assert job.failure_metric in registered_metrics

    main_source = (BACKEND_DIR / "src/main.py").read_text(encoding="utf-8")
    tree = ast.parse(main_source)
    task_calls = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "create_task"
    ]
    assert len(task_calls) == 1

    pyproject = tomllib.loads(
        (BACKEND_DIR / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert "main.py" not in pyproject["tool"]["coverage"]["run"]["omit"]

    ci_workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    tooling_coveragerc = ci_workflow.split("cat > /tmp/tooling.coveragerc <<'EOF'", 1)[
        1
    ].split("EOF", 1)[0]
    assert "apps/backend/src/main.py" not in tooling_coveragerc

    py_bin = str(BACKEND_DIR / ".venv/bin/python")
    proc = subprocess.run(
        [py_bin, "tools/cli.py", "job", "--list"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    for job in BACKGROUND_JOBS:
        assert job.cli_name in proc.stdout and job.concurrency in proc.stdout
    bad_proc = subprocess.run(
        [py_bin, "tools/cli.py", "job", "--run-once", "missing-job"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert bad_proc.returncode != 0

    expected_consumers = {
        "database": ("async_session_maker", "get_db", "SQLAlchemy"),
        "object_storage": ("StorageService",),
        "llm": ("settings.ai_provider", "to_llm_settings", "ai_api_key"),
        "cache": ("redis_url", "is_allowed_async"),
        "workflow_engine": ("prefect_api_url",),
        "telemetry": ("otel_exporter_otlp_endpoint",),
        "analytics": ("openpanel_api_url", "openpanel_client_id"),
        "market_data": ("market_data_yahoo_timeout_seconds",),
    }
    assert set(expected_consumers) == DEPENDENCY_MANIFEST.names()
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((BACKEND_DIR / "src").rglob("*.py"))
        if path.relative_to(BACKEND_DIR / "src").as_posix()
        not in {"boot.py", "config.py"}
        and not path.relative_to(BACKEND_DIR / "src")
        .as_posix()
        .startswith(("runtime/", "schemas/"))
    )
    missing = [
        dep
        for dep, markers in expected_consumers.items()
        if not any(m in combined for m in markers)
    ]
    assert missing == [], (
        f"DEPENDENCY_MANIFEST entries with zero runtime consumers: {missing}"
    )


def test_AC1_10_4_csp_script_src_allows_external_hosts_and_blocks_unsafe_eval() -> None:
    """AC1.10.4"""
    match = re.search('"script-src ([^"]+)"', NEXT_CONFIG.read_text(encoding="utf-8"))
    assert match, "no script-src directive found in next.config.mjs CSP"
    directive = match.group(1)

    analytics_match = re.search(
        r'DEFAULT_OPENPANEL_API_URL\s*=\s*"https://([^/"]+)',
        ANALYTICS.read_text(encoding="utf-8"),
    )
    assert analytics_match, "expected OpenPanel script host in RootClients.tsx"
    host = analytics_match.group(1)
    assert (
        f"https://{host}" in directive
        or f"https://*.{host.split('.', 1)[1]}" in directive
    )
    assert "'unsafe-eval'" not in directive
