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
    assert {"DATABASE_URL", "PRIMARY_MODEL", "OTEL_EXPORTER_OTLP_ENDPOINT"} <= keys
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
    # PRIMARY_MODEL has no override, so its default is shown (AC-runtime.18.2 contract).
    assert "PRIMARY_MODEL=glm-5.1" in block


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
    # Alias keys are surfaced (e.g. ENV alias of ENVIRONMENT, AI_API_KEY of ZAI_API_KEY).
    assert "Alias of" in doc


def test_committed_files_are_up_to_date(monkeypatch):
    """generated == committed (the drift gate)."""
    monkeypatch.setattr(sys, "argv", ["generate_env_reference.py", "--check"])
    assert gen.main() == 0
