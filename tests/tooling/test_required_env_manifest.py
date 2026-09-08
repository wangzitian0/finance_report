"""#1828 G-injection-drift-gate (app side) — the required-env manifest.

``tools/generate_env_reference.py`` derives a machine-readable required-env
manifest (``common/runtime/required-env.generated.json``) from the same single
source of truth as ``.env.example``: the ``Settings`` pydantic metadata in
``apps/backend/src/config.py``. infra2 consumes the manifest to check its
``secrets.ctmpl`` injection template in CI (the #876 artifact boundary), so a
new vault-tagged config field can no longer merge green while the injection
source lags.

Bidirectional lock:
- config -> artifacts: every vault-tagged config field must appear in the
  committed manifest AND in ``.env.example`` (a field added without
  regenerating reds this gate);
- artifacts -> config: every committed manifest entry must map back to a live
  config field (a removed/renamed field leaving a stale entry reds this gate).
"""

import json
import sys

import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tools import generate_env_reference as gen  # noqa: E402


def _committed_manifest() -> dict:
    return json.loads(gen.REQUIRED_ENV_MANIFEST_PATH.read_text(encoding="utf-8"))


def test_AC_runtime_guard_proofs_11_manifest_matches_live_config_bidirectionally():
    """AC-runtime.guard-proofs.11 (#1828 G-injection-drift-gate): the committed
    manifest equals the manifest rendered from the live ``Settings`` metadata —
    exact equality kills BOTH drift directions: a new (e.g. vault-tagged) field
    missing from the manifest, and a stale manifest entry whose field no longer
    exists in config.py."""
    rendered = json.loads(
        gen.render_required_env_manifest(gen.collect_backend_fields())
    )
    committed = _committed_manifest()

    assert committed == rendered, (
        "common/runtime/required-env.generated.json is out of date with "
        "apps/backend/src/config.py. Run: python tools/generate_env_reference.py"
    )


def test_AC_runtime_guard_proofs_12_every_vault_field_reaches_manifest_and_env_example():
    """AC-runtime.guard-proofs.12 (#1828 G-injection-drift-gate): every
    vault-tagged config field appears in the committed manifest (vault=true)
    and as a key in ``.env.example``; and every committed manifest entry maps
    back to a live config field with a matching env key."""
    fields = gen.collect_backend_fields()
    committed = _committed_manifest()
    manifest_by_key = {entry["env"]: entry for entry in committed["fields"]}
    env_example = gen.ENV_EXAMPLE_PATH.read_text(encoding="utf-8")
    env_example_keys = {
        line.split("=", 1)[0]
        for line in env_example.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }

    # Direction 1: config -> artifacts.
    vault_fields = [f for f in fields if f["vault"]]
    assert vault_fields, "no vault-tagged fields found — the gate would be vacuous"
    for field in vault_fields:
        assert field["key"] in manifest_by_key, (
            f"vault-tagged {field['key']} missing from manifest"
        )
        assert manifest_by_key[field["key"]]["vault"] is True
        assert field["key"] in env_example_keys, (
            f"vault-tagged {field['key']} missing from .env.example"
        )

    # Direction 2: artifacts -> config (kills stale entries).
    live_by_key = {f["key"]: f for f in fields}
    settings_field_names = set(gen._settings_model().model_fields)
    for entry in committed["fields"]:
        assert entry["env"] in live_by_key, (
            f"stale manifest entry {entry['env']} has no live config field"
        )
        assert entry["field"] in settings_field_names, (
            f"manifest entry {entry['env']} names unknown Settings field {entry['field']!r}"
        )
        assert entry["field"] == live_by_key[entry["env"]]["field"]


def test_write_mode_emits_the_manifest_artifact(tmp_path, monkeypatch):
    """The generator's write mode materializes the manifest next to the other
    generated env artifacts, byte-identical to the rendered form (so `--check`
    and write can never disagree)."""
    # ROOT_DIR only feeds the relative-path prints here; BACKEND_DIR (used to
    # load Settings) was bound at import time and stays real.
    monkeypatch.setattr(gen, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(gen, "ENV_EXAMPLE_PATH", tmp_path / ".env.example")
    monkeypatch.setattr(
        gen, "ENV_REFERENCE_DOC_PATH", tmp_path / "env-reference.generated.md"
    )
    monkeypatch.setattr(
        gen, "REQUIRED_ENV_MANIFEST_PATH", tmp_path / "required-env.generated.json"
    )
    monkeypatch.setattr(sys, "argv", ["generate_env_reference.py"])

    assert gen.main() == 0

    written = (tmp_path / "required-env.generated.json").read_text(encoding="utf-8")
    assert written == gen.render_required_env_manifest(gen.collect_backend_fields())
    assert json.loads(written)["fields"]


def test_check_mode_reds_on_stale_manifest(tmp_path, monkeypatch, capsys):
    """`--check` exits 1 (with a diff) when the committed manifest is stale —
    the CLI form of the drift gate (red-team path, permanently locked)."""
    stale = tmp_path / "required-env.generated.json"
    stale.write_text('{"fields": []}\n', encoding="utf-8")
    monkeypatch.setattr(gen, "REQUIRED_ENV_MANIFEST_PATH", stale)
    monkeypatch.setattr(sys, "argv", ["generate_env_reference.py", "--check"])

    assert gen.main() == 1
    assert "required-env.generated.json" in capsys.readouterr().out


def test_manifest_carries_the_consumer_contract_fields():
    """Each manifest entry carries what infra2's template check needs: the
    config field name, the canonical env var, aliases, vault tagging, and
    ``has_default`` (whether ``Settings`` defines a default value — no
    deploy-time semantics implied; protected runtimes may still reject
    specific development defaults at boot)."""
    committed = _committed_manifest()

    assert committed["source"] == "apps/backend/src/config.py::Settings"
    assert committed["fields"], "manifest has no entries"
    assert committed["contract_version"] == 2
    for entry in committed["fields"]:
        assert set(entry) >= {
            "field",
            "env",
            "aliases",
            "group",
            "vault",
            "has_default",
            "source",
            "empty_ok",
            "scope",
        }
        assert isinstance(entry["vault"], bool)
        assert isinstance(entry["has_default"], bool)
        assert isinstance(entry["aliases"], list)


def test_AC_runtime_guard_proofs_13_every_field_names_its_producer_and_the_offline_gate_is_green():
    """AC-runtime.guard-proofs.13 (#2005): the manifest is the infra2-sdk v2 contract. Every field names who produces
    its value; a ``vault`` (deployment-injected) field is never a plain code default
    unless the deployment injects it; the offline gate passes without infrastructure."""
    from infra2_sdk.ci import validate_manifest_offline
    from infra2_sdk.runtime.config_schema import EnvironmentManifest

    committed = _committed_manifest()
    manifest = EnvironmentManifest.from_dict(committed)
    assert validate_manifest_offline(manifest) == []
    by_env = {field.env: field for field in manifest.fields}
    assert (
        by_env["DATABASE_URL"].provided_by
        == "finance_report/postgres:POSTGRES_PASSWORD"
    )
    assert by_env["SECRET_KEY"].source == "runtime" and by_env["SECRET_KEY"].sensitive
    assert by_env["ZAI_API_KEY"].source == "human" and by_env["ZAI_API_KEY"].empty_ok
    assert by_env["GIT_COMMIT_SHA"].source == "release"
    # Values infra2's compose env states for finance_report/app are `decision`:
    # deployment-injected, never store-backed (so the agent template never renders
    # them). A field the compose does not set stays a `code` default.
    for env_name in (
        "ENVIRONMENT",
        "CORS_ORIGINS",
        "S3_ENDPOINT",
        "PREFECT_API_URL",
        "PRIMARY_MODEL",
        "API_RATE_LIMIT_REQUESTS",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OPENPANEL_CLIENT_ID",
    ):
        assert by_env[env_name].source == "decision", env_name
        assert by_env[env_name].injected and not by_env[env_name].store_backed, env_name
    assert (
        by_env["OPENPANEL_CLIENT_ID"].empty_ok and by_env["S3_PUBLIC_BUCKET"].empty_ok
    )
    assert (
        by_env["OCR_MODEL"].source == "code" and by_env["VISION_MODEL"].source == "code"
    )
    for entry in committed["fields"]:
        assert entry["source"] in {"human", "runtime", "release", "decision", "code"}, (
            entry["env"]
        )
        if entry["vault"]:
            assert entry["source"] != "code" or entry["injected"], entry["env"]


def test_AC_runtime_guard_proofs_13_unknown_source_class_name_exits_with_the_field_name(
    monkeypatch,
):
    """AC-runtime.guard-proofs.13 (#2005): the side table names settings fields; a typo
    must stop the generator with the offending name, not a stack trace (review on #2028).
    infra2-sdk raises ValueError for it; the tool turns that into a short SystemExit."""
    import types

    real = gen._settings_module()
    fake = types.SimpleNamespace(
        Settings=real.Settings,
        ENV_SOURCE_CLASSES={"not_a_setting": {"source": "human"}},
    )
    monkeypatch.setattr(gen, "_settings_module", lambda: fake)
    with pytest.raises(SystemExit) as stop:
        gen._environment_contract()
    assert "not_a_setting" in str(stop.value)
    assert str(stop.value).startswith("ENV_SOURCE_CLASSES:")
