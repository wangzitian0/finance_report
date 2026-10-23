"""Infra-014 C3: the backend env reference is generated from config.py and
cannot drift. Exercises tools/generate_env_reference.py directly (so it counts
toward tooling coverage) and asserts the committed files are up to date.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tools import generate_env_reference as gen  # noqa: E402


def test_collect_backend_fields_are_grouped_env_fields():
    fields = gen.collect_backend_fields()
    keys = {f["key"] for f in fields}
    # A representative spread of backend env keys, all carrying a group.
    assert {"DATABASE_URL", "SMALL_MODEL", "OTEL_EXPORTER_OTLP_ENDPOINT"} <= keys
    assert all(f["group"] for f in fields)
    # cached_property helpers are not model_fields and must not appear.
    assert "CORS_ORIGINS_STR" not in keys


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, ""), (True, "true"), (False, "false"), (360.0, "360"), (5, "5")],
)
def test_render_value(value, expected):
    assert gen._render_value(value) == expected


def test_backend_block_uses_example_override_and_real_default():
    fields = gen.collect_backend_fields()
    block = gen.render_backend_block(fields)
    # Example override (localhost) is what .env.example shows.
    assert "DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432" in block
    # SMALL_MODEL has no override, so its default is shown (AC-runtime.18.2 contract).
    assert "SMALL_MODEL=glm-5.3-flash" in block


def test_render_env_example_replaces_managed_region_and_keeps_frontend():
    fields = gen.collect_backend_fields()
    existing = f"{gen.BEGIN_MARKER}\nSTALE=1\n{gen.END_MARKER}\n\n# Frontend Configuration\nNEXT_PUBLIC_API_URL=\n"
    out = gen.render_env_example(existing, fields)
    assert "STALE=1" not in out  # managed region replaced
    assert "NEXT_PUBLIC_API_URL=" in out  # frontend region preserved
    assert out.count(gen.BEGIN_MARKER) == 1


def test_reference_doc_splits_default_example_and_lists_aliases():
    fields = gen.collect_backend_fields()
    doc = gen.render_reference_doc(fields)
    assert "| Key | Default | Example | Vault | Group | Description |" in doc
    # Alias keys are surfaced (e.g. ENV alias of ENVIRONMENT).
    assert "Alias of" in doc


def test_alias_chain_field_without_a_value_is_rendered_as_one_commented_example():
    """AC-runtime.env-empty-values.1: an ``AliasChoices`` field whose example value
    is empty is emitted as a single commented canonical line, and its alias keys
    are not emitted at all — an assignment to empty is a value, not "unset", and
    would shadow the rest of the chain."""
    synthetic = [
        {
            "field": "test_empty_chain",
            "key": "TEST_EMPTY_CHAIN",
            "value": "",
            "description": "Test field with empty alias chain",
            "group": "App Settings",
            "vault": False,
            "extra_keys": [],
            "aliases": ["TEST_EMPTY_ALIAS"],
        }
    ]
    block = gen.render_backend_block(synthetic)

    assert "# TEST_EMPTY_CHAIN=" in block
    assert gen.ALIAS_CHAIN_EMPTY_NOTE in block
    for shadowed in ("\nTEST_EMPTY_CHAIN=", "\nTEST_EMPTY_ALIAS="):
        assert shadowed not in block
    # A chain whose value is NOT empty keeps its plain assignment + alias lines.
    real_block = gen.render_backend_block(gen.collect_backend_fields())
    assert "\nENVIRONMENT=development\n" in real_block
    assert "\nENV=development\n" in real_block


def test_alias_names_reads_the_alias_choices_chain():
    """``aliases`` mirrors the generated manifest's chain (canonical name dropped);
    a field with a single string alias, or none, has no chain."""
    by_field = {f["field"]: f for f in gen.collect_backend_fields()}

    assert by_field["environment"]["aliases"] == ["ENV"]
    # ZAI_API_KEY is the name that infra2 still supplies in production (#2487).
    assert by_field["ai_api_key"]["aliases"] == ["ZAI_API_KEY"]
    assert by_field["ai_base_url"]["aliases"] == []
    assert by_field["llm_encryption_keys"]["aliases"] == []
    assert by_field["ai_provider"]["aliases"] == []  # plain string validation_alias
    assert by_field["debug"]["aliases"] == []  # no validation_alias at all


def test_documented_keys_accept_the_commented_canonical_form():
    """ "Documented in .env.example" means assigned **or** shipped as ``# KEY=``.

    Inside a comment the ``=`` must follow the key directly, so prose (including
    prose whose first word happens to be followed by " = ") is never a key.
    """
    keys = gen.env_example_documented_keys(
        "# === AI Provider ===\n"
        "# AI provider API key (empty key = AI features disabled).\n"
        "# Rotate = prepend a new key and re-encrypt.\n"
        "# ZAI_API_KEY=\n"
        "export DEBUG=true\n"
        "DATABASE_URL = postgres://localhost/db\n"
    )
    assert keys == {"ZAI_API_KEY", "DEBUG", "DATABASE_URL"}


def test_committed_files_are_up_to_date(monkeypatch):
    """generated == committed (the drift gate)."""
    monkeypatch.setattr(sys, "argv", ["generate_env_reference.py", "--check"])
    assert gen.main() == 0
