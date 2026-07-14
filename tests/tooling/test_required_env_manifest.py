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
    config field name, the canonical env key, aliases, vault tagging, and
    whether the app has a default (i.e. whether injection is load-bearing)."""
    committed = _committed_manifest()

    assert committed["source"] == "apps/backend/src/config.py::Settings"
    assert committed["fields"], "manifest has no entries"
    for entry in committed["fields"]:
        assert set(entry) == {
            "field",
            "env",
            "aliases",
            "group",
            "vault",
            "has_default",
        }
        assert isinstance(entry["vault"], bool)
        assert isinstance(entry["has_default"], bool)
        assert isinstance(entry["aliases"], list)
