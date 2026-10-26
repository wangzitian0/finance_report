#!/usr/bin/env python3
"""
Environment variable consistency validation.

Validates consistency between the ``Settings`` model (Backend Code) and
.env.example (Documentation). The ``Settings`` env names come from the model
itself (``settings_env_keys``), not from a parse of ``config.py``.

Note (Infra-014 C3): the backend block of ``.env.example`` and
``common/runtime/env-reference.generated.md`` are now GENERATED from the
``apps/backend/src/config.py`` pydantic Settings metadata by
``tools/generate_env_reference.py``. The .env.example <-> config.py leg below is
therefore guaranteed by generation (the generated block contains every backend
key); ``tools/generate_env_reference.py --check`` is the authoritative drift
guard for that file. The versioned
``common/runtime/required-env.generated.json`` artifact is the only App ->
infra2 secret-injection contract; Finance Report does not read infra2 source.

Usage:
    python tools/check_env_keys.py           # Check consistency
    python tools/check_env_keys.py --diff    # Show detailed diff
    python tools/check_env_keys.py --fix     # Generate fix suggestions
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from src.runtime.base.env_classification import settings_env_keys

from .project_root import get_project_root


def parse_env_example(path: Path) -> set[str]:
    """Extract the KEY list .env.example documents.

    A key counts as documented when it is assigned (``KEY=value``) **or** shipped
    as a commented canonical example (``# KEY=``). The commented form is the
    required shape for a key whose ``Settings`` field is resolved through an
    ``AliasChoices`` chain and has no example value: an empty assignment is a
    value, not "unset", so it would shadow every later alias in that chain
    (AC-runtime.env-empty-values.1,
    ``tests/tooling/test_env_empty_value_producers.py``). Prose comments are not
    matched — inside a comment the ``=`` must follow the key name directly, so
    "# Rotate = prepend a new key" is prose, not a documented key.
    """
    if not path.exists():
        print(f"WARNING: .env.example not found: {path}")
        return set()

    content = path.read_text()
    keys = set()

    # An assignment: optional 'export ' prefix, key name, optional whitespace, '='.
    assigned = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
    # A commented canonical example: '#', the key, then '=' with nothing between.
    commented = re.compile(r"^#\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=")

    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue

        match = (commented if line.startswith("#") else assigned).match(line)
        if match:
            keys.add(match.group(1))

    return keys


def settings_env_key_sets() -> dict[str, frozenset[str]]:
    """Map each ``Settings`` field to the env-var names it reads."""
    # Lazy: config.py builds the settings singleton at import time.
    from src.config import Settings

    return {name: settings_env_keys(Settings, name) for name in Settings.model_fields}


def check_consistency(field_keys: dict[str, frozenset[str]], env_example_keys: set[str]) -> dict:
    """Check that .env.example documents every ``Settings`` field.

    A field counts as documented when any env name it reads is documented.
    """
    accepted_env_names = set().union(*field_keys.values())

    # Every Settings field MUST be documented in .env.example. Report one valid
    # key per undocumented field.
    undocumented = {min(keys) for keys in field_keys.values() if not keys & env_example_keys}

    # Keys in .env.example NOT in Settings (information only; might be frontend keys).
    suspicious_extra_keys = {
        k
        for k in env_example_keys - accepted_env_names
        if not k.startswith("NEXT_PUBLIC_") and not k.startswith("DOKPLOY_")
    }

    return {
        "config_field_count": len(field_keys),
        "env_example_keys": env_example_keys,
        "undocumented_in_example": undocumented,
        "suspicious_extra_keys": suspicious_extra_keys,
        "is_consistent": not undocumented,
    }


def print_report(result: dict, verbose: bool = False) -> None:
    """Print validation report."""
    print("\n" + "=" * 60)
    print("Environment Variable Consistency Check")
    print("=" * 60)

    print(f"\nconfig.py:       {result['config_field_count']:3d} fields")
    print(f".env.example:    {len(result['env_example_keys']):3d} keys")

    # Error: Backend uses key, Documentation doesn't have it
    if result["undocumented_in_example"]:
        print("\n[ERROR] In config.py but NOT in .env.example (Undocumented):")
        for key in sorted(result["undocumented_in_example"]):
            print(f"   - {key}")

    # Warning: Documentation has key, Backend doesn't use it
    if verbose and result["suspicious_extra_keys"]:
        print("\n[INFO] In .env.example but NOT in config.py (Frontend/Infra?):")
        for key in sorted(result["suspicious_extra_keys"]):
            print(f"   - {key}")

    if result["is_consistent"]:
        print("\n✅ Consistency check passed!")
    else:
        print("\n❌ Inconsistency found, please fix and retry")

    print("\n" + "=" * 60)


def generate_fix_suggestions(result: dict) -> None:
    """Generate fix suggestions."""

    if result["undocumented_in_example"]:
        print("\n[FIX] Add to .env.example:")
        print("-" * 40)
        for key in sorted(result["undocumented_in_example"]):
            print(f"{key}=")
        print("-" * 40)


def main():
    parser = argparse.ArgumentParser(description="Environment variable consistency check")
    parser.add_argument("--diff", action="store_true", help="Show detailed diff")
    parser.add_argument("--fix", action="store_true", help="Generate fix suggestions")
    args = parser.parse_args()

    root = get_project_root()

    env_example_path = root / ".env.example"

    print(f"Project root: {root}")
    print(f".env.example:  {env_example_path.relative_to(root)}")

    result = check_consistency(settings_env_key_sets(), parse_env_example(env_example_path))
    print_report(result, verbose=args.diff)

    if args.fix:
        generate_fix_suggestions(result)

    sys.exit(0 if result["is_consistent"] else 1)


if __name__ == "__main__":
    main()
