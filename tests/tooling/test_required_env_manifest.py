"""App-specific rules of the environment manifests. The infra2 SDK tests its own checks."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from common.runtime import env_manifests as gen  # noqa: E402

HOOKS_PATH = gen.ROOT_DIR / "runtime-hooks.manifest.json"


def _committed_manifest() -> dict:
    return json.loads((gen.ROOT_DIR / gen.BACKEND_MANIFEST).read_text(encoding="utf-8"))


def _by_env() -> dict:
    return {field.env: field for field in gen.specs()[0].build().fields}


def test_AC_runtime_guard_proofs_11_check_passes_on_the_committed_tree(capsys):
    "AC-runtime.guard-proofs.11"
    assert gen.main(["--check"]) == 0, capsys.readouterr().out
    assert "env manifests: ok" in capsys.readouterr().out


def test_check_reads_the_hand_written_frontend_manifest(tmp_path, monkeypatch, capsys):
    frontend = json.loads((gen.ROOT_DIR / gen.FRONTEND_MANIFEST).read_text(encoding="utf-8"))
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
    monkeypatch.setattr(gen, "HAND_WRITTEN", (str(bad),))
    assert gen.main(["--check"]) == 1
    assert "ENV is deprecated: use ENVIRONMENT" in capsys.readouterr().out


def test_check_reds_on_a_stale_env_example(tmp_path, monkeypatch, capsys):
    stale = tmp_path / ".env.example"
    stale.write_text(gen.ENV_EXAMPLE_PATH.read_text(encoding="utf-8").replace("DEBUG=true", "DEBUG=false"))
    monkeypatch.setattr(gen, "ENV_EXAMPLE_PATH", stale)
    assert gen.main(["--check"]) == 1
    assert "+DEBUG=true" in capsys.readouterr().out


def test_AC_runtime_guard_proofs_12_every_vault_field_reaches_manifest_and_env_example():
    "AC-runtime.guard-proofs.12"
    fields = gen.collect_backend_fields()
    by_env = {entry["env"]: entry for entry in _committed_manifest()["fields"]}
    env_example_keys = gen.env_example_documented_keys(gen.ENV_EXAMPLE_PATH.read_text(encoding="utf-8"))
    vault_fields = [f for f in fields if f["vault"]]
    assert vault_fields, "no vault-tagged fields found — the gate would be vacuous"
    for field in vault_fields:
        assert by_env[field["key"]]["injected"] is True, field["key"]
        assert field["key"] in env_example_keys, f"vault-tagged {field['key']} missing from .env.example"
    assert _committed_manifest()["source"] == gen.MANIFEST_SOURCE


def test_AC_runtime_guard_proofs_13_every_field_names_its_producer():
    "AC-runtime.guard-proofs.13"
    by_env = _by_env()
    assert by_env["DATABASE_URL"].provided_by == "finance_report/postgres:POSTGRES_PASSWORD"
    api_key = by_env["LLM_API_KEY"]
    assert (api_key.source, api_key.empty_ok, api_key.store_key, api_key.aliases) == ("human", True, "LLM_API_KEY", ())
    for env_name in ("GIT_COMMIT_SHA", "CONFIGURATION_SHA256"):
        assert by_env[env_name].source == "release" and by_env[env_name].injected, env_name
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
    assert by_env["OPENPANEL_CLIENT_ID"].empty_ok and by_env["S3_PUBLIC_BUCKET"].empty_ok
    for model_env in ("LLM_LARGE_MODEL", "LLM_SMALL_MODEL", "LLM_MULTIMODAL_MODEL", "PREFECT_WORKER_QUERY_SECONDS"):
        assert by_env[model_env].source == "code", model_env
    assert by_env["ENVIRONMENT"].aliases == ()
    declared = {name for f in by_env.values() for name in (f.env, *f.aliases)}
    for retired in ("ENV", "INFRA_ENVIRONMENT", "LARGE_MODEL", "SMALL_MODEL", "MULTIMODAL_MODEL", "PRIMARY_MODEL"):
        assert retired not in declared, retired


def test_AC_runtime_env_empty_values_1_no_field_declares_an_alias_chain():
    """An empty value of one alias shadows the rest of its chain. With no chain, no shadow."""
    "AC-runtime.env-empty-values.1"
    chains = {f.env: f.aliases for f in _by_env().values() if f.aliases}
    assert chains == {}, f"an alias chain is back; add an empty-value scan for it first: {chains}"


def test_AC_runtime_guard_proofs_14_sensitive_credentials():
    "AC-runtime.guard-proofs.14"
    by_env = _by_env()
    assert by_env["DATABASE_URL"].sensitive is True
    assert by_env["REDIS_URL"].sensitive is True


def test_canonical_model_names_reach_the_llm_settings():
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
    legacy = real.Settings(_env_file=None, AI_API_KEY="tok-legacy", SMALL_MODEL="legacy-small", ENV="staging")
    assert legacy.to_llm_settings().api_key == ""
    assert legacy.small_model != "legacy-small"
    assert legacy.environment == "development"


def _hooks_payload() -> dict:
    return json.loads(HOOKS_PATH.read_text(encoding="utf-8"))


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "runtime-hooks.manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_runtime_hooks_gate_errors_is_empty_for_the_committed_manifest():
    assert gen.runtime_hooks_gate_errors() == []


@pytest.mark.parametrize("old_version", [1, 2])
def test_runtime_hooks_gate_errors_rejects_old_schema(tmp_path, old_version):
    payload = _hooks_payload()
    payload["schema_version"] = old_version
    errors = gen.runtime_hooks_gate_errors(_write(tmp_path, payload))
    assert len(errors) == 1 and "schema_version" in errors[0], errors


def test_runtime_hooks_gate_errors_reports_a_cell_without_checks(tmp_path):
    payload = _hooks_payload()
    removed = {"staging_core_e2e", "ai_provider_connectivity", "staging_ai_ocr"}
    payload["checks"] = [c for c in payload["checks"] if c["id"] not in removed]
    assert gen.runtime_hooks_gate_errors(_write(tmp_path, payload)) == [
        "runtime-hooks.manifest.json: no check runs in cell 'staging.post'"
    ]


def test_runtime_hooks_gate_errors_reports_prod_post_without_check(tmp_path):
    payload = _hooks_payload()
    payload["checks"][0].pop("cells")
    assert gen.runtime_hooks_gate_errors(_write(tmp_path, payload)) == [
        "runtime-hooks.manifest.json: no check runs in cell 'prod.post'"
    ]


def test_runtime_hooks_gate_errors_reports_unknown_env_key(tmp_path):
    payload = _hooks_payload()
    payload["checks"][1]["optional_env"] = [*payload["checks"][1].get("optional_env", []), "NOT_A_REAL_KEY"]
    assert any("'NOT_A_REAL_KEY'" in e for e in gen.runtime_hooks_gate_errors(_write(tmp_path, payload)))


def test_smoke_script_refuses_a_deployed_environment_without_a_version_ref():
    script = gen.ROOT_DIR / "common" / "runtime" / "shell" / "smoke_test.sh"
    base = {k: v for k, v in os.environ.items() if k != "APP_VERSION_REF"}
    for env_name in ("preview", "staging", "production"):
        # EXPECTED_SHA is retired: it does not satisfy the version-ref rule.
        env = {**base, "ENVIRONMENT": env_name, "EXPECTED_SHA": "abc1234"}
        res = subprocess.run(
            ["bash", str(script), "http://127.0.0.1:9"], env=env, capture_output=True, text=True, timeout=30
        )
        assert res.returncode == 2 and "APP_VERSION_REF" in res.stdout, (env_name, res.stdout)
