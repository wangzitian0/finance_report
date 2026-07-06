"""Contract: every env var the runtime dependency manifest declares is a
recognized config key (issue #1623).

The manifest (`apps/backend/src/runtime/base/manifest.py`) is the single
declaration of "what env each dependency needs, and in which tiers". If it
names an env var that `config.py` does not know, the two have drifted and a
required key can be silently absent in a deployed tier (the class of gap behind
the preview `LLM_ENCRYPTION_KEYS` 503). Static AST parse — no backend import.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "apps" / "backend" / "src" / "runtime" / "base" / "manifest.py"
CONFIG = ROOT / "apps" / "backend" / "src" / "config.py"

# Env vars read outside the Settings schema (OTEL/OpenPanel are read via
# os.getenv at request time, not Pydantic fields) — recognized, not drift.
_READ_OUTSIDE_CONFIG = {
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT",
    "OPENPANEL_CLIENT_ID",
    "OPENPANEL_CLIENT_SECRET",
    "OPENPANEL_SCRIPT_URL",
    "OPENPANEL_API_URL",
}


def _manifest_env_vars() -> set[str]:
    """All string literals inside `env_vars=frozenset({...})` in the manifest."""
    tree = ast.parse(MANIFEST.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "env_vars":
            for s in ast.walk(node.value):
                if (
                    isinstance(s, ast.Constant)
                    and isinstance(s.value, str)
                    and s.value.isupper()
                ):
                    found.add(s.value)
    return found


def _config_known_env_keys() -> set[str]:
    """Every env-var name config.py recognizes: AliasChoices args + string
    validation_alias values + uppercase constants."""
    tree = ast.parse(CONFIG.read_text(encoding="utf-8"))
    known: set[str] = set()
    for node in ast.walk(tree):
        # String literals (AliasChoices args, explicit validation_alias values).
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            v = node.value
            if v.isupper() and "_" in v:
                known.add(v)
        # Pydantic maps a field `database_url` to env `DATABASE_URL` by default.
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            known.add(node.target.id.upper())
    return known


def test_every_manifest_env_var_is_a_known_config_key() -> None:
    manifest_vars = _manifest_env_vars()
    assert manifest_vars, "expected to parse env_vars out of the dependency manifest"
    known = _config_known_env_keys() | _READ_OUTSIDE_CONFIG
    unknown = {v for v in manifest_vars if v not in known}
    assert not unknown, (
        "dependency manifest declares env var(s) that config.py does not recognize "
        f"(drift): {sorted(unknown)}. Add them to Settings/AliasChoices in config.py "
        "or to the read-outside-config allowlist if they are read via os.getenv."
    )
